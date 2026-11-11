# Desk memecoins Solana — Grok Bot (MODE PAPIER)

**Papier uniquement** : aucun wallet, aucune clé, aucun ordre réel. Uniquement des API publiques en lecture.

Profil actif : **profit** (fichier `profile.txt`). Les profils **strict** (règles d'origine) et **agressif** restent disponibles.

## Lancer / arrêter
- `./start.sh` — démarre (idempotent) le daemon `desk.py` et le dashboard `server.py`, chacun dans une boucle de redémarrage auto (`supervise.sh`, setsid/nohup).
- `./stop.sh` — arrête tout.
- `./restart_child.sh desk|server|intensif` — redémarre un seul process (le reste continue).
- `python3 report.py` — génère `report.md`.
- `./snapshot.sh [mint]` — captures PNG (430×932 @2x) dans `snapshots/`.
- Dashboard : `http://localhost:8787/?k=$(cat .access_token)` (jeton obligatoire, cookie posé ensuite).

## Changer de profil
```bash
echo profit    > /workspace/memedesk/profile.txt   # défaut, rechercher le profit
echo agressif  > /workspace/memedesk/profile.txt   # fréquence max, plus risqué
echo strict    > /workspace/memedesk/profile.txt   # règles d'origine
./restart_child.sh desk
```
On peut aussi exporter `DESK_PROFILE=profit|agressif|strict` (prioritaire sur le fichier). Le dashboard affiche le mode actif (« Mode profit », « Mode agressif », « Mode strict »).

## Pipeline (passages de relais stricts)
Chaque étape ne consomme que les objets produits par l'étape précédente et écrit son JSONL dans `logs/`.
1. **Scout** (`scout.py`, `logs/scout.jsonl`) — découverte de mints : DexScreener (token-profiles, token-boosts latest/top, community-takeovers, ads, `latest/dex/search` en rotation), compléments GeckoTerminal (new/trending pools) et Jupiter lite-api + liste de surveillance. **Toutes les métriques viennent de DexScreener** `tokens/v1/solana` (paire la plus liquide par token).
2. **Filter** (`filter.py`, `logs/filter_kills.jsonl`, `logs/filter_pass.jsonl`) — tous les motifs qui échouent sont journalisés. En mode agressif, les tokens reportés pour budget RugCheck vont dans `logs/filter_defer.jsonl`.
3. **Analyst** (`analyst.py`, `logs/analyst.jsonl`) — score 0–100 + signaux d'entrée rapide (mode agressif).
4. **Executor** (`executor.py`, `logs/executor.jsonl`) — ordres papier, taggés par déclencheur (`score`, `signal_momentum`, `signal_volume_spike`, `signal_breakout`).
5. **Risk** (`risk.py`, `logs/risk.jsonl`) — stops, surveillance intra-cycle, sortie temps si plat (agressif).
6. **Logger** (`logger.py`, `logs/logger.jsonl`, `desk.db`, `state.json`) — kills, scores, trades, equity, état des agents.

Backoff exponentiel sur 429/5xx, cache court et espacement minimal par hôte (`common.py`).

## Profil strict (règles d'origine)
- Fenêtre Scout : âge 30 min–72 h, market cap 300 k$–20 M$.
- Filter **fail-closed** : liq < 40 k$, vol 1 h < 50 k$, +80 % en 1 h, mint/freeze non révoqués, LP < 90 % brûlée/verrouillée, top 10 > 25 %, dev > 3 % ou rugs passés, bundle > 10 %. Données manquantes = élimination.
- Analyst : seuil **70**. Pas de signaux rapides.
- Executor : 8 % de l'equity, pas de plafond bas, pas de cooldown de ré-entrée (seulement pas de doublon ouvert).
- Risk : stop -6 % avant l'entrée ; trailing 6 % sous le pic après +12 %. Pas de sortie temps.
- Cycle ≈ 75 s ; ticks Risk ≈ 20 s.

## Profil agressif
Objectif : beaucoup plus de trades papier, cycles plus courts, tout en gardant les stops et le mode papier.
- **Scout** : âge **5 min–7 jours**, mcap **30 k$–50 M$**. Moins d'appels GeckoTerminal / Jupiter par cycle (caches + rotation) pour viser un cycle de ~20–30 s, tout en élargissant fortement la fenêtre.
- **Filter — éliminations dures seulement** :
  - mint authority ou freeze authority non révoquée (ou données mint/freeze introuvables après tentative) ;
  - liquidité < **10 k$** ;
  - volume 1 h < **3 k$** (coin mort) ;
  - token signalé *rugged* ;
  - concentration extrême (top 10 > 85 %, dev > 50 %, bundle > 70 %).
- **Filter — pénalités de score** (plus des éliminations) : LP < 50 % brûlée/verrouillée, top 10 > 40 %, dev > 10 %, bundle > 25 %, volume 1 h < 20 k$, déjà +80 % en 1 h, rugs passés du dev, données manquantes hors mint/freeze. Budget RugCheck : 12 nouveaux tokens / cycle (les autres sont reportés, pas tués). Cache 15 min.
- **Analyst** : seuil **45**. Un **signal** peut faire entrer dès un score de **28** :
  - momentum 5 min ≥ +3 % **et** ratio achats/ventes 5 min ≥ 1,3 (au moins 6 tx) ;
  - spike de volume : vol 5 min ≥ 2,5× la moyenne 5 min implicite du volume 1 h, et ≥ 1 500 $ ;
  - cassure : prix ≥ 1 % au-dessus du plus haut des échantillons de la dernière heure, avec m5 > 0.
- **Executor** : taille **3–8 %** de l'equity selon le score / la force du signal (jamais plus de 8 %). Jusqu'à **15** positions simultanées. Ré-entrée sur le même mint après **20 min** de cooldown.
- **Risk** : stop **-6 %** fixé avant l'entrée ; trailing **6 % sous le pic** dès **+12 %**. **Sortie temps** après **35 min** si le PnL latent est encore plat (±4 %) et que le trailing n'est pas actif — pour recycler le capital.
- Cycle cible ≈ **25 s** ; ticks Risk ≈ **10 s**.

## Session et devise (depuis le 10/11/2026 22:43)
- **Nouvelle session papier : 1 000 €** (Mode profit) + **1 000 €** séparés (Mode intensif). L'ancienne session (10 000 $ → ~6 059 $) est archivée dans `archive/session1-20261110-2243/` (desk.db + logs + state.json), non affichée.
- Les prix des tokens sont en USD. Au départ de la session, 1 000 € sont convertis au taux EUR/USD live (`common.eurusd()` : ECB via frankfurter.app, repli open.er-api.com, puis dernier taux connu en base, puis 1,08). Le dashboard affiche tout en € au taux live (comme un compte tenu en USD et affiché en EUR ; le taux bouge un peu l'équité en €).
- Max 8 % par trade (≈ 80 €).

## Profil profit (actif)
Objectif : PnL papier, peu de trades mais de qualité. Règles réglées sur les 39 trades de la session 1 (0 gagnant clos ; voir « Analyse »).

- **Scout** : âge **1 h – 7 j**, mcap **50 k$ – 30 M$**.
- **Filter — éliminations** (fail-closed) : mint/freeze non révoqués ; liquidité < **30 k$** ; volume 1 h < **10 k$** ; **liq/mcap < 10 %** ; **paire pumpswap/pump.fun de moins de 3 h** ; **+40 % en 1 h** (pas de chasse) ; +80 % en 1 h ; LP < 90 % brûlée/verrouillée ; top 10 > 35 % ; dev > 5 % ; bundle/initiés > 10 % ; rugs passés du dev ; token rugged.
- **Analyst** : score ≥ **60** (ou ≥ 55 + signal), **pression acheteuse** (achats/ventes 5 min ≥ 1,1 et achats 1 h > ventes) **et** un setup graphique sur bougies **1 min GeckoTerminal** (`chart.py`) :
  - tendance EMA9 > EMA21 (EMA21 non baissière), repli dans la zone EMA21/VWAP sur les 5 dernières bougies sans casser le support de plus de 4 %, **plus bas plus haut** que le swing précédent, clôture **au-dessus d'EMA9 et du VWAP**, bougie verte, volume ≥ moyenne des 10 dernières, prix ≤ +12 % au-dessus du VWAP ;
  - ou cassure confirmée sur 2 cycles **avec** tendance EMA et prix au-dessus du VWAP.
  Pas de bougies (ou flux > 4 min) = pas d'entrée. 3 appels graphiques par cycle max (limite GeckoTerminal).
- **Executor** : 3–8 % de l'equity selon le score, réduit pour garder un slippage estimé ≤ **1,5 %** (sinon trade sauté). Max **6** positions. Ré-entrée après 20 min. Pause 15 min après 3 pertes de suite. Coupe-circuit −15 % du jour. **Apprentissage** : taille ÷2 ou blocage selon `learn.py` (voir plus bas).
- **Risk** : stop **−6 % depuis le fill** ; trailing **6 % sous le pic** après **+12 %** ; **sorties en tranches** : 1/3 à **+15 %** (stop ramené au prix d'entrée), 1/3 à **+30 %**, le dernier tiers en trailing ; sortie temps après 35 min si plat (±4 %) ; **sortie forcée après 4 h**.
- **Prix** : même paire et `priceUsd` partout ; saut > 50 % revérifié sur un 2e endpoint DexScreener ; pas de cache HTTP sur les prix.
- Cycle ≈ 30 s ; ticks Risk ≈ 10 s.

### Analyse de la session 1 (39 trades, archive)
- **Le « bug de prix » n'en était pas un** : DAKITTY, DacityCoin, Gemini, MrBeast, STARBUCKS valent aujourd'hui ~0,0000015 $ avec ~1,6 k$ de liquidité sur la même paire → vrais rugs, sortis en gap à travers le stop (confirmé par deux endpoints). Gemini/MEOW/FAIR ont en plus été sortis en retard à cause du blocage de 3 h.
- Paires **pumpswap de moins de 3 h** : 13 trades, 13 pertes, ≈ −2 800 $ dont 4 rugs à −90 % → élimination.
- **Slippage d'entrée ≥ 4 %** (positions trop grosses pour la liquidité) : tous perdants → plafond 1,5 %.
- **Momentum déjà fort (composante ≥ 70)** : 13 trades, 13 pertes → interdiction de chasser (+40 % en 1 h) et entrée seulement sur repli.
- Les seuls non-perdants (THUG, FAIR, MYWAY) : paires de 22 à 126 h, Raydium/Meteora, momentum modéré, forte pression acheteuse, volume 1 h de 7–10 k$ → âge max 7 j, volume 1 h min abaissé à 10 k$.
- Les TP partiels à +15 % ont tous été gagnants ; les restes ont été rendus (rugs) → tranches + sortie max 4 h.
- Validation du filtre graphique sur l'historique (`backtest_chart.py`, résultats dans `backtest_chart.json`).

## Mode intensif v2 (parallèle, sous-portefeuille séparé 1 000 €)
`intensif.py` (asyncio), base `intensif.db`, état `intensif_state.json`, onglet ⚡ **Intensif**. PAPIER uniquement : aucun compte, aucune clé, aucun ordre.
- **Flux temps réel publics et gratuits** (testés depuis la machine) :
  - Binance spot WS (`aggTrade` + `depth5@100ms`) : BTC, ETH, SOL, BNB, XRP, DOGE, ADA, SUI, LINK, PEPE, WIF, BONK, **PAXG** (or tokenisé), **EUR/USDT** (forex en stablecoin) — long seulement ;
  - Binance perps USD-M WS : BTC, ETH, SOL, XRP, DOGE, SUI, 1000PEPE, WIF, BNB, **XAUUSDT** (or) — **long et short** ;
  - Kraken spot WS v2 (`ticker` bbo + `trade`) : EUR/USD, PAXG/USD, BTC/EUR, SOL/EUR ;
  - Jupiter lite-api `price/v3` (~2 s, pas de carnet ni de volume par tick) : SOL, JUP, BONK, WIF, RAY, POPCAT, FARTCOIN, PENGU, TRUMP, JTO.
  OKX est bloqué depuis la machine ; pas de flux gratuit temps réel pour actions/indices/forex classique → non inclus (pas de données inventées).
- **Bougies** 15 s et 1 min construites à partir des trades (volume réel → **VWAP réel** 30 min sur Binance/Kraken ; TWAP sur Jupiter). Historique 1 min amorcé via les klines publiques Binance.
- **Stratégies (taguées)** : `obi` (déséquilibre du carnet top 5 > 75 % / < 25 % + flux + tendance), `flow_burst` (flux 5 s > 3× la base 2 min, 70 % dans un sens), `vwap_pullback` (EMA9/21 + contact VWAP/EMA21), `bb_rsi` (clôture hors Bollinger 20/2 + RSI14 < 25 / > 75), `fvg`, `sweep`, `order_block` (SMC sur 1 min). Pas de trade si le range 20 × 15 s < 0,08 %.
- **Exécution simulée** : entrées **limite (maker)** pour vwap_pullback / bb_rsi / fvg / order_block, remplies seulement si un trade **traverse** le prix limite dans les 15 s (sinon annulées) ; entrées **taker** pour obi / flow_burst / sweep (achat à l'ask, vente au bid + 0,01 % de latence). TP en limite (maker, rempli si le prix traverse), stop et sortie temps en taker.
- **Frais** : Binance spot 0,10 % ; Binance perps 0,02 % maker / 0,05 % taker ; Kraken spot 0,25 % / 0,40 % ; DEX Jupiter 0,30 % + slippage taille/(liq/2). PnL affiché **net de frais**.
- **Risque** : 0,75 % du sous-portefeuille par trade (notionnel), stop = 1,5 × ATR(1 min) borné entre 0,3 % et 1 %, objectif = 1,5 × stop, sortie après 10 min, exposition max 20 %, 1 position par marché × stratégie, 20 s de cooldown, **pause à −3 % sur la journée** (jusqu'au lendemain, Paris) et **10 min après 6 pertes de suite**.
- L'ancienne v1 (Jupiter seul, 0 trade) est dans `archive/intensif-v1/`.

## Apprentissage (« Leçons apprises »)
`learn.py`, utilisé par les deux modes. Espérance glissante (60 derniers trades) par **stratégie**, **marché/token** et **heure (Paris)** ; en Mode intensif aussi par **stratégie × marché** et **stratégie × marché × heure** :
- ≥ 10 trades et espérance négative → **taille ÷2** ;
- ≥ 20 trades et espérance négative → **désactivé**, puis **probation** (taille ÷2) après 2 h.
Les pertes sont journalisées avec leurs caractéristiques dans `logs/journal_losses.jsonl`. Le tableau est visible dans l'onglet Intensif.

## Fonctionnement 24/7
- `supervise.sh` relance chaque process s'il s'arrête (desk, server, intensif, ngrok, watchdog).
- `watchdog.sh` (lui-même supervisé) toutes les 60 s : relance `start.sh` (idempotent) ; tue `desk.py` si `heartbeat`/`desk.log` ont plus de 300 s, `intensif.py` si `heartbeat_intensif` > 180 s ; tue `server.py` après 2 échecs HTTP sur `localhost:8787` ; tue ngrok après 3 échecs sur l'URL publique. Journal : `logs/watchdog.log`.
- Dans `desk.py`, un `SIGALRM` coupe tout cycle de plus de 240 s et tout tick Risk de plus de 60 s, recrée la session HTTP et logue l'erreur ; chaque cycle écrit une ligne, même en pause (`active` / `PAUSED …`). Timeouts HTTP (5 s connexion, 10 s lecture).
- ngrok lit son authtoken dans `~/.config/ngrok/ngrok.yml` (pas besoin de variable d'environnement au redémarrage).
- **Limite** : la machine n'a ni cron ni systemd (PID 1 = tini). Après un **redémarrage à froid**, il faut relancer `./start.sh` une fois (une routine Grok Bot peut le faire). Les gels/reprises de la machine sont couverts par le watchdog.

## Sources (recherche stratégie, 10/11/2026)
- BitLogic — VWAP pullback (EMA9 > EMA20, reprise du VWAP, volume > moyenne 10) : https://bitlogic.info/blog/prebuilt-vwap-pullback-bounce-screener/
- Solana Tracker — filtrer le risque de rug, slippage ≤ 1–2 %, prises de profit partielles, « second leg » après plus bas plus haut : https://www.solanatracker.io/blog/how-to-trade-meme-coins
- Quacklington — rug check Solana : liq/FDV, concentration, croissance des holders, risque post-pump : https://www.quacklington.com/learn/solana-rug-checking-guide.html
- SolanaOS STRATEGY.md — croisement EMA9/21, cap de slippage, sorties en tranches, blocage des entrées pump.fun en drawdown : https://github.com/x402agent/SolanaOS/blob/main/STRATEGY.md
- Trojan Chart — EMA 9/21 et VWAP sur memecoins : https://trojanchart.com/guides/moving-averages-rsi-memecoins/
- Smart money / KOL : pas de source gratuite fiable → non implémenté.

## Hypothèses et approximations (à lire)

- **Capital virtuel 1 000 €** par mode depuis la session 2 (session 1 : 10 000 $, archivée).
- **Fill simulé** = priceUsd DexScreener × (1 + slippage), slippage = taille / (liquidité/2) + 0,25 % de frais (impact x·y=k approx.). Même modèle à la sortie, au prix observé (pas au prix du stop : les gaps sont subis).
- **Stop -6 %** calculé et stocké avec l'ordre *avant* l'enregistrement de l'entrée (refus d'entrée sans stop). **Trailing** activé dès que le pic ≥ +12 % ; stop = max(stop initial, pic × 0,94) (6 % sous le plus haut — confirmé par l'utilisateur).
- **LP « brûlée ou verrouillée »** : `lpLockedPct` RugCheck du marché correspondant à la paire DexScreener (sinon moyenne pondérée des marchés).
- **Top 10** : `topHolders` RugCheck en excluant les comptes de pool/AMM/locker identifiés (`markets[].pubkey`, comptes de liquidité, `knownAccounts` AMM/LOCKER) et adresses de burn.
- **Dev** : max(creatorBalance / supply, part d'un top holder détenu par le créateur).
- **Dev rugs passés — APPROXIMATION** : RugCheck n'expose pas d'historique complet gratuit ; flags `rugged`, risques rug / creator history, ou `creatorTokens` marqués rugged. Un dev avec historique non détecté par RugCheck passera.
- **Bundle — APPROXIMATION** : max(somme des avoirs actuels des `insiderNetworks` RugCheck / supply, % des top holders marqués `insider`).
- **Acheteurs uniques — PROXY** : l'API publique DexScreener ne donne que le nombre de transactions d'achat (h1), pas les wallets distincts.
- **Smart wallets — DÉSACTIVÉ** : aucune source gratuite. Poids 0, autres poids renormalisés.

## Pondération Analyst
| Composante | Poids nominal | Poids effectif | Calcul (0–100) |
|---|---:|---:|---|
| Momentum | 20 | 23,5 % | 0,6·lin(Δh1, -20→+40 %) + 0,25·lin(Δm5, -5→+5 %) + 0,15·lin(Δh6, -30→+100 %) |
| Acheteurs uniques (proxy) | 17 | 20 % | log10(achats h1) de 50 → 1500 |
| Ratio achats/ventes | 17 | 20 % | 0,75·lin(B/S h1, 0,8→2,0) + 0,25·lin(B/S m5) |
| Croissance holders | 17 | 20 % | suivi en base : %/h sur ≤3 h (0→15 %/h) dès 10 min d'historique ; sinon holders/h depuis la création (20→800), plafonné à 80 |
| Liquidité / mcap | 14 | 16,5 % | lin(liq/mcap, 0,05→0,25) |
| Smart wallets | 15 | **0 %** | pas de source gratuite |

En mode agressif, les pénalités Filter sont soustraites du score brut (plancher 0).

## Dashboard
`server.py` (stdlib, port 8787) : `/api/all`, `/api/summary`, `/api/agents`, `/api/handoffs`, `/api/kills`, `/api/kills_by_reason`, `/api/scores`, `/api/positions`, `/api/equity`, `/api/activity`, `/api/scout_feed`, `/api/token?mint=`, `/api/ohlcv?pair=&mint=` (GeckoTerminal, repli sur les échantillons de prix du desk), `/api/config`. Accès protégé par jeton (`.access_token`, `?k=` ou cookie). PWA : manifest (standalone, noir), apple-touch-icon. Affiche le profil actif et le déclencheur de chaque trade.

Exposition publique : le quick tunnel cloudflared est installé (`tunnel.sh`, `ENABLE_TUNNEL=1 ./start.sh`) mais **l'egress de cette machine bloque le port 7844** (et les ports non HTTP), donc il ne peut pas se connecter. Le tunnel ngrok (`ngrok.sh`) est le chemin public.
