param([Parameter(Mandatory=$true)][string]$MarkFile)
Set-Content -Path $MarkFile -Value (Get-Date -Format 'o') -Encoding ASCII
