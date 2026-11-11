# One-line install for Windows (no Python required):
#   irm https://raw.githubusercontent.com/businesstradeforex-ui/kairo/main/install.ps1 | iex
# Downloads the latest portable zip, extracts it, and starts Kairo.
# Paper trading. Live trading stays off. From-source install: scripts\install-windows.ps1
$ErrorActionPreference = "Stop"
$rel = Invoke-RestMethod -Uri "https://api.github.com/repos/businesstradeforex-ui/kairo/releases/latest" -Headers @{ "User-Agent" = "kairo-install" }
$asset = $rel.assets | Where-Object { $_.name -like "*windows-x64.zip" } | Select-Object -First 1
if (-not $asset) { throw "Aucune archive windows-x64 dans la dernière release." }
$tmp = Join-Path $env:TEMP ("kairo-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp "kairo.zip"
Write-Host "Téléchargement $($asset.browser_download_url)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "out") -Force
$cmd = Get-ChildItem -Path (Join-Path $tmp "out") -Filter "Kairo.cmd" -Recurse | Select-Object -First 1
if (-not $cmd) { throw "Kairo.cmd introuvable dans l'archive." }
$dest = Join-Path $env:LOCALAPPDATA "Programs\Kairo"
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
New-Item -ItemType Directory -Path (Split-Path $dest) -Force | Out-Null
Move-Item $cmd.Directory.FullName $dest
Write-Host "Installé : $dest"
Write-Host "Paper trading. Branchez Ollama (ou LM Studio) puis ouvrez http://127.0.0.1:8787"
Start-Process -FilePath (Join-Path $dest "Kairo.cmd")
Remove-Item -Recurse -Force $tmp
