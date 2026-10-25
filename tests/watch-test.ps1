<#
.SYNOPSIS
  Watcher e2e test: a usage-limit line appearing in a watched agent log must
  cause 429-wait-watch to spawn the daemon, which polls until recovery,
  then exits by itself.
#>
[CmdletBinding()]
param(
  [int]$IntervalSeconds = 3,
  [int]$TimeoutSeconds = 45,
  [string]$RunId = ('w' + (Get-Date -Format 'HHmmss'))
)

$ErrorActionPreference = 'Stop'
$root      = Split-Path $PSScriptRoot -Parent
$watcher   = Join-Path $root 'bin\429-wait-watch.ps1'
$mock      = Join-Path $root 'mock\mock-llm.ps1'
$stateDir  = Join-Path $root "tests\state\$RunId"
$null = New-Item -ItemType Directory -Force -Path $stateDir

$agentLog  = Join-Path $stateDir 'agent.log'
$mockState = Join-Path $stateDir 'mock-state.json'
Set-Content $agentLog -Value "agent session log start" -Encoding UTF8
& pwsh -NoProfile -File $mock -StateFile $mockState -Reset 2 | Out-Null

$probeCmd = "pwsh -NoProfile -File $mock -StateFile $mockState"
$argLine  = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -LogFile "{1}" -ProbeCommand "{2}" -IntervalSeconds {3} -MaxAttempts 10 -StateDir "{4}" -Tag "test-{5}"' -f $watcher, $agentLog, $probeCmd, $IntervalSeconds, $stateDir, $RunId
$wproc = Start-Process -PassThru -WindowStyle Hidden -FilePath 'pwsh' -ArgumentList $argLine
Start-Sleep -Seconds 2

# simulate the agent hitting the wall mid-session
Add-Content $agentLog -Value "Error: 403 hit usage limit. Your quota resets at 04:00" -Encoding UTF8

$nannyLog = Join-Path $stateDir "nanny-test-$RunId.log"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ok = $false
while ((Get-Date) -lt $deadline) {
  if ((Test-Path (Join-Path $stateDir "nanny-test-$RunId.ok"))) { $ok = $true; break }
  Start-Sleep -Milliseconds 500
}

$results = [ordered]@{}
$results['1_watcher_auto_spawned_nanny'] = Test-Path $nannyLog
$log = if (Test-Path $nannyLog) { Get-Content $nannyLog -Raw } else { '' }
$results['2_retried_until_recovery'] = ([regex]::Matches($log, 'STILL LIMITED')).Count -ge 2
$results['3_nanny_exited_on_success'] = $ok -and ($log -match 'SUCCESS')

# cleanup: stop watcher
try { Stop-Process -Id $wproc.Id -Force -ErrorAction Stop } catch {}

$pass = ($results.Values | Where-Object { -not $_ }).Count -eq 0
Write-Output "== watcher run $RunId =="
$results.GetEnumerator() | ForEach-Object { Write-Output ("  [{0}] {1}" -f ($(if ($_.Value) {'PASS'} else {'FAIL'}), $_.Key)) }
Write-Output ("  RESULT: {0}" -f $(if ($pass) {'PASS'} else {'FAIL'}))
if (-not $pass) { Write-Output "---- nanny log ----`n$log" }
exit $(if ($pass) {0} else {1})
