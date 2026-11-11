# Changelog

## 1.2.0 — 2026-11-11

Écran revu (courbe, compteurs, modèle) et mode turbo, toujours en papier.

- La courbe d'équité a des plages LIVE, 1H, 4H, 1J, 1S, TOUT. Un trou dans les points n'est plus un trait droit. Sur TOUT, le badge suit le même écart que l'en-tête (équité moins capital de départ).
- L'état du desk est écrit dans le dossier du compte. Les compteurs Scout viennent de ce dossier, plus de zéros quand le journal montre des paires scannées.
- Le modèle d'IA est celui du fichier partagé `model.txt`. Un compte peut le remplacer avec son propre fichier. L'écran affiche le modèle réellement lu.
- Onglet Flux : dernière décision de chaque agent, et ce que le mode turbo a retenu.
- Réinitialiser le compte papier archive la session (elle n'est pas effacée) puis repart à 100, 500, 1 000, 5 000, 10 000 € ou un montant libre.
- Mode turbo : jusqu'à 10 positions, surveillance des sorties chaque seconde, frais de swap et frais de priorité dans le prix papier, taille selon le score, stops suiveurs et sortie de temps. Aucun trade n'est forcé.
- Le turbo tient un journal des pertes et baisse ou bloque un type de setup après assez d'exemples. Les modes strict, agressif et profit gardent leurs règles d'origine.
- Rejeu du fichier de labels `backtest_chart.json` (41 trades archivés, pas une bande de ticks) : agressif −3 986,60 $ (2 gains sur 41) ; turbo prend 21 trades et saute 20, pnl enregistré −2 574,70 $ (1 gain), −1 976,15 $ si l'on applique la taille réduite. Le seau bloqué est `chart_fail|liq_low`.

Paper par défaut. Trading réel éteint.

## 1.1.0 — 2026-11-11

Kairo.app est une application Mac, plus seulement un serveur qui ouvre Safari.

- Fenêtre native (WKWebView via pywebview), icône Dock, menu (À propos, Préférences, Quitter), taille et position mémorisées.
- Icône dans la barre des menus : état du desk, équité, Ouvrir, Pause ou Reprendre, Quitter.
- Le desk démarre avec l'app et s'arrête sur Quitter. Préférences : rester en arrière-plan quand la fenêtre se ferme, ouvrir à la connexion, notifications des trades clôturés.
- Écran d'accueil : détection Ollama, conseil de modèle selon la RAM et le disque libre (au moins 4 Go gardés), téléchargement avec progression, test de connexion.
- Le `.dmg` est signé ad hoc (`codesign -`) pour Apple Silicon. Gatekeeper : Réglages Système → Confidentialité et sécurité → Ouvrir quand même, ou `xattr -dr com.apple.quarantine /Applications/Kairo.app`.
- Windows utilise la même fenêtre si pywebview est dans le zip. Linux reste sur le navigateur.

Paper par défaut. Trading réel éteint.

## 1.0.0 — 2026-11-11

Paquets autonomes. Python et les dépendances sont dans l'archive : il n'y a plus rien à installer à part, si ce n'est l'IA locale que vous choisissez.

- Release GitHub sur un tag `v*` (et un lancement manuel) : macOS arm64 et Intel (dmg + zip), Windows x64 (zip), Linux x64 et arm64 (tar.gz, deb, AppImage).
- Premier lancement : dossier de données, clé de chiffrement, navigateur, détection d'Ollama / LM Studio / llama.cpp, page `/setup` si rien n'écoute.
- Image `ghcr.io/businesstradeforex-ui/kairo` (amd64 et arm64). Ollama dans Compose est optionnel (`--profile ai`).
- `curl | bash` et `install.ps1` téléchargent la dernière release.
- `pipx install` depuis le dépôt git (`pyproject.toml`). Les manifests Homebrew, Scoop et winget sont produits par la release (empreintes réelles) et joints aux fichiers. Ils ne sont pas publiés dans un tap séparé ni soumis à winget-pkgs : voir le README.

Le trading réel reste désactivé par défaut.

## 0.1.0 — 2026-11-11

Première publication publique de Kairo.

- Moteur d'origine conservé : Scout, Filter, Analyst, Executor, Risk, Logger, modes strict / agressif / profit, mode intensif, apprentissage, rapports.
- Comptes isolés : e-mail et mot de passe, lien magique, Google, Apple, Sign in with Solana (Phantom). Chaque fournisseur se coupe s'il n'est pas configuré. Le mot de passe fonctionne sans rien d'autre.
- Comptes connectés : Phantom et Solflare (adresse publique seulement), Kraken, Binance, Coinbase (secrets chiffrés), Jupiter (cotations). Trading réel désactivé par défaut, opt-in, confirmation, plafonds, kill switch.
- Espace propriétaire : jeton à scopes, rotation, révocation, journal d'audit, liste d'IP optionnelle.
- IA locale : Ollama et serveurs compatibles OpenAI (LM Studio, llama.cpp, etc.), liste blanche inchangée.
- Durcissement : CSRF, CSP, en-têtes, limitation de débit, verrouillage, cookies, 2FA TOTP, requêtes paramétrées.
- PWA installable, interface française avec bascule anglaise sur les libellés principaux.
- Tests, CI GitHub Actions, licence MIT.
