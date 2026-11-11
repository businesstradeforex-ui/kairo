#!/usr/bin/env bash
# Install Kairo.
#
# One line (downloads the latest packaged build, no Python required):
#   curl -fsSL https://raw.githubusercontent.com/businesstradeforex-ui/kairo/main/install.sh | bash
#
# From a git checkout, ./install.sh installs from source (venv + service).
#   ./install.sh --release     packaged build even inside the checkout
#   ./install.sh --model qwen3:4b --no-ollama --no-service --tunnel
#
# Paper trading. Live trading stays off. No default password.
set -euo pipefail

release_install() {
  command -v curl >/dev/null || { echo "curl est requis"; exit 1; }
  local os arch suffix url tmp dest inner
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os-$arch" in
    Darwin-arm64) suffix="macos-arm64.zip" ;;
    Darwin-x86_64) suffix="macos-intel.zip" ;;
    Linux-x86_64|Linux-amd64) suffix="linux-x64.tar.gz" ;;
    Linux-aarch64|Linux-arm64) suffix="linux-arm64.tar.gz" ;;
    *) echo "Plateforme non prise en charge : $os $arch"; exit 1 ;;
  esac
  echo "Recherche de la dernière release ($suffix)…"
  url="$(curl -fsSL "https://api.github.com/repos/businesstradeforex-ui/kairo/releases/latest" \
    | python3 -c 'import json,sys; suf=sys.argv[1]; d=json.load(sys.stdin); print(next(a["browser_download_url"] for a in d.get("assets",[]) if a["name"].endswith(suf)))' "$suffix")"
  tmp="$(mktemp -d)"
  echo "Téléchargement de $url"
  curl -fL "$url" -o "$tmp/pkg"
  if [ "$os" = Darwin ]; then
    mkdir -p "$tmp/out"
    unzip -q "$tmp/pkg" -d "$tmp/out"
    inner="$(find "$tmp/out" -name 'Kairo.app' -type d | head -1)"
    [ -n "$inner" ] || { echo "Kairo.app introuvable dans l'archive"; exit 1; }
    mkdir -p "$HOME/Applications"
    rm -rf "$HOME/Applications/Kairo.app"
    mv "$inner" "$HOME/Applications/Kairo.app"
    echo "Installé : $HOME/Applications/Kairo.app"
    echo "Première ouverture : clic droit > Ouvrir (app non signée, Gatekeeper)."
    open "$HOME/Applications/Kairo.app" || true
  else
    mkdir -p "$tmp/out"
    tar -xzf "$tmp/pkg" -C "$tmp/out"
    inner="$(find "$tmp/out" -type f -path '*/bin/kairo' | head -1)"
    [ -n "$inner" ] || { echo "bin/kairo introuvable"; exit 1; }
    dest="${KAIRO_INSTALL_DIR:-$HOME/.local/opt/kairo}"
    rm -rf "$dest"
    mkdir -p "$(dirname "$dest")"
    mv "$(dirname "$(dirname "$inner")")" "$dest"
    mkdir -p "$HOME/.local/bin"
    ln -sfn "$dest/bin/kairo" "$HOME/.local/bin/kairo"
    echo "Installé : $dest"
    echo "Lancez : $HOME/.local/bin/kairo   (ajoutez ~/.local/bin au PATH si besoin)"
    "$dest/bin/kairo" || true
  fi
  rm -rf "$tmp"
}

IN_REPO=0
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [ -f "$ROOT/kairo/server.py" ] && IN_REPO=1
fi
FORCE_RELEASE=0
for _a in "$@"; do [ "$_a" = "--release" ] && FORCE_RELEASE=1; done
if [ "$IN_REPO" = 0 ] || [ "$FORCE_RELEASE" = 1 ]; then
  release_install
  exit 0
fi
# Drop --release so the source installer does not treat it as unknown.
args=()
for _a in "$@"; do [ "$_a" = "--release" ] || args+=("$_a"); done
set -- "${args[@]}"
APP="$ROOT/kairo"
DATA="${DATA_DIR:-$HOME/kairo-data}"
PORT="${DESK_PORT:-8787}"
UI="${MEMEDESK_UI_DIR:-$HOME/kairo-ui}"
MODEL="qwen3:4b"
WANT_OLLAMA=1
WANT_SERVICE=1
WANT_CAFF=1
ONLY_TUNNEL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift ;;
    --no-ollama) WANT_OLLAMA=0 ;;
    --no-service) WANT_SERVICE=0 ;;
    --no-caffeinate) WANT_CAFF=0 ;;
    --tunnel) ONLY_TUNNEL=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Option inconnue : $1"; exit 1 ;;
  esac
  shift
done

OS="$(uname -s)"
say() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
ask() { local r; read -r -p "$1 [o/N] " r; [[ "$r" =~ ^[oOyY] ]]; }
LA="$HOME/Library/LaunchAgents"
UID_N="$(id -u)"

plist() {
  local label="$1" ka="$2"; shift 2
  local f="$LA/$label.plist" args="" a
  for a in "$@"; do args="$args<string>$a</string>"; done
  mkdir -p "$LA" "$DATA/logs"
  cat > "$f" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>$args</array>
  <key>WorkingDirectory</key><string>$APP</string>
  <key>EnvironmentVariables</key><dict>
    <key>MEMEDESK_DATA</key><string>$DATA</string>
    <key>DESK_PORT</key><string>$PORT</string>
    <key>DESK_HOST</key><string>127.0.0.1</string>
    <key>TRUST_PROXY</key><string>1</string>
    <key>KAIRO_ENV</key><string>production</string>
    <key>KAIRO_LLM_MODEL</key><string>$MODEL</string>
    <key>OLLAMA_MODEL</key><string>$MODEL</string>
    <key>OLLAMA_URL</key><string>http://127.0.0.1:11434</string>
    <key>MEMEDESK_UI_DIR</key><string>$UI</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><$ka/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$DATA/logs/launchd-${label##*.}.log</string>
  <key>StandardErrorPath</key><string>$DATA/logs/launchd-${label##*.}.log</string>
</dict></plist>
PL
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$f"
  echo "  service $label"
}

tunnel_service() {
  command -v cloudflared >/dev/null || { warn "cloudflared absent. Voir docs/exposition.md"; return; }
  [ -f "$HOME/.cloudflared/config.yml" ] || { warn "~/.cloudflared/config.yml absent"; return; }
  local CF; CF="$(command -v cloudflared)"
  if [ "$OS" = Darwin ]; then plist com.kairo.cloudflared true "$CF" tunnel --no-autoupdate run
  else sudo "$CF" --config "$HOME/.cloudflared/config.yml" service install || warn "cloudflared service install a échoué"; fi
}

if [ "$ONLY_TUNNEL" = 1 ]; then tunnel_service; exit 0; fi

say "1/5 Python"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  if [ "$OS" = Darwin ]; then
    command -v brew >/dev/null || { echo "Installez Homebrew : https://brew.sh puis relancez."; exit 1; }
    brew install python@3.12
    PY="$(brew --prefix)/bin/python3.12"
  else
    echo "Installez Python 3.10+ : sudo apt install -y python3 python3-venv git"; exit 1
  fi
fi
echo "  $PY ($("$PY" -V))"
"$PY" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
VPY="$ROOT/.venv/bin/python"

say "2/5 Données : $DATA"
mkdir -p "$DATA/logs"
chmod 700 "$DATA"
[ -f "$DATA/profile.txt" ] || echo profit > "$DATA/profile.txt"
export MEMEDESK_DATA="$DATA"
"$VPY" "$APP/manage.py" agent-token >/dev/null
echo "  jeton agent : $DATA/agent_token.txt (chmod 600). Ne le commitez pas."

if [ "$WANT_OLLAMA" = 1 ]; then
  say "3/5 IA locale — $MODEL"
  if ! command -v ollama >/dev/null; then
    if [ "$OS" = Darwin ] && command -v brew >/dev/null; then brew install ollama
    elif ask "Installer Ollama (curl https://ollama.com/install.sh) ?"; then curl -fsSL https://ollama.com/install.sh | sh
    else warn "Ollama ignoré. Les ordres JSON et les règles simples marchent quand même."; fi
  fi
  if command -v ollama >/dev/null; then
    if [ "$OS" = Darwin ] && command -v brew >/dev/null && brew list ollama >/dev/null 2>&1; then brew services start ollama >/dev/null || true; fi
    curl -fsS -m 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1 || { (nohup ollama serve >/dev/null 2>&1 &); sleep 3; }
    ollama pull "$MODEL" || warn "Téléchargement impossible : ollama pull $MODEL"
  fi
else
  say "3/5 IA locale ignorée (--no-ollama)"
fi

say "4/5 Compte"
if [ "$(cd "$APP" && MEMEDESK_DATA="$DATA" "$VPY" -c 'import webauth; print(webauth.user_count())')" = 0 ]; then
  read -r -p "Identifiant du propriétaire : " U
  (cd "$APP" && "$VPY" manage.py create-user "$U" --role owner)
else
  (cd "$APP" && "$VPY" manage.py list-users)
fi

if [ "$WANT_SERVICE" = 1 ]; then
  say "5/5 Démarrage"
  if [ "$OS" = Darwin ]; then
    for c in server desk intensif ai; do plist "com.kairo.$c" true "$VPY" "$APP/run.py" "$c"; done
    if [ "$WANT_CAFF" = 1 ]; then plist com.kairo.caffeinate true /usr/bin/caffeinate -dimsu; fi
    [ -f "$HOME/.cloudflared/config.yml" ] && tunnel_service
    warn "Sur secteur, pour empêcher la veille capot fermé : sudo pmset -c sleep 0 disablesleep 1"
  elif command -v systemctl >/dev/null; then
    sed -e "s#__USER__#$(id -un)#g" -e "s#__APP__#$APP#g" -e "s#__ROOT__#$ROOT#g" -e "s#__DATA__#$DATA#g" -e "s#__MODEL__#$MODEL#g" -e "s#__UI__#$UI#g" \
      "$APP/deploy/kairo.service" | sudo tee /etc/systemd/system/kairo.service >/dev/null
    sudo systemctl daemon-reload && sudo systemctl enable --now kairo
    [ -f "$HOME/.cloudflared/config.yml" ] && tunnel_service
  else
    warn "Pas de systemd. Lancez : MEMEDESK_DATA=$DATA $VPY $APP/run.py all"
  fi
else
  say "5/5 Sans service. Lancez : MEMEDESK_DATA=$DATA $VPY $APP/run.py all"
fi

sleep 2
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$PORT/login" || true)
if [ "$code" = 200 ]; then echo "OK : http://127.0.0.1:$PORT"; else warn "Le serveur ne répond pas encore ($code). Voir $DATA/logs/server.log"; fi
