<#
make_chatgpt_bundle.ps1
Creates:
  - CHATGPT_BRIEF.md    : small, skimmable overview for ChatGPT
  - chatgpt_bundle.zip  : zip of tracked files at HEAD (no venv/.idea/__pycache__/etc.)

Usage:
  .\make_chatgpt_bundle.ps1 [-OutZip chatgpt_bundle.zip] [-OutBrief CHATGPT_BRIEF.md] [-MaxDepth 2]
Notes:
  - Uses `git archive` -> only files tracked at HEAD are included.
  - ASCII-only; works on Windows PowerShell 5.1+.
#>

param(
  [string]$OutZip   = "logs\chatgpt_bundle.zip",
  [string]$OutBrief = "logs\CHATGPT_BRIEF.md",
  [int]   $MaxDepth = 6
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Err ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

# names to suppress in the brief's layout
$Global:ExcludeNames = @(
  ".git", ".idea", "__pycache__", ".mypy_cache", ".pytest_cache",
  "venv", ".venv", "dist", "build"
)

function Should-Exclude([string]$name) {
  if ($Global:ExcludeNames -contains $name) { return $true }
  if ($name -like "*.egg-info") { return $true }
  return $false
}

function Get-Children($Path) {
  $items = Get-ChildItem -LiteralPath $Path -Force |
           Where-Object { -not (Should-Exclude $_.Name) }

  # Force arrays even when there’s only one or zero items
  $dirs  = @($items | Where-Object { $_.PSIsContainer } | Sort-Object Name)
  $files = @($items | Where-Object { -not $_.PSIsContainer } | Sort-Object Name)

  return @($dirs + $files)  # concatenation of two arrays
}

function Build-Tree([string]$Root, [int]$MaxDepth) {
  # ASCII tree, depth-limited. Uses "+-- " and "|   " / "    " as guides.
  $lines = New-Object System.Collections.Generic.List[string]

  function Recurse([string]$Path, [string]$Prefix, [int]$Depth) {
    $children = Get-Children -Path $Path
    for ($i = 0; $i -lt $children.Count; $i++) {
      $child   = $children[$i]
      $isLast  = ($i -eq $children.Count - 1)
      $connector = '+-- '
      $name = $child.Name + ($(if ($child.PSIsContainer) { '/' } else { '' }))
      $lines.Add("$Prefix$connector$name")
      if ($child.PSIsContainer -and $Depth -gt 1) {
        $nextPrefix = [string]$Prefix + ($(if ($isLast) { '    ' } else { '|   ' }))
        Recurse -Path $child.FullName -Prefix $nextPrefix -Depth ($Depth - 1)
      }
    }
  }

  $rootName = Split-Path -Leaf $Root
  if ([string]::IsNullOrWhiteSpace($rootName)) { $rootName = '.' }
  $lines.Add("$rootName/")
  Recurse -Path $Root -Prefix '' -Depth $MaxDepth
  return ($lines -join [Environment]::NewLine)
}

function Run-Git {
  param(
    [Parameter(Mandatory=$true)]
    [string[]]$GitArgs
  )
  if (-not $GitArgs -or $GitArgs.Count -eq 0) {
    throw "internal: Run-Git invoked with no arguments"
  }
  $out = & git @GitArgs 2>&1
  $code = $LASTEXITCODE
  if ($code -ne 0) {
    $joined = ($GitArgs -join ' ')
    throw "git $joined failed (exit $code): $out"
  }
  return ($out | Out-String).Trim()
}

try {
  # verify git + repo
  Run-Git @('--version') | Out-Null
  $inside = Run-Git @('rev-parse','--is-inside-work-tree')
  if ($inside -ne 'true') { throw 'Not inside a git working tree.' }

  $repoRoot = Run-Git @('rev-parse','--show-toplevel')
  $branch   = Run-Git @('rev-parse','--abbrev-ref','HEAD')
  $commit   = Run-Git @('rev-parse','--short=12','HEAD')
  $remote   = ''
  try { $remote = Run-Git @('remote','get-url','--push','origin') } catch { $remote = '(no origin)' }

  $cwd = Get-Location
  if ($cwd.Path -ne $repoRoot) {
    Write-Info "Switching to repo root: $repoRoot"
    Push-Location $repoRoot
  }

  # ----- brief -----
  Write-Info "Generating $OutBrief"

  $repoName = Split-Path -Leaf $repoRoot

  $keyFiles = @()
  $candidates = @(
    'README.md','README.rst','README.txt',
    'pyproject.toml','requirements.txt','requirements-dev.txt',
    'setup.cfg','setup.py'
  )
  foreach ($n in $candidates) {
    if (Test-Path -LiteralPath (Join-Path $repoRoot $n)) { $keyFiles += $n }
  }
  if (Test-Path -LiteralPath (Join-Path $repoRoot 'tests')) { $keyFiles += 'tests/' }

  $layout = Build-Tree -Root $repoRoot -MaxDepth $MaxDepth

  $brief = @()
  $brief += '# Project brief'
  $brief += ''
  $brief += "**Repository:** $repoName"
  $brief += "**Branch:** $branch"
  $brief += "**Commit:** $commit"
  $brief += "**Remote:** $remote"
  $brief += ''
  $brief += '## Key files'
  if ($keyFiles.Count -gt 0) {
    foreach ($k in ($keyFiles | Sort-Object -Unique)) { $brief += "- $k" }
  } else {
    $brief += '_(No standard key files detected)_'
  }
  $brief += ''
  $brief += "## Layout (depth $MaxDepth)"
  $brief += ''
  $brief += '```'
  $brief += $layout
  $brief += '```'
  $brief += ''
  $brief += 'Tip: when you upload the zip, also tell ChatGPT which files/dirs to focus on.'

  $brief | Set-Content -Encoding UTF8 $OutBrief

  # ----- zip via git archive -----
  Write-Info "Creating $OutZip from tracked files at HEAD..."
  Run-Git @('archive','--format=zip','-o', $OutZip, 'HEAD') | Out-Null

  Write-Info 'Done.'
  Write-Host ''
  Write-Host 'Created:' -ForegroundColor Green
  Write-Host ("  - {0}`t({1})" -f $OutBrief, (Get-Item $OutBrief).FullName)
  Write-Host ("  - {0}`t({1})" -f $OutZip,   (Get-Item $OutZip).FullName)
  Write-Host ''
  Write-Warn 'ZIP contains files as of HEAD. Commit/stage changes if you want them included.'

} catch {
  Write-Err $_.Exception.Message
  exit 1
} finally {
  if ($cwd -and (Get-Location).Path -ne $cwd.Path) {
    Pop-Location | Out-Null
  }
}
