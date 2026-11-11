#!/usr/bin/env bash
# cloudflared quick tunnel (no account). Writes the public URL to public_url.txt.
cd /workspace/memedesk
./cloudflared tunnel --no-autoupdate --url http://localhost:8787 2>&1 | while IFS= read -r line; do
  echo "$line"
  u=$(echo "$line" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1)
  if [ -n "$u" ]; then echo "$u" > public_url.txt; echo "[$(date '+%F %T %Z')] public URL $u" >> logs/supervisor.log; fi
done
