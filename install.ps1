<#
.SYNOPSIS
  Installs 429-wait globally: copies scripts to ~/.local/bin (already on
  PATH on this machine) with .cmd shims so they run from any shell.
#>
$ErrorActionPreference = 'Stop'
$src  = $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.local\bin'
$null = New-Item -ItemType Directory -Force -Path $dest

foreach ($name in '429-wait.ps1','429-wait-watch.ps1') {
  Copy-Item (Join-Path $src "bin\$name") -Destination $dest -Force
  $cmd = $name -replace '\.ps1$','.cmd'
  Set-Content -Path (Join-Path $dest $cmd) -Encoding ASCII -Value (
    "@echo off`r`npwsh -NoProfile -ExecutionPolicy Bypass -File `"%USERPROFILE%\.local\bin\$name`" %*"
  )
}
Copy-Item (Join-Path $src 'bin\429-wait.sh') -Destination $dest -Force

# v2: Python daemon. The .cmd shim keeps the same name minus the extension.
Copy-Item (Join-Path $src 'bin\429-wait.py') -Destination $dest -Force
Set-Content -Path (Join-Path $dest '429-wait-py.cmd') -Encoding ASCII -Value (
  "@echo off`r`npython `"%USERPROFILE%\.local\bin\429-wait.py`" %*"
)

Write-Output "installed to $dest"
Write-Output "  429-wait-py.cmd     - v2 daemon, Python, probes the API directly (recommended)"
Write-Output "  429-wait.cmd        - v1 daemon (probe command based)"
Write-Output "  429-wait-watch.cmd  - log watcher (auto-spawn v1 daemon on limit)"
Write-Output "  429-wait.sh         - bash version for Linux/macOS/Termux"
Write-Output "  429-wait.py         - v2 script itself (python 429-wait.py --help)"
