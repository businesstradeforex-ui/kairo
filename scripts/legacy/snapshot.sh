#!/usr/bin/env bash
# Snapshot dashboard screens to PNG with headless Chrome (mobile viewport 430x932 @2x).
# Usage: ./snapshot.sh [mint_for_detail]
cd /workspace/memedesk
K=$(cat .access_token); B="http://localhost:8787"; TS=$(date +%Y%m%d-%H%M)
MINT="${1:-$(python3 -c "
import sqlite3;c=sqlite3.connect('desk.db')
r=c.execute(\"SELECT mint FROM positions ORDER BY status='open' DESC, id DESC LIMIT 1\").fetchone() or c.execute('SELECT mint FROM scores ORDER BY score DESC LIMIT 1').fetchone() or c.execute('SELECT mint FROM token_meta ORDER BY ts DESC LIMIT 1').fetchone()
print(r[0] if r else '')")}"
shot() { google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
  --window-size=430,932 --virtual-time-budget=9000 --screenshot="$2" "$1" >/dev/null 2>&1; echo "$2"; }
shot "$B/?k=$K" "snapshots/home-$TS.png"
shot "$B/?k=$K#agents" "snapshots/agents-$TS.png"
shot "$B/?k=$K#activity" "snapshots/activity-$TS.png"
shot "$B/?k=$K#intensif" "snapshots/intensif-$TS.png"
[ -n "$MINT" ] && shot "$B/?k=$K&token=$MINT" "snapshots/token-$TS.png"
