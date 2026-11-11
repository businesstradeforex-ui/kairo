# Changelog

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
