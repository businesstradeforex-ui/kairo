# Le moteur est déterministe

Les décisions de trading viennent du **code des agents**, pas du modèle local.

Scout, Filter, Analyst, Executor, Risk et Logger sont le desk d'origine, avec les mêmes profils et les mêmes paramètres :

- **strict** — seuil 70, fail-closed, 8 % fixe, pas de signal rapide.
- **agressif** — seuil 45, signal dès 28, liquidité plancher 15 000 $, jusqu'à 10 positions.
- **profit** (défaut) — seuil 60, filtre pumpswap &lt; 3 h, slippage estimé ≤ 1,5 %, 6 positions, sorties par tiers, pause après 3 pertes, coupe-circuit −15 % sur la journée.
- **intensif** — sous-portefeuille séparé, flux publics Binance / Kraken / Jupiter, stratégies taguées (`obi`, `flow_burst`, `vwap_pullback`, `bb_rsi`, `fvg`, `sweep`, `order_block`). Papier. Sur une install multi-comptes, ce processus suit le dossier du propriétaire pour ne pas ouvrir un websocket par utilisateur.

`learn.py` est inchangé : 10 trades à espérance négative → taille ÷2 ; 20 → coupure, puis probation après 2 h.

Deux choses seulement ont été ajoutées autour du moteur, sans changer les formules :

- le dossier de données peut changer par compte (`bind_data_dir`), pour que les portefeuilles soient isolés ;
- un fichier `control.json` applique un changement de capital ou une remise à zéro au début du cycle.

`KAIRO_MULTIUSER=0` relance `desk.py` sur un seul dossier, comme le desk d'origine (timing du cycle compris). En multi-comptes, `userdesk.py` appelle la **même** fonction `desk.run_cycle` pour chaque compte, l'un après l'autre. Les règles sont les mêmes ; l'horloge entre deux comptes n'est pas celle d'un desk seul, parce que les comptes ne partagent pas un portefeuille.

Les prix restent ceux de DexScreener. Le capital de départ (1 000 € par défaut, ou celui choisi) est converti en USD avec le même helper EUR/USD (ECB via frankfurter, repli, puis 1,08). Rien de tout cela n'est « décidé » par l'IA locale.

L'historique rédigé du desk (hypothèses, pondérations, session) est dans `docs/historique/`.
