# Installer Kairo sur Windows

Deux chemins : Python natif, ou WSL / Docker. Le paper trading est le même.

## Natif

1. Installez Python 3.10+ depuis python.org et cochez **Add python.exe to PATH**.
2. Dans PowerShell, à la racine du dépôt :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
$env:MEMEDESK_DATA = "$env:USERPROFILE\kairo-data"
.\.venv\Scripts\python.exe kairo\run.py all
```

3. Ouvrez http://127.0.0.1:8787

Ollama pour Windows : https://ollama.com/download puis `ollama pull qwen3:4b`.

Le script natif ne crée pas de service Windows. Pour le laisser tourner, utilisez le Planificateur de tâches sur `run.py all`, ou passez par Docker.

## WSL (Ubuntu)

Dans Ubuntu sous WSL :

```bash
sudo apt update && sudo apt install -y python3 python3-venv git curl
cd /mnt/c/Users/vous/src/kairo   # ou un clone dans le système de fichiers Linux, plus rapide
./install.sh
```

Préférez un clone dans `~/kairo` (ext4) plutôt que `/mnt/c`, les bases SQLite y sont plus fiables.

## Docker Desktop

```powershell
docker compose up -d --build
docker compose run --rm kairo python manage.py create-user you --role owner
docker compose exec ollama ollama pull qwen3:4b
```

Le port publié est `127.0.0.1:8787` seulement. Docker Desktop n'a pas le GPU comme une install native : Ollama y est plus lent.
