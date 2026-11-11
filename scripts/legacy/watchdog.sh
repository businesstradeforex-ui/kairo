#!/usr/bin/env bash
# 24/7 watchdog (runs under supervise.sh). Every 10 s (public URL every 60 s):
#  - re-runs start.sh (idempotent) so any missing supervisor loop comes back;
#  - desk: heartbeat file or desk.log older than 300 s => kill desk.py (its supervisor restarts it);
#  - server: local dashboard must answer HTTP 200 with the key (2 strikes) => kill server.py;
#  - ngrok: public URL must answer (3 strikes) => kill the ngrok process.
cd /workspace/memedesk
KEY=$(cat .access_token)
URL=$(cat public_url.txt 2>/dev/null || echo https://greedless-reptilian-oversized.ngrok-free.dev)
s_fail=0; n_fail=0; t_fail=0; loop_i=0
log(){ echo "[$(date '+%F %T %Z')] watchdog: $*" >> logs/watchdog.log; }
log "start"
while true; do
  loop_i=$((loop_i+1))
  [ $((loop_i % 6)) -eq 1 ] && ./start.sh >/dev/null 2>&1
  now=$(date +%s)
  hb=$(stat -c %Y heartbeat 2>/dev/null || echo 0)
  dl=$(stat -c %Y logs/desk.log 2>/dev/null || echo 0)
  newest=$(( hb > dl ? hb : dl ))
  if pgrep -f "^python3 -u desk.py" >/dev/null && [ $(( now - newest )) -gt 120 ] && [ $(( now - ${desk_kill:-0} )) -gt 90 ]; then
    log "desk stale ($(( now - newest ))s) -> restart"; pkill -9 -f "^python3 -u desk.py"; desk_kill=$now
  fi
  ih=$(stat -c %Y heartbeat_intensif 2>/dev/null || echo 0)
  if pgrep -f "^python3 -u intensif.py" >/dev/null && [ $(( now - ih )) -gt 120 ] && [ $(( now - ${int_kill:-0} )) -gt 90 ]; then
    log "intensif stale ($(( now - ih ))s) -> restart"; pkill -9 -f "^python3 -u intensif.py"; int_kill=$now
  fi
  code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:8787/api/summary?k=$KEY")
  if [ "$code" != 200 ]; then s_fail=$((s_fail+1)); log "server http $code (strike $s_fail)"; else s_fail=0; fi
  if [ $s_fail -ge 2 ]; then log "server down -> restart"; pkill -9 -f "^python3 -u server.py"; s_fail=0; fi
  # ngrok tunnel state via its local API, every loop (no public request)
  if curl -s -m 3 http://127.0.0.1:4040/api/tunnels | grep -q '"public_url":"https'; then t_fail=0; else t_fail=$((t_fail+1)); log "tunnel api down (strike $t_fail)"; fi
  if [ $t_fail -ge 2 ]; then log "tunnel down -> restart ngrok"; pkill -f "ngrok http 8787"; t_fail=0; fi
  if [ $((loop_i % 6)) -eq 1 ]; then
  pcode=$(curl -s -o /dev/null -m 15 -H 'ngrok-skip-browser-warning: 1' -w '%{http_code}' "$URL/api/summary?k=$KEY")
  if [ "$pcode" != 200 ]; then n_fail=$((n_fail+1)); log "public $pcode (strike $n_fail)"; else n_fail=0; fi
  if [ $n_fail -ge 3 ]; then log "tunnel down -> restart ngrok"; pkill -f "ngrok http 8787"; n_fail=0; fi
  fi
  # wake detection: if the loop was frozen (box asleep), restart desk and ngrok right away
  t_now=$(date +%s)
  if [ -n "$last_loop" ] && [ $(( t_now - last_loop )) -gt 40 ]; then
    log "wake after $(( t_now - last_loop ))s gap -> restart desk + ngrok"
    pkill -f "^python3 -u desk.py"; pkill -f "^./ngrok http"; desk_kill=$t_now
  fi
  last_loop=$t_now
  sleep 10
done
