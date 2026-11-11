# Installer Kairo sur macOS

## Paquet (recommandé)

Apple Silicon : `Kairo-<version>-macos-arm64.dmg`. Intel : `Kairo-<version>-macos-intel.dmg`. Glissez **Kairo** dans Applications. L'app ouvre sa propre fenêtre (pas un onglet du navigateur), une icône dans le Dock et une icône dans la barre des menus.

```bash
curl -fsSL https://raw.githubusercontent.com/businesstradeforex-ui/kairo/main/install.sh | bash
```

L'app est signée ad hoc (elle tourne sur Apple Silicon) mais pas avec un certificat Apple. Gatekeeper peut bloquer le premier lancement.

1. Réglages Système → Confidentialité et sécurité → **Ouvrir quand même**.
2. Ou, dans le Terminal : `xattr -dr com.apple.quarantine /Applications/Kairo.app`
3. Le script d'installation copie l'app dans `~/Applications`. Même commande avec ce chemin si besoin.

Le premier lancement crée `~/Library/Application Support/Kairo` (données et `secret.key`) et affiche l'écran d'IA locale : modèles Ollama déjà là, conseil selon la RAM et le disque libre, téléchargement avec une barre de progression. Le desk papier fonctionne même si vous passez cette étape. Fermer la fenêtre laisse le desk tourner (réglage dans Préférences). **Quitter Kairo** arrête les processus. Le trading réel reste éteint.

Le premier lancement crée `~/Library/Application Support/Kairo` (données et `secret.key`, chmod 700) et ouvre le navigateur. Sans Ollama, LM Studio ou llama.cpp, la page http://127.0.0.1:8787/setup explique comment en brancher un. Le desk papier fonctionne sans modèle.

## Depuis les sources

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
