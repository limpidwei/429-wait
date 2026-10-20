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
Write-Output "installed to $dest"
Write-Output "  quota-nanny.cmd        - daemon (wait out limit, then resume)"
Write-Output "  quota-nanny-watch.cmd  - log watcher (auto-spawn daemon on limit)"
Write-Output "  quota-nanny.sh         - bash version for Linux/macOS/Termux"
