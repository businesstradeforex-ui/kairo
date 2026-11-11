# Oracle Cloud Always Free

Une VM gratuite peut faire tourner le desk 24 h/24. Une carte sert à vérifier l'identité ; rien n'est prélevé tant que vous restez dans Always Free. Passez le compte en Pay As You Go (sans dépense dans les limites gratuites) si Oracle récupère les instances inactives.

1. https://www.oracle.com/cloud/free/ — région proche (Paris, Marseille). Elle ne se change plus ensuite.
2. Compute → Ubuntu 24.04, forme **VM.Standard.A1.Flex** (Ampere), 2 à 4 OCPU et 12 à 24 Go. « Out of capacity » est fréquent : réessayez, ou changez de domaine de disponibilité.
3. Sur la VM :

```bash
sudo apt update && sudo apt install -y python3 python3-venv git curl
git clone https://github.com/businesstradeforex-ui/kairo.git
cd kairo && ./install.sh --model qwen3:4b
```

`qwen3:4b` répond plus vite sans GPU. `gemma4:12b` ou `qwen3:30b-a3b` seulement si la RAM le permet (voir [le classement](../modeles.md)).

4. Ne ouvrez pas le port 8787 dans le pare-feu Oracle. Le serveur reste sur `127.0.0.1`. Exposez-le avec un tunnel ([exposition](../exposition.md)).

5. `sudo systemctl status kairo`
