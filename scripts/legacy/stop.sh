#!/usr/bin/env bash
pkill -f "supervise.sh" ; pkill -f "^python3 -u desk.py"; pkill -f "^python3 -u server.py"; pkill -f "^python3 -u intensif.py"; pkill -f "cloudflared tunnel"; pkill -f "ngrok http"; pkill -f "watchdog.sh"; echo stopped
