<#
.SYNOPSIS
  Uninstalls 429-wait hooks, shims, scripts, and adapters using the manifest.
#>
$ErrorActionPreference = 'Stop'
$stateDir = Join-Path $env:USERPROFILE '.429-wait'
$manifest = Join-Path $stateDir 'manifest.json'

if (-not (Test-Path $manifest)) {
    Write-Output '429-wait: manifest not found. Nothing to uninstall.'
    Write-Output "  (expected at $manifest)"
    exit 0
}

$m = Get-Content $manifest -Raw | ConvertFrom-Json
$dest = $m.dest
$adapterDest = $m.adapter_dest

Write-Output 'Uninstalling 429-wait ...'

$settingsHelper = Join-Path $dest '429-wait-settings.py'
if (Test-Path $settingsHelper) {
    & python -I $settingsHelper uninstall --hook-script (Join-Path $dest '429-wait-hook.py')
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to remove the Claude Code StopFailure hook'
    }
}

# Remove only shims that still contain our wrapper marker.
foreach ($cmd in $m.shims) {
    foreach ($extension in '.cmd', '.ps1') {
        $p = Join-Path $dest "$cmd$extension"
        if ((Test-Path $p) -and ((Get-Content $p -Raw) -match '429-wait-(shim|terminal)\.py')) {
            Remove-Item $p -Force
            Write-Output "  removed shim: $p"
        }
    }
}

foreach ($f in $m.files) {
    $p = Join-Path $dest $f
    if (Test-Path $p) {
        Remove-Item $p -Force
        Write-Output "  removed: $p"
    }
}

foreach ($f in '429-wait.cmd', '429-wait-watch.cmd', '429-wait-py.cmd', '429-wait.ps1', '429-wait-watch.ps1', '429-wait.sh') {
    $p = Join-Path $dest $f
    if (Test-Path $p) {
        Remove-Item $p -Force
        Write-Output "  removed legacy: $p"
    }
}

if (Test-Path $adapterDest) {
    Remove-Item $adapterDest -Recurse -Force
    Write-Output "  removed adapters: $adapterDest"
}

Remove-Item $manifest -Force
Write-Output '  removed manifest'

Write-Output ''
Write-Output 'Done. 429-wait has been uninstalled.'
Write-Output "Note: state/logs in $stateDir were preserved. Delete manually if not needed."
