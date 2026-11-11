# Sécurité — Kairo

Kairo est un logiciel expérimental. Le mode par défaut est le **paper trading**. Les memecoins peuvent perdre toute leur valeur. Ne mettez pas de clé avec permission de retrait.

English summary: paper trading is the default. Live orders need a server flag, a per-account opt-in, a one-time confirmation, hard caps and a kill switch. Report vulnerabilities privately to the repository owner. Do not open a public issue with exploit details.

## Signaler un problème

Écrivez au propriétaire du dépôt en privé. Décrivez l'impact et une façon de le reproduire. Donnez un délai raisonnable avant toute publication.

## Ce qui est en place

- Mots de passe : scrypt (N=2^14, r=8, p=1), sel aléatoire, 10 à 200 caractères. Jamais stockés en clair, jamais passés en argument de commande.
- Sessions : jeton aléatoire, seul le SHA-256 est en base. Cookie `HttpOnly`, `SameSite=Lax`, `Secure` derrière HTTPS. 30 jours au plus, 7 jours d'inactivité.
- CSRF : jeton de session exigé sur les POST du navigateur (`X-CSRF-Token` doit égaler le cookie et la session). Les jetons Bearer n'utilisent pas le cookie.
- En-têtes : CSP stricte (`script-src 'self'`, pas de script inline), `frame-ancestors 'none'`, `nosniff`, Referrer-Policy `no-referrer`, Permissions-Policy, COOP, HSTS quand la requête est en HTTPS.
- Limitation : verrouillage persistant après 5 échecs / 15 min (IP et identifiant). Plafonds séparés sur l'inscription, les liens magiques et les ordres.
- SQL : requêtes paramétrées. Une entrée du type `' OR 1=1` ne change pas la requête.
- Secrets des connecteurs : Fernet (cryptography), clé `KAIRO_SECRET_KEY` ou fichier `secret.key` en chmod 600. L'API ne renvoie que les 4 derniers caractères.
- Phantom / Solflare : adresse publique uniquement. Toute clé privée, seed ou phrase secrète est refusée.
- Trading réel : `KAIRO_LIVE_ENABLED=0` par défaut. Même à 1, il faut `confirm=LIVE`, puis pour chaque ordre un jeton à usage unique et le mot `CONFIRMER`. Plafonds d'environnement non contournables. Kill switch global et par compte.
- IA locale : elle ne choisit pas les trades. Elle traduit une phrase en une action d'une liste blanche, revérifiée. Température 0, débit limité. Pas de shell.
- Espace propriétaire : rôle `owner` seulement. Jeton à scopes (`read`, `params`, `orders`, `ui`, `live`), hashé, révocable, rotatif. `KAIRO_ADMIN_ALLOWLIST` limite les jetons Bearer. L'en-tête `X-Forwarded-For` n'est lu que si `TRUST_PROXY=1` **et** que le pair TCP est loopback.
- 2FA : TOTP (RFC 6238) optionnel sur les comptes mot de passe.
- Production : `KAIRO_ENV=production` masque le détail des exceptions. `server_version` ne divulgue pas la version de Python. Pas de mode debug.

## Revue faite sur le code d'origine, et corrections

| Problème | Correction |
|---|---|
| Réponses 500 qui renvoyaient `str(exception)` | Message générique en production |
| Pas de CSP | CSP stricte, scripts externes seulement |
| CSRF limité à un en-tête maison | Jeton lié à la session |
| `hmac.compare_digest` lève si les longueurs diffèrent | Comparaison des SHA-256 |
| Mot de passe sans longueur max (coût scrypt) | 200 caractères |
| `TRUST_PROXY` faisait confiance à n'importe quel client | Uniquement depuis 127.0.0.1 / ::1 |
| Un seul jeton agent dans un fichier, sans scope ni révocation fine | Jetons hashés, scopes, rotation, journal |
| Journal et file d'ordres visibles par tous les comptes | Filtrés par compte ; le propriétaire voit l'ensemble |
| id_token Apple copié depuis le navigateur | Seul l'id_token renvoyé par l'endpoint Apple en HTTPS est lu |
| Secrets API qui auraient été en clair | Chiffrement au repos, jamais renvoyés |
| Trading réel absent, donc facile à ajouter sans garde | Désactivé, opt-in, confirmation, plafonds, kill switch |

## Limites honnêtes

- Le verrouillage et les quotas de débit sont en mémoire pour le débit, en base pour les échecs de login. Plusieurs processus ne partagent pas le quota de débit.
- Le cookie de session est `SameSite=Lax` (pas `Strict`) pour que le retour Google / Apple puisse poser la session. Les POST passent par le CSRF.
- La signature du id_token Apple n'est pas revérifiée sur les JWKS : le jeton est celui renvoyé par `https://appleid.apple.com/auth/token` après échange du code avec le secret client. Vérifiez ce secret et l'`aud`.
- `git pull` de l'interface n'exécute rien (hooks coupés, fast-forward). Ne pointez `MEMEDESK_UI_DIR` que vers un dépôt de confiance.
- Binance et Coinbase enregistrent la clé mais n'envoient pas d'ordre tant qu'un transport signé n'est pas branché. Kraken peut envoyer un ordre marché **seulement** si toutes les gardes passent.
- Ce n'est pas un audit externe.
