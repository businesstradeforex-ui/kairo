# Installer Kairo sur macOS

Le desk lui-même est léger. Un MacBook Air M1 suffit. L'IA locale est optionnelle : sans elle, les ordres JSON et les phrases simples (« pause », « mode profit », « liquidité min 20k ») fonctionnent quand même.

1. Installez [Homebrew](https://brew.sh) si besoin.
2. Évitez Bureau, Documents et Téléchargements (macOS y bloque les services). Par exemple `~/src/kairo`.
3. À la racine du dépôt :

```bash
./install.sh                  # modèle par défaut qwen3:4b
./install.sh --model gemma4:12b   # si vous avez 16 Go et plus
./install.sh --no-ollama      # sans IA locale
```

Le script crée `.venv`, le dossier `~/kairo-data` (chmod 700), vous demande le compte **propriétaire** (aucun mot de passe par défaut), et charge des agents launchd `com.kairo.*` plus `caffeinate`.

Ouvrez http://127.0.0.1:8787

## Rester allumé

`caffeinate` empêche la veille tant que la session est ouverte. Sur secteur, capot fermé :

```bash
sudo pmset -c sleep 0 disablesleep 1
# annuler : sudo pmset -c disablesleep 0
```

Activez l'ouverture de session automatique si vous voulez un redémarrage seul. FileVault demandera quand même le mot de passe au boot.

## Commandes

```bash
tail -f ~/kairo-data/logs/desk.log
launchctl kickstart -k gui/$(id -u)/com.kairo.desk
./uninstall.sh
```

Le jeton d'assistant est dans `~/kairo-data/agent_token.txt` (chmod 600). Ne le commitez pas.
