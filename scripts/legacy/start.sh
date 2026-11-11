#!/usr/bin/env bash
# Start everything (idempotent): desk daemon, dashboard server, ngrok tunnel, watchdog — each under an auto-restart loop.
cd /workspace/memedesk
start() { pgrep -f "supervise.sh $1 " >/dev/null && { echo "$1 already supervised"; return; }; setsid nohup ./supervise.sh "$@" >/dev/null 2>&1 < /dev/null & echo "started $1"; }
start desk python3 -u desk.py
start server python3 -u server.py
[ "${ENABLE_TUNNEL:-0}" = 1 ] && start tunnel ./tunnel.sh  # cloudflared: blocked on this box (egress port 7844 closed)
start intensif python3 -u intensif.py
start ngrok ./ngrok.sh
start watchdog ./watchdog.sh
true
