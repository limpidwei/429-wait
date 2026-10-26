<#
.SYNOPSIS
  Uninstalls 429-wait: removes shims, scripts, and adapters using the manifest.
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

# remove shims
foreach ($cmd in $m.shims) {
    $p = Join-Path $dest "$cmd.cmd"
    if (Test-Path $p) {
        Remove-Item $p -Force
        Write-Output "  removed shim: $p"
    }
}

# remove core files
foreach ($f in $m.files) {
    $p = Join-Path $dest $f
    if (Test-Path $p) {
        Remove-Item $p -Force
        Write-Output "  removed: $p"
    }
}

# remove legacy files
foreach ($f in '429-wait.cmd','429-wait-watch.cmd','429-wait.ps1','429-wait-watch.ps1','429-wait.sh') {
    $p = Join-Path $dest $f
    if (Test-Path $p) {
        Remove-Item $p -Force
        Write-Output "  removed legacy: $p"
    }
}

# remove adapters
if (Test-Path $adapterDest) {
    Remove-Item $adapterDest -Recurse -Force
    Write-Output "  removed adapters: $adapterDest"
}

# remove manifest
Remove-Item $manifest -Force
Write-Output "  removed manifest"

Write-Output ''
Write-Output 'Done. 429-wait has been uninstalled.'
Write-Output "Note: state/logs in $stateDir were preserved. Delete manually if not needed."
