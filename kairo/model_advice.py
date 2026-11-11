"""Pick a local model from RAM and free disk. Sizes are approximate Ollama downloads, not benchmarks.

Quality order follows the public Local Agent Bench notes in docs/modeles.md:
gemma4:12b on 16 GB, otherwise qwen3:4b. A 32B model is not recommended under 24 GB of RAM.
At least 4 GB of disk must remain free after a download.
"""
CANDIDATES = (
    {"id": "gemma4:12b", "ram_min_gb": 16, "disk_gb": 8.5, "rank": 1,
     "label_fr": "Meilleur choix à 16 Go",
     "why_fr": "Local Agent Bench (oct. 2026) : score 98,3, JSON 100, tool calling 100. Téléchargement Ollama d'environ 8,5 Go."},
    {"id": "qwen3:4b", "ram_min_gb": 8, "disk_gb": 2.8, "rank": 2,
     "label_fr": "Meilleur petit modèle",
     "why_fr": "Même banc : score 92,9, JSON 100, tool calling 100, environ 2,8 Go. Tient sur 8 Go de RAM et laisse de la place sur le disque."},
    {"id": "qwen2.5:7b", "ram_min_gb": 8, "disk_gb": 4.7, "rank": 4,
     "label_fr": "Ancien 7B",
     "why_fr": "Tient en mémoire, mais ce banc lui donne un score JSON de 33. Préférez qwen3:4b."},
    {"id": "qwen2.5:3b", "ram_min_gb": 6, "disk_gb": 2.0, "rank": 5,
     "label_fr": "Très léger",
     "why_fr": "Déjà assez petit pour tourner tout de suite. Moins fiable en JSON que qwen3:4b. Les règles simples marchent sans modèle."},
    {"id": "qwen2.5:32b", "ram_min_gb": 24, "disk_gb": 20.0, "rank": 3,
     "label_fr": "Trop lourd ici",
     "why_fr": "Environ 20 Go de RAM une fois chargé. Sur un MacBook Air 16 Go il va swapper ou refuser de démarrer."},
)
RESERVE_GB = 4.0

def _by_id(name):
    for c in CANDIDATES:
        if c["id"] == name:
            return c
    return None

def fits_ram(model, ram_gb):
    return ram_gb + 0.25 >= model["ram_min_gb"]

def fits_download(model, free_disk_gb):
    return free_disk_gb >= model["disk_gb"] + RESERVE_GB

def recommend(ram_gb, free_disk_gb, installed=()):
    installed = list(installed or [])
    installed_ids = [str(name) for name in installed]
    # Match "qwen2.5:3b" and "qwen2.5:3b-instruct" style tags by prefix before an extra dash after the tag.
    def is_installed(model_id):
        for name in installed_ids:
            if name == model_id or name.startswith(model_id + "-") or name.startswith(model_id + ":"):
                return True
            # ollama tags look like qwen2.5:3b or qwen2.5:3b-q4_K_M sometimes as the name itself
            if name.split()[0] == model_id:
                return True
        return model_id in installed_ids

    ranked = sorted(CANDIDATES, key=lambda m: m["rank"])
    choice = None
    action = "download"
    for model in ranked:
        if not fits_ram(model, ram_gb):
            continue
        if is_installed(model["id"]):
            choice = model
            action = "use_installed"
            break
        if fits_download(model, free_disk_gb):
            choice = model
            action = "download"
            break
    # Prefer a download of a better-ranked model that fits, even if a weaker one is installed.
    for model in ranked:
        if not fits_ram(model, ram_gb):
            continue
        if is_installed(model["id"]):
            continue
        if fits_download(model, free_disk_gb) and (choice is None or model["rank"] < choice["rank"]):
            choice = model
            action = "download"
            break
    notes = []
    for model in CANDIDATES:
        state = "ok"
        if not fits_ram(model, ram_gb):
            state = "ram"
        elif not is_installed(model["id"]) and not fits_download(model, free_disk_gb):
            state = "disk"
        elif is_installed(model["id"]):
            state = "installed"
        notes.append({**{k: model[k] for k in ("id", "ram_min_gb", "disk_gb", "label_fr", "why_fr", "rank")}, "state": state})
    reason = "Aucun modèle conseillé ne tient dans cette machine."
    if choice:
        if action == "download":
            reason = f"{choice['id']} — {choice['why_fr']} Il restera au moins {RESERVE_GB:.0f} Go libres."
        else:
            reason = f"{choice['id']} est déjà installé et tient dans {ram_gb:.0f} Go de RAM. {choice['why_fr']}"
    return {
        "recommended": choice["id"] if choice else None,
        "action": action if choice else "none",
        "reason_fr": reason,
        "models": notes,
        "reserve_gb": RESERVE_GB,
    }
