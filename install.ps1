<#
.SYNOPSIS
  Installs quota-nanny globally: copies scripts to ~/.local/bin (already on
  PATH on this machine) with .cmd shims so they run from any shell.
#>
$ErrorActionPreference = 'Stop'
$src  = $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.local\bin'
$null = New-Item -ItemType Directory -Force -Path $dest

foreach ($name in 'quota-nanny.ps1','quota-nanny-watch.ps1') {
  Copy-Item (Join-Path $src "bin\$name") -Destination $dest -Force
  $cmd = $name -replace '\.ps1$','.cmd'
  Set-Content -Path (Join-Path $dest $cmd) -Encoding ASCII -Value (
    "@echo off`r`npwsh -NoProfile -ExecutionPolicy Bypass -File `"%USERPROFILE%\.local\bin\$name`" %*"
  )
}
Copy-Item (Join-Path $src 'bin\quota-nanny.sh') -Destination $dest -Force

# v2: Python daemon. The .cmd shim keeps the same name minus the extension.
Copy-Item (Join-Path $src 'bin\quota-nanny.py') -Destination $dest -Force
Set-Content -Path (Join-Path $dest 'quota-nanny-py.cmd') -Encoding ASCII -Value (
  "@echo off`r`npython `"%USERPROFILE%\.local\bin\quota-nanny.py`" %*"
)

Write-Output "installed to $dest"
Write-Output "  quota-nanny-py.cmd     - v2 daemon, Python, probes the API directly (recommended)"
Write-Output "  quota-nanny.cmd        - v1 daemon (probe command based)"
Write-Output "  quota-nanny-watch.cmd  - log watcher (auto-spawn v1 daemon on limit)"
Write-Output "  quota-nanny.sh         - bash version for Linux/macOS/Termux"
Write-Output "  quota-nanny.py         - v2 script itself (python quota-nanny.py --help)"
