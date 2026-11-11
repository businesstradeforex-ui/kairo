#!/usr/bin/env bash
# Update only the optional UI checkout (static/). Does not execute repository code.
set -euo pipefail
UI_DIR="${MEMEDESK_UI_DIR:-$HOME/kairo-ui}"
[ -d "$UI_DIR/.git" ] || { echo "Pas de checkout git dans $UI_DIR"; exit 1; }
before=$(git -C "$UI_DIR" rev-parse HEAD)
GIT_TERMINAL_PROMPT=0 git -c core.hooksPath=/dev/null -C "$UI_DIR" pull --ff-only --quiet
after=$(git -C "$UI_DIR" rev-parse HEAD)
if [ "$before" = "$after" ]; then echo "Interface déjà à jour (${after:0:12})."
else echo "Interface : ${before:0:12} -> ${after:0:12}"; fi
