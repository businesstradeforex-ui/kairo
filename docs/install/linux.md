# Installer Kairo sur Linux

```bash
sudo apt update && sudo apt install -y python3 python3-venv git curl
./install.sh --model qwen3:4b
```

Sur une machine avec systemd, le script installe l'unité `kairo.service` (redémarrage automatique, `NoNewPrivileges`). Le serveur écoute seulement sur `127.0.0.1`.

Sans systemd :

```bash
export MEMEDESK_DATA="$HOME/kairo-data"
./.venv/bin/python kairo/run.py all
```

Ollama, s'il est installé, reste sur la machine (le script officiel demande confirmation). Le desk tourne sans lui.

Journal : `journalctl -u kairo -f` ou `~/kairo-data/logs/`.
