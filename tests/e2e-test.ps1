<#
.SYNOPSIS
  End-to-end test for quota-nanny against the mock LLM.
  Verifies the three acceptance criteria:
    1. daemon spawns in background and stays resident
    2. it retries every interval while the probe reports a usage limit
    3. on recovery it runs the resume command and exits by itself
#>
[CmdletBinding()]
param(
  [int]$FailCount = 3,
  [int]$IntervalSeconds = 3,
  [int]$TimeoutSeconds = 60,
  [string]$RunId = ('r' + (Get-Date -Format 'HHmmss'))
)

$ErrorActionPreference = 'Stop'
$root      = Split-Path $PSScriptRoot -Parent
$nanny     = Join-Path $root 'bin\quota-nanny.ps1'
$mock      = Join-Path $root 'mock\mock-llm.ps1'
$stateDir  = Join-Path $root "tests\state\$RunId"
$null = New-Item -ItemType Directory -Force -Path $stateDir

$mockState   = Join-Path $stateDir 'mock-state.json'
$resumeMark  = Join-Path $stateDir 'resume-fired.txt'
$resumeScr   = Join-Path $root 'mock\resume-mark.ps1'
# paths under D:\quota-nanny contain no spaces -> no nested quoting needed
$probeCmd  = "pwsh -NoProfile -File $mock -StateFile $mockState"
$resumeCmd = "pwsh -NoProfile -File $resumeScr -MarkFile $resumeMark"

& pwsh -NoProfile -File $mock -StateFile $mockState -Reset $FailCount | Out-Null

$argLine = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -ProbeCommand "{1}" -IntervalSeconds {2} -MaxAttempts 10 -ResumeCommand "{3}" -StateDir "{4}" -Tag "test-{5}"' -f $nanny, $probeCmd, $IntervalSeconds, $resumeCmd, $stateDir, $RunId
$proc = Start-Process -PassThru -WindowStyle Hidden -FilePath 'pwsh' -ArgumentList $argLine

$results = [ordered]@{}

# --- criterion 1: spawned and resident -------------------------------------
Start-Sleep -Seconds 2
$pidFile = Join-Path $stateDir "nanny-test-$RunId.pid"
$results['1_spawned_and_resident'] = (-not $proc.HasExited) -and (Test-Path $pidFile)

# --- wait for exit ----------------------------------------------------------
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while (-not $proc.HasExited -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
$proc.Refresh()

$logFile = Join-Path $stateDir "nanny-test-$RunId.log"
$log = if (Test-Path $logFile) { Get-Content $logFile -Raw } else { '' }
$mockCalls = ((Get-Content $mockState -Raw | ConvertFrom-Json).calls)

# --- criterion 2: retried every interval while limited ----------------------
$limitedHits = ([regex]::Matches($log, 'STILL LIMITED')).Count
$results['2_retried_while_limited'] = ($limitedHits -ge $FailCount) -and ($mockCalls -ge $FailCount + 1)

# --- criterion 3: auto-exit on recovery + resume command fired ---------------
$results['3_auto_exit_on_recovery'] = $proc.HasExited -and
  (Test-Path (Join-Path $stateDir "nanny-test-$RunId.ok")) -and
  ($log -match 'SUCCESS') -and (Test-Path $resumeMark)

$pass = ($results.Values | Where-Object { -not $_ }).Count -eq 0
Write-Output "== run $RunId =="
$results.GetEnumerator() | ForEach-Object { Write-Output ("  [{0}] {1}" -f ($(if ($_.Value) {'PASS'} else {'FAIL'}), $_.Key)) }
Write-Output ("  mock probe calls: {0} (expected {1})" -f $mockCalls, ($FailCount + 1))
Write-Output ("  RESULT: {0}" -f $(if ($pass) {'PASS'} else {'FAIL'}))
if (-not $pass) { Write-Output "---- nanny log ----`n$log" }
exit $(if ($pass) {0} else {1})
