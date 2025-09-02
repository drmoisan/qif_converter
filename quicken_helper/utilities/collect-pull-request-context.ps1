
<#PSScriptInfo
.VERSION 2.0.5
.GUID 7e3e9a2a-2d5a-4b0a-8d39-1e0cbe2f9c11
.AUTHOR ChatGPT (per user request)
.DESCRIPTION
Collect Git repository context for robust commit/PR messages.
PS 5.1 compatible; hardened against null outputs; safe extension parsing for rename lines.
#>

[CmdletBinding()]
param(
    [string]$Base,
    [string]$Head,
    [string]$Out = "logs\pr_context.txt",
    [string]$RepoRoot = ".",
    [switch]$Append,
    [switch]$NoUntracked
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param(
        [Parameter(Mandatory=$true)][string[]]$Args,
        [switch]$AllowNonZeroExit
    )
    $output = & git @Args 2>&1
    $code = $LASTEXITCODE
    $lines = @()
    if ($null -ne $output) {
        if ($output -is [System.Array]) {
            $lines = @($output)
        } else {
            $lines = @([string]$output)
        }
    }
    $stdout = ($lines -join "`n")
    if (-not $AllowNonZeroExit -and $code -ne 0) {
        $argLine = ($Args -join ' ')
        throw ("git {0} failed ({1}): {2}" -f $argLine, $code, $stdout)
    }
    return @{ Out = $stdout; Err = ""; Code = $code }
}

function Resolve-Repo {
    param([string]$Root)
    Push-Location $Root
    try {
        if (-not (Test-Path ".git")) {
            $top = (Invoke-Git @('rev-parse','--show-toplevel')).Out
            if (-not $top) { throw "Not a git repo: $Root" }
            Pop-Location
            Push-Location $top
        }
    } catch {
        Pop-Location
        throw
    }
}

function Write-Section { param([string]$Title) "`n===== $Title =====`n" }

function Count-Items { param($x) if ($null -eq $x) { 0 } else { @($x).Count } }


function Pick-Default-Base {
    $candidates = @('origin/main','origin/master','main','master','origin/develop','develop')
    foreach ($ref in $candidates) {
        $res = Invoke-Git -Args @('rev-parse','--verify','--quiet',$ref) -AllowNonZeroExit
        if ($res.Code -eq 0 -and $res.Out) { return $ref }
    }
    return $null
}

function Get-Branch {
    param([string]$Ref)
    if ([string]::IsNullOrWhiteSpace($Ref)) {
        return (Invoke-Git -Args @('rev-parse','--abbrev-ref','HEAD')).Out
    }
    return $Ref
}

function Collect-Remotes {
@"
$(Write-Section "Repository remotes")
$((Invoke-Git -Args @('remote','-v')).Out)
"@
}

function Collect-BranchMeta {
    $current = (Invoke-Git -Args @('rev-parse','--abbrev-ref','HEAD')).Out
    $upstream = (Invoke-Git -Args @('rev-parse','--abbrev-ref','--symbolic-full-name','@{u}') -AllowNonZeroExit).Out
    $upDisplay = if (-not [string]::IsNullOrWhiteSpace($upstream)) { $upstream } else { '(none)' }
@"
$(Write-Section "Current branch")
$current

$(Write-Section "Upstream")
$upDisplay
"@
}

function Collect-Status {
    param([switch]$NoUntracked)
    $short = (Invoke-Git -Args @('status','-sb')).Out
    $untracked = $null
    if (-not $NoUntracked) {
        $untracked = (Invoke-Git -Args @('ls-files','--others','--exclude-standard')).Out
    }
    $unDisplay = if (-not [string]::IsNullOrWhiteSpace($untracked)) { $untracked } else { "(none)" }
@"
$(Write-Section "Status (short)")
$short

$(Write-Section "Untracked files")
$unDisplay
"@
}

function Collect-WorkingTreeDiff {
    $stagedNameStatus = (Invoke-Git -Args @('diff','--cached','--name-status') -AllowNonZeroExit).Out
    $stagedDiff       = (Invoke-Git -Args @('diff','--cached') -AllowNonZeroExit).Out
    $unstagedNameStat = (Invoke-Git -Args @('diff','--name-status') -AllowNonZeroExit).Out
    $unstagedDiff     = (Invoke-Git -Args @('diff') -AllowNonZeroExit).Out
@"
$(Write-Section "Staged files (name-status)")
$($stagedNameStatus)

$(Write-Section "Staged diff")
$($stagedDiff)

$(Write-Section "Unstaged files (name-status)")
$($unstagedNameStat)

$(Write-Section "Unstaged diff")
$($unstagedDiff)
"@
}

function Parse-Numstat {
    param([string]$NumstatText)
    $adds = 0
    $dels = 0
    $files = @()
    foreach ($line in ($NumstatText -split "`n")) {
        if (-not $line) { continue }
        $parts = $line -split "`t"
        if ($parts.Count -ge 3) {
            $a = $parts[0]; $d = $parts[1]; $f = $parts[2]
            if ($a -match '^\d+$') { $adds += [int]$a }
            if ($d -match '^\d+$') { $dels += [int]$d }
            $files += $f
        }
    }
    return @{ Additions = $adds; Deletions = $dels; Files = $files }
}

function Normalize-DiffPath {
    param([string]$PathText)
    if ([string]::IsNullOrWhiteSpace($PathText)) { return $PathText }
    $t = $PathText.Trim('"').Trim()
    # Handle brace rename syntax: dir/{old => new}/file -> dir/new/file
    $t = [regex]::Replace($t, '\{[^{}]*\s=>\s([^{}]*)\}', '$1')
    # Handle simple rename: old => new  (take right side)
    if ($t -match '^\s*(.+?)\s=>\s(.+?)\s*$') { $t = $matches[2] }
    return $t
}

function Count-By-Ext {
    param([string[]]$Files)
    $map = @{}
    foreach ($f in $Files) {
        $name = Normalize-DiffPath -PathText $f
        $ext = "(unknown)"
        try {
            $e = [System.IO.Path]::GetExtension($name)
            if ([string]::IsNullOrEmpty($e)) { $ext = "(noext)" } else { $ext = $e }
        } catch {
            # Fallback: regex for trailing dot-segment
            if ($name -match '\.([A-Za-z0-9_]+)$') { $ext = ".$($matches[1])" } else { $ext = "(unknown)" }
        }
        if (-not $map.ContainsKey($ext)) { $map[$ext] = 0 }
        $map[$ext]++
    }
    $pairs = $map.GetEnumerator() | Sort-Object Name
    $lines = foreach ($p in $pairs) { "{0,8}  {1}" -f $p.Value, $p.Key }
    return ($lines -join "`n")
}

function Extract-IssueRefs {
    param([string]$Text)
    $set = New-Object System.Collections.Generic.HashSet[string]
    if ($Text) {
        $m = [regex]::Matches($Text, '(?<!\w)#\d+|\b[A-Z][A-Z0-9]+-\d+\b')
        foreach ($x in $m) { [void]$set.Add($x.Value) }
    }
    return ($set | Sort-Object)
}

function Summarize-ConventionalCommitTypes {
    param([string]$SubjectsText)
    $counts = [ordered]@{ feat=0; fix=0; refactor=0; perf=0; docs=0; test=0; chore=0; build=0; ci=0; style=0; other=0 }
    foreach ($line in ($SubjectsText -split "`n")) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            if ($line -match '^\s*(feat|fix|refactor|perf|docs|test|chore|build|ci|style)(\(|!|:)\b') {
                $t = $matches[1]
            } else {
                $t = 'other'
            }
            $counts[$t]++
        }
    }
    $pairs = $counts.GetEnumerator() | Where-Object { $_.Value -gt 0 }
    if (-not $pairs) { return "(no recognizable conventional commit types)" }
    ($pairs | ForEach-Object { "{0,-9} : {1}" -f $_.Name, $_.Value }) -join "`n"
}

function Collect-PRContext {
    param([string]$BaseRef, [string]$HeadRef)

    $base = (Invoke-Git -Args @('rev-parse','--verify',$BaseRef)).Out
    $head = (Invoke-Git -Args @('rev-parse','--verify',$HeadRef)).Out
    $mergeBase = (Invoke-Git -Args @('merge-base',$base,$head)).Out
    $range = "$mergeBase..$head"

    $oneline = (Invoke-Git -Args @('log','--date=short','--pretty=format:%h %ad %an %s',$range)).Out
    $subjects = (Invoke-Git -Args @('log','--pretty=%s',$range)).Out
    $authors  = (Invoke-Git -Args @('log','--format=%an <%ae>',$range)).Out -split "`n" | Where-Object { $_ -and $_.Trim() } | Sort-Object -Unique
    $nameStatus = (Invoke-Git -Args @('diff','--name-status',$mergeBase,$head)).Out
    $numstat    = (Invoke-Git -Args @('diff','--numstat',$mergeBase,$head)).Out
    $shortstat  = (Invoke-Git -Args @('diff','--shortstat',$mergeBase,$head)).Out
    $stat       = (Invoke-Git -Args @('diff','--stat',$mergeBase,$head)).Out

    $num = Parse-Numstat -NumstatText $numstat
    $extSummary = Count-By-Ext -Files $num.Files
    $issues = Extract-IssueRefs -Text ($oneline + "`n" + $subjects)
    $typeSummary = Summarize-ConventionalCommitTypes -SubjectsText $subjects

    $onelineDisplay  = if (-not [string]::IsNullOrWhiteSpace($oneline)) { $oneline } else { "(none)" }
    $authorsDisplay  = if ((Count-Items $authors) -gt 0) { (@($authors) -join "`n") } else { "(none)" }
    $nameStatDisplay = if (-not [string]::IsNullOrWhiteSpace($nameStatus)) { $nameStatus } else { "(none)" }
    $shortDisplay    = if (-not [string]::IsNullOrWhiteSpace($shortstat)) { $shortstat } else { "(none)" }
    $extDisplay      = if (-not [string]::IsNullOrWhiteSpace($extSummary)) { $extSummary } else { "(none)" }
    $issuesDisplay   = if ((Count-Items $issues) -gt 0) { (@($issues) -join ", ") } else { "(none)" }
    $statDisplay     = if (-not [string]::IsNullOrWhiteSpace($stat)) { $stat } else { "(none)" }

@"
$(Write-Section "PR Comparison")
Base: $BaseRef
Head: $HeadRef
Merge-base: $mergeBase
Range: $range

$(Write-Section "Commits in range")
$onelineDisplay

$(Write-Section "Conventional commit type summary")
$typeSummary

$(Write-Section "Authors")
$authorsDisplay

$(Write-Section "Changed files (name-status)")
$nameStatDisplay

$(Write-Section "Diff shortstat")
$shortDisplay

$(Write-Section "Additions/Deletions totals (from numstat)")
Additions: $($num.Additions)
Deletions: $($num.Deletions)

$(Write-Section "Files by extension")
$extDisplay

$(Write-Section "Referenced issues")
$issuesDisplay

$(Write-Section "Diff stat")
$statDisplay
"@
}

# ------- Main -------

Resolve-Repo -Root $RepoRoot

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$header = @"
===== Context generated =====

$timestamp

"@

$remotes   = Collect-Remotes
$branchMet = Collect-BranchMeta
$status    = Collect-Status -NoUntracked:$NoUntracked
$wtDiff    = Collect-WorkingTreeDiff

$pr = ""
$baseRef = $Base
$headRef = $Head

if (-not $baseRef) { $baseRef = Pick-Default-Base }
$headRef = Get-Branch -Ref $headRef

if ($baseRef -and $headRef) {
    try {
        $pr = Collect-PRContext -BaseRef $baseRef -HeadRef $headRef
    } catch {
        $pr = "$(Write-Section "PR Comparison")`n(FAILED to compute PR context: $($_.Exception.Message))"
    }
}

$outText = @"
$remotes
$branchMet
$status
$wtDiff
$pr
"@

if ($Append) {
    $header + $outText | Out-File -FilePath $Out -Encoding UTF8 -Append
} else {
    $header + $outText | Out-File -FilePath $Out -Encoding UTF8
}

Write-Host "Wrote context to: $Out"
