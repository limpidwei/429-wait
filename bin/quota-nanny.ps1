<#
.SYNOPSIS
  quota-nanny: background daemon that waits out an LLM/agent usage limit.

.DESCRIPTION
  Runs a cheap probe command every -IntervalSeconds. While the probe output
  matches the usage-limit pattern (or exits non-zero), it keeps sleeping and
  retrying. As soon as the probe succeeds, it logs SUCCESS and exits.

  No computer use, no extra agent, no token burn beyond one tiny probe per
  interval.

.EXAMPLE
  quota-nanny.ps1 -ProbeCommand "claude -p ping --max-turns 1" -IntervalSeconds 1800
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ProbeCommand,
  [int]$IntervalSeconds = 1800,
  [int]$MaxAttempts = 48,
  [string]$LimitPattern = 'usage limit|hit.*limit|rate.?limit|quota|429|403|overloaded|exceeded',
  [string]$ResumeCommand = '',
  [string]$StateDir = (Join-Path $env:USERPROFILE '.quota-nanny'),
  [string]$Tag = 'default'
)

$ErrorActionPreference = 'Continue'
$null = New-Item -ItemType Directory -Force -Path $StateDir
$logFile  = Join-Path $StateDir "nanny-$Tag.log"
$pidFile  = Join-Path $StateDir "nanny-$Tag.pid"
$okFile   = Join-Path $StateDir "nanny-$Tag.ok"

function Log([string]$msg) {
  $line = "{0} [pid {1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $PID, $msg
  Add-Content -Path $logFile -Value $line -Encoding UTF8
}

# Single-instance guard: if a live nanny for this tag exists, exit.
if (Test-Path $pidFile) {
  $oldPid = [int](Get-Content $pidFile -ErrorAction SilentlyContinue)
  if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
    Log "another nanny already running (pid $oldPid); exiting"
    exit 0
  }
}
Set-Content -Path $pidFile -Value $PID -Encoding ASCII
Remove-Item $okFile -Force -ErrorAction SilentlyContinue

Log "START tag=$Tag interval=${IntervalSeconds}s maxAttempts=$MaxAttempts probe='$ProbeCommand'"

$attempt = 0
try {
  while ($attempt -lt $MaxAttempts) {
    $attempt++
    $out = $null; $code = 0
    try {
      # Run probe through cmd so any CLI string works (claude, hermes, curl, mock, ...)
      $out = & cmd /c "$ProbeCommand 2>&1" | Out-String
      $code = $LASTEXITCODE
    } catch {
      $out = $_.Exception.Message
      $code = 1
    }
    $limited = ($code -ne 0) -or ($out -match $LimitPattern)
    $snippet = (($out -split "`n") | Select-Object -First 2) -join ' | '
    if ($limited) {
      Log "attempt ${attempt}/${MaxAttempts}: STILL LIMITED (exit=$code) :: $snippet"
      Start-Sleep -Seconds $IntervalSeconds
    } else {
      Log "attempt ${attempt}/${MaxAttempts}: RECOVERED (exit=$code) :: $snippet"
      Set-Content -Path $okFile -Value (Get-Date -Format 'o') -Encoding ASCII
      if ($ResumeCommand) {
        Log "quota restored, running resume command: '$ResumeCommand'"
        try {
          $rout = & cmd /c "$ResumeCommand 2>&1" | Out-String
          $rcode = $LASTEXITCODE
          $rsnip = (($rout -split "`n") | Select-Object -First 3) -join ' | '
          Log "resume command exit=$rcode :: $rsnip"
        } catch {
          Log "resume command failed to launch: $($_.Exception.Message)"
        }
      }
      Log "SUCCESS - quota restored, nanny exiting"
      exit 0
    }
  }
  Log "GIVE UP after $MaxAttempts attempts"
  exit 2
} finally {
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
