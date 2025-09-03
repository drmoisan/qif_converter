# PowerShell
param(
  [string]$Output = "logs/commit_context.txt"
)

$ErrorActionPreference = "Stop"

# Force UTF-8 encoding
if ($PSVersionTable.PSVersion.Major -lt 7) {
    chcp 65001 > $null
}
$enc = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $enc
[Console]::InputEncoding  = $enc
$OutputEncoding           = $enc
$PSDefaultParameterValues['Out-File:Encoding']     = 'utf8'
$PSDefaultParameterValues['Set-Content:Encoding']  = 'utf8'
$PSDefaultParameterValues['Add-Content:Encoding']  = 'utf8'
$PSDefaultParameterValues['Export-Csv:Encoding']   = 'utf8'

function Append-Section {
  param(
    [string]$Title,
    [ScriptBlock]$Cmd,
    [switch]$AllowFail
  )
  Add-Content -Path $Output -Value "`n===== $Title =====`n"
  try {
    if ($Cmd) {
      $result = & $Cmd | Out-String
      Add-Content -Path $Output -Value $result.TrimEnd()
    }
  } catch {
    if ($AllowFail) {
      Add-Content -Path $Output -Value "[n/a]"
    } else {
      throw
    }
  }
}

# Ensure we are inside a Git repo and move to root
git rev-parse --is-inside-work-tree | Out-Null
$root = git rev-parse --show-toplevel
Set-Location $root

# Fresh output
if (Test-Path $Output) { Remove-Item -Force $Output }

Add-Content -Path $Output -Value "Please generate a commit message based on the following content:`n"
Append-Section -Title "Repository remotes" -Cmd { git remote -v }
Append-Section -Title "Current branch" -Cmd { git branch --show-current }
Append-Section -Title "Upstream" -Cmd { git rev-parse --abbrev-ref --symbolic-full-name '@{u}' } -AllowFail
Append-Section -Title "Status (short)" -Cmd { git status -sb }

Append-Section -Title "Staged files (name-status)" -Cmd { git diff --staged --name-status }
Append-Section -Title "Staged diff" -Cmd { git diff --staged }
Append-Section -Title "Unstaged files (name-status)" -Cmd { git diff --name-status }
Append-Section -Title "Unstaged diff" -Cmd { git diff }
Append-Section -Title "Untracked files" -Cmd { git ls-files --others --exclude-standard }

# Summaries
Append-Section -Title "Diff stat (staged + unstaged)" -Cmd { git diff --numstat; git diff --staged --numstat | Sort-Object }
Append-Section -Title "Changed Python files" -Cmd { git diff --name-only HEAD -- '*.py' }

# Baseline context
Append-Section -Title "Last commit (header only)" -Cmd { git show -s --pretty=fuller -1 }

# Placeholder for intent (edit this section in the file if desired)
Add-Content -Path $Output -Value "`n===== Change intent (edit below) =====`n- What/why summary: `n- Breaking changes: `n- Affected modules: `n- Issue/PR refs: `n"

Write-Host "Wrote $Output in $root"