# Docker

```bash
cp .env.example .env
docker compose up -d --build
docker compose run --rm kairo python manage.py create-user you --role owner
docker compose exec ollama ollama pull qwen3:4b
```

- Les données sont dans le volume `kairo-data` (bases, journaux, `secret.key`, jeton). Elles ne sont pas dans l'image.
- `KAIRO_LIVE_ENABLED` reste à 0.
- Le conteneur écoute `0.0.0.0` **à l'intérieur**, mais Compose ne publie le port que sur `127.0.0.1`.
- Santé : `GET /health`.

Tunnel géré par Cloudflare (jeton à distance) :

```bash
# .env : TUNNEL_TOKEN=...
docker compose --profile tunnel up -d
```

Le service interne du tunnel doit viser `http://kairo:8787`.

Sur Mac, préférez `./install.sh` : Ollama natif utilise le GPU Metal. Docker ne le voit pas.
