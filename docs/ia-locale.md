# Connecter une IA locale, de A à Z

L'IA locale **n'est pas** le trader. Les entrées, les stops et les scores viennent du code des six agents, identique au desk d'origine. Le modèle sert à :

- traduire une phrase en **une** action de la liste blanche ;
- rédiger un résumé court à partir de chiffres déjà calculés.

S'il est éteint, le JSON et un petit analyseur de phrases continuent de marcher.

## 1. Choisir un runtime

| Runtime | URL | Variable |
|---|---|---|
| Ollama | `http://127.0.0.1:11434` | `OLLAMA_URL` (défaut) |
| LM Studio | serveur local, souvent `http://127.0.0.1:1234/v1` | `OPENAI_BASE_URL` |
| llama.cpp `llama-server` | souvent `http://127.0.0.1:8080/v1` | `OPENAI_BASE_URL` |
| vLLM, LocalAI, autre compatible OpenAI | leur `/v1` | `OPENAI_BASE_URL` |

`KAIRO_LLM_BACKEND=auto` utilise le serveur OpenAI si `OPENAI_BASE_URL` est défini, sinon Ollama.

## 2. Ollama

```bash
# macOS
brew install ollama && brew services start ollama
ollama pull qwen3:4b
```

Dans l'environnement du desk :

```bash
export OLLAMA_URL=http://127.0.0.1:11434
export KAIRO_LLM_MODEL=qwen3:4b
export OLLAMA_MODEL=qwen3:4b
```

`./install.sh` fait cela. Vérifiez : `curl -s http://127.0.0.1:11434/api/tags`.

L'onglet **Ordres** doit afficher « IA locale en ligne ».

## 3. LM Studio ou llama.cpp

Dans LM Studio : chargez un modèle, démarrez le serveur, activez le mode compatible OpenAI.

```bash
export KAIRO_LLM_BACKEND=openai
export OPENAI_BASE_URL=http://127.0.0.1:1234/v1
export OPENAI_API_KEY=lm-studio
export KAIRO_LLM_MODEL=le-nom-exact-du-modele
```

llama.cpp :

```bash
llama-server -m modele.gguf --port 8080
export OPENAI_BASE_URL=http://127.0.0.1:8080/v1
export OPENAI_API_KEY=none
export KAIRO_LLM_MODEL=local
```

Redémarrez le processus `ai` (`run.py ai` ou `launchctl kickstart -k gui/$(id -u)/com.kairo.ai`).

Le client envoie `temperature: 0` et, pour la traduction d'ordre, `response_format: json_object` (Ollama : `format: json`).

## 4. Donner un ordre

Dans l'onglet Ordres, ou :

```bash
curl -X POST "http://127.0.0.1:8787/api/orders?wait=20" \
  -H "Authorization: Bearer $(cat ~/kairo-data/agent_token.txt)" \
  -H "Content-Type: application/json" \
  -d '{"action":"summary","hours":6}'
```

Phrases reconnues sans modèle : « pause », « reprends », « mode profit », « coupe l'intensif », « liquidité min 20k », « max 6 positions », « stop à 5 % », « résumé des 6 dernières heures ».

## 5. Ce que le modèle n'a pas le droit de faire

Liste blanche : `set_profile`, `set_intensif`, `set_param` (bornes dans `config.OVERRIDABLE`), `reset_params`, `pause_desk`, `resume_desk`, `summary`.

Refusé, même si le modèle le propose : achat ou vente manuelle, wallet, clé, seed, retrait, shell, SQL. La réponse du modèle est revérifiée (`validate` + un indice dans le texte). Le trading réel ne passe **pas** par cette liste : il exige l'opt-in et le mot `CONFIRMER` dans l'interface.

Débit : au plus un appel modèle toutes les `KAIRO_LLM_MIN_INTERVAL_S` secondes (2 par défaut).

## 6. L'assistant distant (propriétaire seulement)

L'espace `/admin` crée un jeton à scopes. L'assistant appelle `POST /api/owner/orders` avec `Authorization: Bearer`. Il peut lire l'état, changer un paramètre autorisé, envoyer un ordre de la liste blanche, et demander `POST /api/owner/ui` (git pull fast-forward du dossier d'interface). Il ne peut pas activer le trading réel à lui seul.

`KAIRO_ADMIN_ALLOWLIST=ip1,ip2` refuse les jetons venus d'ailleurs. Tournez le jeton s'il a fuité : `manage.py revoke-token <id>` ou l'écran propriétaire.
