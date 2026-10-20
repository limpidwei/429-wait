<#
.SYNOPSIS
  quota-nanny-watch: tails a log file; when a usage-limit error appears,
  spawns a background quota-nanny daemon (once) to poll until recovery.

.EXAMPLE
  quota-nanny-watch.ps1 -LogFile C:\path\to\agent.log -ProbeCommand "claude -p ping --max-turns 1"
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$LogFile,
  [Parameter(Mandatory=$true)][string]$ProbeCommand,
  [string]$LimitPattern = 'usage limit|hit.*limit|rate.?limit|quota|429|403|overloaded|exceeded',
  [int]$IntervalSeconds = 1800,
  [int]$MaxAttempts = 48,
  [string]$ResumeCommand = '',
  [string]$StateDir = (Join-Path $env:USERPROFILE '.quota-nanny'),
  [string]$Tag = 'default'
)

$null = New-Item -ItemType Directory -Force -Path $StateDir
$watchLog = Join-Path $StateDir "watch-$Tag.log"
$nanny    = Join-Path $PSScriptRoot 'quota-nanny.ps1'

function WLog([string]$msg) {
  Add-Content -Path $watchLog -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding UTF8
}

WLog "watching $LogFile for /$LimitPattern/"
Get-Content -Path $LogFile -Wait -Tail 0 | ForEach-Object {
  if ($_ -match $LimitPattern) {
    $pidFile = Join-Path $StateDir "nanny-$Tag.pid"
    $alive = $false
    if (Test-Path $pidFile) {
      $p = [int](Get-Content $pidFile -ErrorAction SilentlyContinue)
      if ($p -and (Get-Process -Id $p -ErrorAction SilentlyContinue)) { $alive = $true }
    }
    if (-not $alive) {
      WLog "limit detected, spawning nanny: $_"
      # Start-Process joins an ArgumentList array with spaces and no quoting,
      # so build one argument string and quote each value ourselves.
      $argLine = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -ProbeCommand "{1}" -IntervalSeconds {2} -MaxAttempts {3} -ResumeCommand "{4}" -LimitPattern "{5}" -StateDir "{6}" -Tag "{7}"' -f $nanny, $ProbeCommand, $IntervalSeconds, $MaxAttempts, $ResumeCommand, $LimitPattern, $StateDir, $Tag
      Start-Process -WindowStyle Hidden -FilePath 'pwsh' -ArgumentList $argLine
    }
  }
}
