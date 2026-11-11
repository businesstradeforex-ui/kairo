# Native Windows install (PowerShell). For WSL or Docker, see docs/install/windows.md.
# Run from the repository root:  powershell -ExecutionPolicy Bypass -File scripts/install-windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Data = Join-Path $env:USERPROFILE "kairo-data"
$Py = Get-Command py -ErrorAction SilentlyContinue
if (-not $Py) { $Py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $Py) { throw "Installez Python 3.10+ depuis https://www.python.org/downloads/ (cochez Add to PATH)." }
Push-Location $Root
& $Py.Source -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
New-Item -ItemType Directory -Force -Path $Data, (Join-Path $Data "logs") | Out-Null
$env:MEMEDESK_DATA = $Data
Set-Location (Join-Path $Root "kairo")
Write-Host "Créez le compte propriétaire (10 caractères minimum)."
& "$Root\.venv\Scripts\python.exe" manage.py create-user --role owner
Write-Host "Démarrez avec :  `$env:MEMEDESK_DATA='$Data'; & '$Root\.venv\Scripts\python.exe' '$Root\kairo\run.py' all"
Write-Host "Puis ouvrez http://127.0.0.1:8787"
Pop-Location
