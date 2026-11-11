# Docker

Image publiée (linux/amd64 et linux/arm64) : `ghcr.io/businesstradeforex-ui/kairo:1.0.0`.

```bash
docker compose pull
docker compose up -d
docker compose run --rm kairo python manage.py create-user you --role owner
```

Le conteneur écoute dans le réseau Docker, et Compose ne publie le port que sur `127.0.0.1:8787`. `KAIRO_LIVE_ENABLED` vaut 0. `KAIRO_NO_BROWSER=1`.

Ollama sur la machine hôte est le défaut (`http://host.docker.internal:11434`). Pour un Ollama dans Compose :

```bash
OLLAMA_URL=http://ollama:11434 docker compose --profile ai up -d
docker compose exec ollama ollama pull qwen3:4b
```

Construire au lieu de tirer l'image : `docker compose up -d --build`.

```bash
cp .env.example .env
docker compose up -d --build
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
