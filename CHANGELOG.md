# Changelog

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
