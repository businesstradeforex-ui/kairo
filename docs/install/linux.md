# Installer Kairo sur Linux

## Paquet (recommandé)

x64 et arm64 : `.tar.gz`, `.deb` et AppImage, dans la [dernière release](https://github.com/businesstradeforex-ui/kairo/releases/latest).

```bash
curl -fsSL https://raw.githubusercontent.com/businesstradeforex-ui/kairo/main/install.sh | bash
```

Le script pose le programme dans `~/.local/opt/kairo` et un lien `~/.local/bin/kairo`. Les données vont dans `~/.local/share/kairo`.

Ou, avec le deb : `sudo apt install ./Kairo-<version>-linux-x64.deb` puis `kairo`.

## Depuis les sources

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
