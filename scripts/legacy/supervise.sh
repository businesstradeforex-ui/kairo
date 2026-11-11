#!/usr/bin/env bash
# Auto-restart supervisor: supervise.sh <name> <command...>
name="$1"; shift
cd /workspace/memedesk
while true; do
  echo "[$(date '+%F %T %Z')] starting $name" >> logs/supervisor.log
  "$@" >> "logs/$name.log" 2>&1
  echo "[$(date '+%F %T %Z')] $name exited code $? - restarting in 10s" >> logs/supervisor.log
  sleep 10
done
