#!/usr/bin/env bash
# Restart one supervised child (desk|server|intensif) without killing its supervisor loop.
pkill -f "^python3 -u $1.py" && echo "killed $1; supervisor restarts it in ~10s"
