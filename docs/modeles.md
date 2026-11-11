# Classement des modèles locaux pour Kairo

Kairo n'a pas été mesuré modèle par modèle dans ce dépôt : **aucun chiffre ci-dessous n'est un benchmark Kairo inventé**. Les scores viennent de bancs publics, cités, et ils mesurent des tâches d'agent plus dures qu'un ordre Kairo (une seule action JSON, plus un analyseur de secours).

Ce que Kairo demande vraiment au modèle : suivre une consigne courte, répondre en JSON, ne pas inventer d'action. La vitesse et la RAM comptent parce que la machine fait aussi tourner le desk.

## Sources

1. **Local Agent Bench**, résultats v0.1.4, scoring v3, octobre 2026 (page résultats datée autour du 9 novembre 2026). Quants Q4_K_M, Ollama, hôtes NVIDIA RTX 3090. Un modèle n'est dans un palier 8 / 16 / 24 Go que si la VRAM mesurée à **contexte 32K, cache KV inclus** (`ollama ps`) tient dans ce palier. Les sous-scores cités sont ceux du tableau : JSON, schéma, tool, multi-step. La VRAM marquée « not measured » sur certaines lignes est recopiée telle quelle : on ne l'invente pas. Les tok/s ne sont **pas** comparés d'un hôte à l'autre (le banc le dit).
   https://localagentbench.com/results/
2. **JD Hodges**, « I Tested 13 Local LLMs on Tool Calling » (2026) : un banc personnel d'environ 40 vérifications (8 cas × 5 axes), pas un standard. Utile pour l'ordre de grandeur mémoire de Qwen3.5 4B, pas pour départager finement les gros modèles.
   https://www.jdhodges.com/blog/local-llms-on-tool-calling-2026-pt1-local-lm/

Les prompts Kairo font quelques centaines de tokens, pas 32K. Une VRAM « à 32K » est donc un majorant.

## Tableau

Les scores sont le score total Local Agent Bench sauf mention. « JSON » et « Tool » sont les sous-scores de ce banc (sur 100).

| Modèle Ollama | Palier du banc | Score | JSON | Tool | RAM / VRAM annoncée par la source | Pour Kairo |
|---|---|---:|---:|---:|---|---|
| `qwen3:4b` | 8 Go | 92.9 | 100 | 100 | 7.6 Go à 32K (mesuré) | Défaut. Tient sur 8 Go si le contexte reste court. JSON et tool au plafond de ce banc. |
| `gemma4:e4b` | 8 Go | 94.7 | 99 | 100 | VRAM **non mesurée** sur cette ligne | Meilleur score du palier 8 Go, à confirmer chez vous avec `ollama ps`. |
| `qwen2.5:7b` | 8 Go | 58.6 | 33 | 100 | 6.6 Go à 32K | Ancien défaut du desk. Faible en JSON sur ce banc. Gardez-le seulement si vous n'utilisez que les règles fixes. |
| `llama3.2:3b` | 8 Go | 49.8 | 91 | 93 | 6.0 Go à 32K | Trop juste en enchaînement (multi-step 18 sur ce banc). |
| `gemma4:12b` | 16 Go | 98.3 | 100 | 100 | VRAM **non mesurée** | **Meilleur choix global** si la machine a 16 Go. |
| `gpt-oss:20b` | 16 Go | 93.4 | 100 | 100 | 12 Go à 32K (mesuré) | Solide, un peu derrière Gemma 4 12B sur ce banc. |
| `qwen3.5:9b` | 16 Go | 90.6 | 100 | 100 | 6.7 Go à 32K (mesuré) | Bon rapport place / JSON. Le banc le classe sous Gemma 4 12B. |
| `qwen3:14b` | 16 Go | 90.6 | 100 | 100 | 14 Go à 32K | Correct, plus lourd que `qwen3.5:9b` pour le même score total. |
| `gemma4:26b` | 24 Go | 99.7 | 100 | 100 | VRAM **non mesurée** | Le plus haut score publié sur ce banc dans le palier 24 Go. |
| `qwen3:30b-a3b` | 24 Go | 98.5 | 100 | 100 | 21 Go à 32K (mesuré) | MoE : beaucoup de paramètres, peu d'actifs. Choix 32 Go quand on veut un chiffre de VRAM réel. |
| `qwen3.5:27b` | 24 Go | 95.0 | 99 | 100 | 18 Go (mesuré) | Très bon, sous les deux précédents sur ce banc. |
| `llama3.3:70b` (Q4, série A100 du même banc, pas le palier 3090) | gros GPU | 68.35 sur la série A100 v3, 3 essais | — | — | ne tient pas dans 24 Go | Le banc A100 (autre série, ne pas mélanger les scores) ne le place pas devant Qwen3 32B Q8. Pas un choix « petit Mac ». |

Hors de ce tableau, le billet Hodges donne pour **Qwen3.5 4B** 97,5 % de réussite sur **son** jeu (3,4 Go, 48 tok/s **sur sa machine**). Ce n'est pas le même protocole que Local Agent Bench. Si `qwen3.5:4b` existe dans votre Ollama et que `qwen3:4b` est juste en RAM, c'est un candidat 8 Go crédible, à vérifier avec vos propres ordres français.

Phi-4 et Gemma 3 4B sont listés par le banc comme **sans** appel d'outil natif dans le template Ollama testé (`n/a`). On ne les recommande pas pour cet usage.

DeepSeek-R1 distillé (8B / 14B) a un sous-score tool à 0 sur ce banc : le modèle raisonne au lieu d'émettre l'action. Mauvais exécuteur d'ordres Kairo.

## Choix par machine

| Machine | Modèle | Pourquoi |
|---|---|---|
| **8 Go** | `qwen3:4b` | Seul modèle du palier 8 Go avec JSON 100, tool 100 **et** une VRAM mesurée (7.6 Go à 32K). Nos prompts sont plus courts. `gemma4:e4b` a un meilleur score (94.7) mais sa VRAM n'est pas publiée sur cette ligne. |
| **16 Go** | `gemma4:12b` | Score 98.3, JSON 100, tool 100. |
| **32 Go et plus** | `qwen3:30b-a3b` ou `gemma4:26b` | 98.5 avec 21 Go mesurés, ou 99.7 si `gemma4:26b` tient (VRAM non mesurée sur la ligne). |
| **Meilleur global** | **`gemma4:12b`** | Meilleur compromis publié : très haut sur l'ordre et le JSON, palier 16 Go, assez rapide pour une phrase. Le desk n'a pas besoin d'un 70B. |

Installez avec `./install.sh --model gemma4:12b` ou `ollama pull gemma4:12b`, puis `KAIRO_LLM_MODEL`.

Le défaut du dépôt reste `qwen3:4b` pour qu'une machine 8 Go démarre sans échange mémoire.

## Comment lire un échec

Si l'onglet Ordres dit « ordre ambigu » ou « réponse inexploitable », le modèle a parlé à côté et **rien n'a été exécuté**. Reformulez, ou envoyez le JSON. Les décisions de trading, elles, ne dépendent pas de ce modèle : voir [moteur.md](moteur.md).
