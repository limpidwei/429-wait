# Isolated installer upgrade/uninstall test; never touches the real profile.
$ErrorActionPreference = 'Stop'
$root = Join-Path $PSScriptRoot '..'
$temp = Join-Path $env:TEMP ("429-install-test-" + [guid]::NewGuid().ToString('N'))
$oldProfile = $env:USERPROFILE
$oldConfig = $env:CLAUDE_CONFIG_DIR
try {
    $env:USERPROFILE = $temp
    $env:CLAUDE_CONFIG_DIR = Join-Path $temp 'claude-config'
    $bin = Join-Path $temp '.local\bin'
    $null = New-Item -ItemType Directory -Force -Path $bin, $env:CLAUDE_CONFIG_DIR

    $settings = Join-Path $env:CLAUDE_CONFIG_DIR 'settings.json'
    @'
{"env":{"KEEP_ME":"yes"},"hooks":{"StopFailure":[{"hooks":[{"type":"command","command":"other-command"}]}]}}
'@ | Set-Content -Path $settings -Encoding UTF8
    Set-Content -Path (Join-Path $bin 'claude.cmd') -Encoding ASCII -Value '@echo 429-wait-shim.py'
    Set-Content -Path (Join-Path $bin 'claude.ps1') -Encoding UTF8 -Value '# 429-wait-shim.py'

    & (Join-Path $root 'install.ps1') -Agents claude | Out-Null
    if (-not (Test-Path (Join-Path $bin 'claude.cmd'))) { throw 'supervisor cmd wrapper missing' }
    if (-not (Test-Path (Join-Path $bin 'claude.ps1'))) { throw 'supervisor ps1 wrapper missing' }
    if ((Get-Content (Join-Path $bin 'claude.cmd') -Raw) -notmatch '429-wait-terminal.py') { throw 'cmd wrapper is not the supervisor' }
    if ((Get-Content (Join-Path $bin 'claude.ps1') -Raw) -notmatch '429-wait-terminal.py') { throw 'ps1 wrapper is not the supervisor' }
    & (Join-Path $root 'install.ps1') -Agents claude | Out-Null
    $manifest = Get-Content (Join-Path $temp '.429-wait\manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.files -notcontains '429-wait-terminal.py') { throw 'supervisor missing from manifest' }

    $data = Get-Content $settings -Raw | ConvertFrom-Json
    $owned = @($data.hooks.StopFailure | Where-Object { ($_ | ConvertTo-Json -Depth 10) -match '429-wait-hook.py' })
    $other = @($data.hooks.StopFailure | Where-Object { ($_ | ConvertTo-Json -Depth 10) -match 'other-command' })
    if ($owned.Count -ne 1) { throw "expected one owned hook, got $($owned.Count)" }
    if ($other.Count -ne 1) { throw 'existing hook was not preserved' }
    if ($data.env.KEEP_ME -ne 'yes') { throw 'existing settings were not preserved' }

    & (Join-Path $root 'uninstall.ps1') | Out-Null
    $data = Get-Content $settings -Raw | ConvertFrom-Json
    $owned = @($data.hooks.StopFailure | Where-Object { ($_ | ConvertTo-Json -Depth 10) -match '429-wait-hook.py' })
    $other = @($data.hooks.StopFailure | Where-Object { ($_ | ConvertTo-Json -Depth 10) -match 'other-command' })
    if ($owned.Count -ne 0) { throw 'owned hook survived uninstall' }
    if ($other.Count -ne 1) { throw 'other hook was removed during uninstall' }
    if ($data.env.KEEP_ME -ne 'yes') { throw 'settings changed during uninstall' }
    if (Test-Path (Join-Path $bin 'claude.cmd')) { throw 'cmd wrapper survived uninstall' }
    if (Test-Path (Join-Path $bin 'claude.ps1')) { throw 'ps1 wrapper survived uninstall' }
    if (Test-Path (Join-Path $bin '429-wait-terminal.py')) { throw 'supervisor file survived uninstall' }
    Write-Output 'PASS  isolated install, upgrade, idempotence, and uninstall'
}
finally {
    $env:USERPROFILE = $oldProfile
    $env:CLAUDE_CONFIG_DIR = $oldConfig
    if (Test-Path $temp) { Remove-Item $temp -Recurse -Force }
}
