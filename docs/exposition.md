# Exposer Kairo, et l'installer sur iPhone

Le serveur n'écoute que sur `127.0.0.1`. On ne le publie pas directement. Un tunnel sortant fournit le HTTPS.

## Cloudflare Tunnel (recommandé)

1. Compte gratuit sur https://dash.cloudflare.com et un nom de domaine (souvent la seule dépense, environ le prix coûtant du `.com`).
2. Sur la machine :

```bash
# macOS : brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create kairo
cloudflared tunnel route dns kairo kairo.votredomaine.com
```

3. `~/.cloudflared/config.yml` — un exemple est dans `kairo/deploy/cloudflared-config.example.yml`.
4. `./install.sh --tunnel`

Ouvrez `https://kairo.votredomaine.com`. Test sans domaine : `cloudflared tunnel --url http://127.0.0.1:8787` (l'adresse change à chaque fois).

Si vous activez Cloudflare Access, laissez passer `/api/orders` et `/api/owner` pour l'assistant, ou créez un service token. Sinon l'API sera bloquée devant la page de login.

`TRUST_PROXY=1` est posé par l'install et par Docker, et les en-têtes `X-Forwarded-*` ne sont lus que depuis localhost.

## ngrok

```bash
ngrok http 8787
```

Le jeton ngrok reste dans `~/.config/ngrok/ngrok.yml`, pas dans le dépôt. L'URL publique change sur un tunnel gratuit.

Les scripts `scripts/legacy/ngrok.sh` et `tunnel.sh` sont ceux de l'ancienne machine. Ils ne sont pas le chemin par défaut.

## PWA sur iPhone

1. Ouvrez le site **en HTTPS** dans Safari (un tunnel, pas `http://` sur l'IP du Mac : iOS n'installe une PWA fiable qu'en HTTPS, et l'accès LAN direct n'est pas le mode prévu).
2. Partager → **Sur l'écran d'accueil**.
3. L'icône Kairo s'ouvre en plein écran (`display: standalone`), barre noire, `apple-mobile-web-app-capable`.

Le manifeste, les icônes 180/192/512, les balises apple et `sw.js` sont servis par l'application. Le service worker ne met pas en cache `/api/`.

L'interface est pensée mobile d'abord (colonne 430 px, barre du bas, zones sûres iPhone).
