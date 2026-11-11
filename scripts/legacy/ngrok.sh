#!/usr/bin/env bash
# ngrok tunnel to the dashboard on the account's static dev domain. Authtoken comes from ~/.config/ngrok (set from $NGROK_AUTHTOKEN).
cd /workspace/memedesk
DOMAIN="greedless-reptilian-oversized.ngrok-free.dev"
echo "https://$DOMAIN" > public_url.txt
exec ./ngrok http 8787 --url "https://$DOMAIN" --log stdout --log-format logfmt
