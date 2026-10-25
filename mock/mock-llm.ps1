<#
.SYNOPSIS
  Mock LLM CLI for 429-wait tests. Simulates "usage limit" for the first N
  invocations (tracked in a state file), then starts succeeding.

.USAGE
  mock-llm.ps1 -StateFile <path>           # one probe call
  mock-llm.ps1 -StateFile <path> -Reset 3  # reset: next 3 calls fail
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$StateFile,
  [int]$Reset = -1
)

if ($Reset -ge 0) {
  @{ fail_remaining = $Reset; calls = 0 } | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
  Write-Output "mock reset: fail_remaining=$Reset"
  exit 0
}

$state = Get-Content $StateFile -Raw | ConvertFrom-Json
$state.calls = [int]$state.calls + 1

if ([int]$state.fail_remaining -gt 0) {
  $state.fail_remaining = [int]$state.fail_remaining - 1
  $state | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
  [Console]::Error.WriteLine("Error 403: hit usage limit. Your quota resets at " + (Get-Date).AddHours(5).ToString('HH:mm'))
  exit 1
} else {
  $state | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
  Write-Output "OK: LLM response (call #$($state.calls))"
  exit 0
}
