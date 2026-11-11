"""Bayesian down-weight for mode turbo.

Each losing setup is stored with a few features. A bucket needs enough samples
before it can shrink or block size. Nothing here sends a live order.
"""
import json, os

PRIOR_A = 2.0
PRIOR_B = 2.0
MIN_N = 8
BLOCK_N = 20
BLOCK_P = 0.35
DOWN_P = 0.45

def bucket(features):
    liq = float(features.get("liq") or 0)
    if liq < 20_000:
        band = "liq_low"
    elif liq < 80_000:
        band = "liq_mid"
    else:
        band = "liq_high"
    setup = (features.get("setup") or "score").split(",")[0][:40]
    return f"{setup}|{band}"

def posterior(wins, n, a=PRIOR_A, b=PRIOR_B):
    n = max(0, int(n))
    wins = max(0, min(int(wins), n))
    return (wins + a) / (n + a + b)

def decide(wins, n):
    """Return (status, size multiplier)."""
    n = int(n)
    if n < MIN_N:
        return "watch", 1.0
    p = posterior(wins, n)
    if n >= BLOCK_N and p < BLOCK_P:
        return "block", 0.0
    if p < DOWN_P:
        return "down", 0.5
    return "ok", 1.0

def update(stats, key, win):
    row = dict(stats.get(key) or {"n": 0, "wins": 0})
    row["n"] = int(row["n"]) + 1
    row["wins"] = int(row["wins"]) + (1 if win else 0)
    status, mult = decide(row["wins"], row["n"])
    row["status"] = status
    row["mult"] = mult
    row["p"] = round(posterior(row["wins"], row["n"]), 4)
    stats[key] = row
    return stats

def multiplier(stats, features):
    key = bucket(features)
    row = (stats or {}).get(key)
    if not row:
        return 1.0, key, "watch"
    status, mult = decide(row.get("wins", 0), row.get("n", 0))
    return mult, key, status

def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save(path, stats):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=1)
    os.replace(tmp, path)

def journal_loss(path, features):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(features, default=str) + "\n")
