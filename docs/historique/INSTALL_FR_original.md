# Grok Desk — version web (papier) : guide d'installation

Ce dossier contient la version web du desk memecoins Solana. Vous y retrouvez la **même interface**, les **mêmes agents** (Scout, Filter, Analyst, Executor, Risk, Logger), le **mode intensif** et les mêmes profils. Trois choses changent :

- **une vraie page de connexion** (identifiant + mot de passe, plusieurs comptes, rôles *admin* et *lecture seule*) ;
- **une IA locale gratuite** (Ollama) qui exécute vos ordres en français, dans une liste blanche stricte ;
- **une API protégée par jeton**, pour que Grok Bot puisse donner des ordres à votre IA locale et mettre à jour l'interface.

> **Papier uniquement.** Aucun wallet, aucune clé, aucun ordre réel. L'IA locale ne peut ni acheter, ni vendre, ni transférer, ni lancer une commande système.

Le desk démarre sur une session neuve à **1 000 € virtuels**. L'historique du desk actuel n'est pas repris.

---

## 1. Puissance de calcul : ce qu'il faut vraiment

- **Le desk lui-même consomme peu.** Python et quelques appels d'API publiques par cycle suffisent. Un MacBook Air (M1 ou plus récent) fait largement l'affaire. La VM Oracle « Always Free » (4 cœurs ARM, 24 Go) a même plus de ressources que la machine qui fait tourner le desk aujourd'hui.
- **Une IA locale gratuite (3 à 8 milliards de paramètres) est beaucoup plus faible et plus lente qu'un grand modèle dans le cloud.** C'est pour ça qu'elle sert seulement à **traduire un ordre en une action autorisée** (changer de profil, mettre en pause, régler un paramètre borné, faire un résumé). Les décisions de stratégie et l'analyse lourde restent chez **Grok Bot**, qui pilote votre IA locale via l'API (partie 7).
- **Quel modèle choisir ?**

| Machine | Modèle conseillé | Remarque |
|---|---|---|
| MacBook Air 8 Go | `qwen2.5:3b` | environ 2 Go de RAM, réponse en 1 à 3 s (GPU Metal) |
| MacBook Air 16 Go et plus | `qwen2.5:7b` | environ 5 Go de RAM, plus fiable en français |
| Oracle ARM 24 Go (sans GPU) | `qwen2.5:7b` si la vitesse vous convient, sinon `qwen2.5:3b` | le 7b répond en environ 10 à 30 s par ordre sur processeur |

Changez de modèle avec `./install.sh --model qwen2.5:7b`. Pour éviter les erreurs, les formulations courantes (« mode profit », « pause », « liquidité min 20k », « résumé 6 h »…) sont reconnues **sans IA** par des règles fixes. Le modèle ne sert qu'aux phrases plus libres, et sa réponse est revérifiée avant d'être exécutée.

---

## 2. Installation sur votre MacBook Air (option principale)

### 2.1 Prérequis (une seule fois)
1. **Homebrew** : ouvrez le Terminal et collez la commande indiquée sur <https://brew.sh>.
2. Copiez le dossier `memedesk-web` dans votre dossier personnel, par exemple `~/grokdesk/memedesk-web`. **Évitez Bureau, Documents et Téléchargements** : macOS y bloque l'accès aux services en arrière-plan.
   ```bash
   mkdir -p ~/grokdesk && cd ~/grokdesk && tar xzf ~/Downloads/memedesk-web.tar.gz && cd memedesk-web
   ```

### 2.2 Installation
```bash
./install.sh                    # ou : ./install.sh --model qwen2.5:7b  (Mac 16 Go)
```
Le script :
- installe Python (si besoin) et un environnement isolé `.venv` ;
- installe **Ollama** (`brew install ollama`), le lance et télécharge le modèle ;
- crée le dossier de données `~/grokdesk-data` (bases, logs, jeton agent `agent_token.txt` en chmod 600) ;
- vous demande **l'identifiant et le mot de passe du compte admin**. Il n'existe aucun mot de passe par défaut ;
- installe **des services launchd** qui démarrent à l'ouverture de session et redémarrent en cas de plantage (KeepAlive) : `com.grokdesk.server`, `desk`, `intensif`, `ai`, plus `com.grokdesk.caffeinate` (anti-veille) et `com.grokdesk.cloudflared` une fois le tunnel configuré.

Ouvrez ensuite <http://127.0.0.1:8787> et connectez-vous.

### 2.3 Empêcher la mise en veille (indispensable)
Sur la machine actuelle, le desk se fige à chaque mise en veille. Sur le Mac, il faut l'éviter :
1. `caffeinate -dimsu` est lancé automatiquement par launchd (service `com.grokdesk.caffeinate`). Il empêche la veille **tant que votre session est ouverte**.
2. Pour que le Mac reste éveillé **capot fermé, sur secteur**, lancez une seule fois :
   ```bash
   sudo pmset -c sleep 0 disablesleep 1      # pour annuler : sudo pmset -c disablesleep 0
   ```
3. **Laissez le Mac branché sur le chargeur.** Sur batterie, macOS finira par dormir.
4. Réglages Système > Utilisateurs et groupes : activez **l'ouverture de session automatique**, pour que tout redémarre seul après une coupure de courant ou une mise à jour. Si FileVault est activé, macOS demandera quand même le mot de passe au démarrage : il faudra le saisir à la main.
5. Réglages Système > Économiseur d'énergie / Batterie > Options : cochez « Empêcher la suspension d'activité automatique lorsque l'écran est éteint » (sur secteur).

Limites honnêtes du Mac : il chauffe un peu capot fermé, le Wi-Fi peut décrocher, et les mises à jour macOS redémarrent la machine. Le site est alors inaccessible quelques minutes, puis les services reviennent seuls.

### 2.4 Commandes utiles (Mac)
```bash
tail -f ~/grokdesk-data/logs/desk.log                     # cycles du desk
launchctl kickstart -k gui/$(id -u)/com.grokdesk.desk     # redémarrer le desk
./uninstall.sh                                             # retirer les services (données conservées)
```

---

## 3. Comptes et rôles
```bash
cd ~/grokdesk/memedesk-web && export MEMEDESK_DATA=~/grokdesk-data
.venv/bin/python manage.py create-user mael --role admin      # ordres + réglages
.venv/bin/python manage.py create-user ami --role viewer      # tableau de bord en lecture seule
.venv/bin/python manage.py list-users
.venv/bin/python manage.py delete-user ami
```
- Les mots de passe font au moins 10 caractères. Ils sont hachés avec **scrypt** (sel aléatoire) et jamais stockés en clair.
- La session est gardée dans un cookie **HttpOnly, SameSite=Strict**, avec l'attribut **Secure** derrière HTTPS. Elle dure 30 jours, ou 7 jours sans visite.
- Après 5 échecs en 15 minutes (par adresse IP ou par identifiant), la connexion est bloquée pendant 15 minutes.
- Le bouton **Se déconnecter** se trouve dans l'onglet **Compte**.

---

## 4. Votre nom de domaine + Cloudflare Tunnel (accès depuis l'extérieur)

Le serveur écoute seulement sur `127.0.0.1` : il n'est jamais exposé directement. Cloudflare Tunnel établit une connexion **sortante** vers Cloudflare. Vous n'avez aucun port à ouvrir sur votre box, et le HTTPS est fourni gratuitement.

### 4.1 Acheter le domaine (payant)
1. Créez un compte gratuit sur <https://dash.cloudflare.com>.
2. Allez dans **Domain Registration > Register Domains** et achetez votre `.com`. Cloudflare le vend au prix coûtant, environ 10 à 11 $ par an, sans marge. C'est la **seule dépense** de toute l'installation.

### 4.2 Créer le tunnel nommé (sur le Mac)
```bash
brew install cloudflared
cloudflared tunnel login                         # ouvre le navigateur : choisissez votre domaine
cloudflared tunnel create grokdesk               # affiche un UUID et crée ~/.cloudflared/<UUID>.json
cloudflared tunnel route dns grokdesk desk.votredomaine.com
```
Créez ensuite `~/.cloudflared/config.yml` (un modèle se trouve dans `deploy/cloudflared-config.example.yml`) :
```yaml
tunnel: <UUID>
credentials-file: /Users/<vous>/.cloudflared/<UUID>.json
ingress:
  - hostname: desk.votredomaine.com
    service: http://127.0.0.1:8787
  - service: http_status:404
```
Installez le service qui garde le tunnel ouvert en permanence :
```bash
./install.sh --tunnel
```
Ouvrez <https://desk.votredomaine.com> : la page de connexion s'affiche. Sur iPhone, utilisez Partager > « Sur l'écran d'accueil » pour retrouver l'app plein écran.

**Test rapide sans domaine** : `cloudflared tunnel --url http://127.0.0.1:8787` donne une adresse temporaire `https://xxxx.trycloudflare.com`. Elle change à chaque lancement, donc elle sert seulement à tester.

**Option : double protection.** Cloudflare Zero Trust > Access (gratuit jusqu'à 50 utilisateurs) peut demander un code reçu par e-mail avant même la page de connexion. Si vous l'activez, ajoutez une règle *Bypass* sur le chemin `/api/orders*` et `/api/update-ui`, ou créez un *Service Token* pour Grok Bot. Sinon, l'API sera bloquée.

---

## 5. Le panneau « Ordres & IA locale »

C'est le nouvel onglet **Ordres** (icône ✦). Écrivez un ordre ou touchez une suggestion :

| Exemple d'ordre | Action exécutée |
|---|---|
| « passe en mode profit » | profil `profit` (aussi `strict`, `agressif`) |
| « coupe l'intensif » / « relance l'intensif » | arrêt ou démarrage du mode intensif |
| « pause » / « reprends » | plus aucune nouvelle entrée ; Risk continue de surveiller les positions ouvertes |
| « liquidité min 20k » | `liq_min` (de 5 000 à 500 000 $) |
| « max 6 positions » | `max_open` (de 1 à 20) |
| « stop à 5 % » | `stop_pct` (de 2 à 15 %) |
| « trailing 6 % », « trailing activé à 12 % » | `trail_pct` (2–15 %), `trail_activate` (4–50 %) |
| « taille 5 % » | `max_frac`, taille max par position (1 à **8 % au maximum**) |
| « remets les paramètres par défaut » | annule les réglages ci-dessus |
| « résumé des 6 dernières heures » | bilan chiffré des trades (de 1 à 168 h) |

Le reste est **refusé et journalisé** : achat ou vente manuels, argent réel, wallet, clés, transferts, commandes système. L'historique s'affiche comme une conversation, et le **journal d'audit** indique qui a demandé quoi (vous ou Grok Bot) et le résultat.

Si Ollama est arrêté, le panneau l'indique. Les formulations simples et les ordres JSON continuent de fonctionner.

---

## 6. Mise à jour de l'interface via un dépôt GitHub privé

Grok Bot peut modifier l'interface (fichiers `static/` : HTML, CSS, JS) sans toucher au code des agents. Voici le principe :
1. Créez un dépôt **privé** sur GitHub, par exemple `memedesk-ui`, qui contient le dossier `static/` :
   ```bash
   cd ~/grokdesk && mkdir memedesk-ui-src && cp -r memedesk-web/static memedesk-ui-src/ && cd memedesk-ui-src
   git init -b main && git add static && git commit -m "Interface initiale"
   git remote add origin git@github.com:<votre-compte>/memedesk-ui.git && git push -u origin main
   ```
2. Sur le Mac du serveur, créez une **clé de déploiement en lecture seule** :
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/memedesk_ui -N ""
   cat ~/.ssh/memedesk_ui.pub    # à coller dans GitHub > memedesk-ui > Settings > Deploy keys (sans « Allow write access »)
   printf 'Host github-ui\n  HostName github.com\n  IdentityFile ~/.ssh/memedesk_ui\n  IdentitiesOnly yes\n' >> ~/.ssh/config
   ```
3. Clonez seulement `static/` à l'endroit lu par le serveur (`~/memedesk-ui` par défaut) :
   ```bash
   git clone --filter=blob:none --sparse git@github-ui:<votre-compte>/memedesk-ui.git ~/memedesk-ui
   git -C ~/memedesk-ui sparse-checkout set static
   launchctl kickstart -k gui/$(id -u)/com.grokdesk.server
   ```
   Si `~/memedesk-ui/static/index.html` existe, le serveur sert cette interface. Sinon, il sert celle livrée avec le code.
4. Pour récupérer une mise à jour :
   - à la main : `./update.sh` ;
   - à distance (Grok Bot) : `POST /api/update-ui` avec le jeton agent. Le serveur fait un `git pull --ff-only` (hooks désactivés) et ne sert que des fichiers statiques. **Aucun code n'est exécuté.**
5. Donnez à Grok Bot l'accès en écriture à ce dépôt, via votre connexion GitHub dans l'app Grok Bot. Il y pousse ses modifications, puis appelle `/api/update-ui`.

---

## 7. Connecter Grok Bot (API agent)

- **Adresse** : `https://desk.votredomaine.com`
- **Jeton** : le contenu de `~/grokdesk-data/agent_token.txt`. Transmettez-le à Grok Bot par un canal privé, par exemple le coffre-fort de l'app Grok Bot. Ne le publiez jamais. Pour le remplacer : `manage.py rotate-agent-token`.

```bash
# Envoyer un ordre (JSON structuré ou phrase en français) et attendre le résultat jusqu'à 20 s
curl -X POST "https://desk.votredomaine.com/api/orders?wait=20" \
  -H "Authorization: Bearer $JETON" -H "Content-Type: application/json" \
  -d '{"action":"set_profile","profile":"profit"}'
curl -X POST ".../api/orders?wait=20" -H "Authorization: Bearer $JETON" -H "Content-Type: application/json" \
  -d '{"order":"résumé des 12 dernières heures"}'
# État de l'IA locale + derniers ordres + journal d'audit
curl -H "Authorization: Bearer $JETON" "https://desk.votredomaine.com/api/orders?limit=20"
# Mettre à jour l'interface depuis GitHub
curl -X POST -H "Authorization: Bearer $JETON" https://desk.votredomaine.com/api/update-ui
```
Codes de réponse : `200` exécuté, `422` refusé (hors liste blanche ou hors bornes), `401` jeton absent ou faux, `202` encore en cours.

---

## 8. Alternative : Oracle Cloud « Always Free » (serveur toujours allumé, gratuit)

Si vous préférez ne pas laisser le Mac allumé :
1. Créez un compte sur <https://www.oracle.com/cloud/free/>. **Une carte bancaire est demandée pour vérifier votre identité, mais rien n'est prélevé** tant que vous restez sur les ressources « Always Free ». Choisissez une région proche, par exemple Paris ou Marseille. Elle ne pourra plus être changée.
2. Allez dans Compute > Instances > Create : image **Ubuntu 24.04**, forme **VM.Standard.A1.Flex** (Ampere ARM), **4 OCPU / 24 Go**. Ajoutez votre clé SSH publique.
   L'erreur « Out of capacity » est fréquente : réessayez plus tard ou dans un autre domaine de disponibilité. Oracle peut récupérer une instance gratuite restée inactive : le desk tourne en continu, mais passez le compte en « Pay As You Go » (sans dépense tant que vous restez dans les limites gratuites) pour éviter ce risque.
3. Connectez-vous à la VM, puis installez :
   ```bash
   ssh ubuntu@<ip>
   sudo apt update && sudo apt install -y python3 python3-venv git curl
   scp memedesk-web.tar.gz ubuntu@<ip>:   # depuis votre Mac
   tar xzf memedesk-web.tar.gz && cd memedesk-web && ./install.sh --model qwen2.5:7b   # ou qwen2.5:3b si c'est trop lent
   ```
   Le script installe Ollama (après confirmation) et crée un service **systemd** `grokdesk`.
4. Le tunnel Cloudflare se configure comme en partie 4 (`sudo apt install cloudflared`, ou le paquet `.deb` arm64 de Cloudflare), puis `./install.sh --tunnel`. Aucun port n'est à ouvrir dans le pare-feu Oracle.

---

## 9. Alternative : Docker
```bash
docker compose up -d --build
docker compose run --rm desk python manage.py create-user mael --role admin
docker compose exec ollama ollama pull qwen2.5:3b
```
Pour le tunnel : créez un tunnel « géré à distance » dans Cloudflare Zero Trust > Networks > Tunnels, avec le service `http://desk:8787`. Mettez son jeton dans `.env` (`TUNNEL_TOKEN=...`), puis lancez `docker compose --profile tunnel up -d`.
Sur Mac, Docker n'a pas accès au GPU : Ollama y est nettement plus lent. Préférez l'installation native (partie 2).

---

## 10. Dépannage
- **Page blanche ou erreur 502 via le domaine** : le serveur local est arrêté. Lancez `curl http://127.0.0.1:8787/health`, puis consultez `~/grokdesk-data/logs/server.log`.
- **« Trop de tentatives »** : attendez 15 minutes. Ce blocage est prévu contre les attaques.
- **IA locale hors ligne** : `ollama list`, puis `brew services restart ollama`.
- **Le desk ne trade plus** : vérifiez s'il est en pause (onglet Ordres > État) et consultez `logs/desk.log`.
- Tout est journalisé dans `~/grokdesk-data/logs/` et dans la table d'audit (onglet Ordres).
