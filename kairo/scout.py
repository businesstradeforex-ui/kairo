"""Stage 1 - SCOUT. Output: list of candidate dicts (DexScreener pair snapshot).
Window and source volume come from the active profile (strict or agressif)."""
import time
from common import get_json, jsonl
from config import cfg

DS = "https://api.dexscreener.com"
SEARCH_TERMS = ["pump", "pumpswap", "bonk", "letsbonk", "raydium", "meteora", "solana", "SOL", "moon", "inu",
                "cat", "dog", "pepe", "ai", "trump", "frog", "meme", "coin", "elon", "baby", "wif", "chad",
                "based", "grok", "x", "token", "the", "official", "launch", "bags", "believe", "jup", "usdc",
                "penguin", "monkey", "ape", "bull", "bear", "gold", "king", "god", "world", "dao", "agent", "gpt", "musk",
                "fart", "shib", "doge", "kitty", "panda", "fish", "rocket", "mars", "punk", "rich", "money", "alpha", "100x",
                "boop", "heaven", "daos", "moonshot", "jupiter", "orca", "wojak", "troll", "sigma", "giga", "anime"]
JUP_PATHS = ("toptrending/1h", "toptraded/1h", "toporganicscore/1h", "toptrending/6h", "toptraded/6h", "toptrending/24h")

def _collect_mints(cycle, S):
    mints = set()
    paths = ["/token-profiles/latest/v1", "/token-boosts/latest/v1", "/token-boosts/top/v1",
             "/community-takeovers/latest/v1", "/ads/latest/v1"]
    if S.get("concurrent"):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            payloads = list(pool.map(lambda p: get_json(DS + p), paths))
    else:
        payloads = [get_json(DS + p) for p in paths]
    for d in payloads:
        for x in d or []:
            if isinstance(x, dict) and x.get("chainId") == "solana" and x.get("tokenAddress"):
                mints.add(x["tokenAddress"])
    n = len(SEARCH_TERMS); k = max(1, int(S["search_terms_per_cycle"]))
    start = (cycle * k) % n
    terms = [SEARCH_TERMS[(start + i) % n] for i in range(k)]
    for q in terms:
        d = get_json(DS + "/latest/dex/search", params={"q": q})
        for p in (d or {}).get("pairs") or []:
            if p.get("chainId") == "solana":
                mints.add(p["baseToken"]["address"])
    # discovery supplement (mint list only; all metrics still come from DexScreener): GeckoTerminal public API
    gt = "https://api.geckoterminal.com/api/v2/networks/solana"
    gt_jobs = [("/new_pools", 1), ("/new_pools", 2), ("/new_pools", 3), ("/trending_pools?duration=1h", 1), ("/trending_pools?duration=1h", 2),
               ("/trending_pools?duration=6h", 1), ("/trending_pools?duration=6h", 2), ("/trending_pools?duration=24h", 1),
               ("/pools?sort=h24_volume_usd_desc", 1), ("/pools?sort=h24_tx_count_desc", 1)]
    n_gt = max(0, int(S["gt_calls_per_cycle"]))
    for path, pg in [gt_jobs[(cycle * max(n_gt, 1) + i) % len(gt_jobs)] for i in range(n_gt)]:
        sep = "&" if "?" in path else "?"
        d = get_json(f"{gt}{path}{sep}page={pg}")
        for x in (d or {}).get("data") or []:
            try:
                tid = x["relationships"]["base_token"]["data"]["id"]
                if tid.startswith("solana_"):
                    mints.add(tid[7:])
            except Exception:
                pass
    # discovery supplement 2: Jupiter public token lists (mint list only)
    n_jup = max(0, int(S["jup_calls_per_cycle"]))
    for i, path in enumerate(JUP_PATHS):
        if i >= n_jup:
            break
        # rotate which Jupiter lists we hit so we still cover them over cycles
        path = JUP_PATHS[(cycle + i) % len(JUP_PATHS)]
        d = get_json(f"https://lite-api.jup.ag/tokens/v2/{path}?limit=100")
        for x in d or []:
            if isinstance(x, dict) and x.get("id"): mints.add(x["id"])
    if n_jup >= 3 and cycle % 2 == 0:
        d = get_json("https://lite-api.jup.ag/tokens/v2/recent")
        for x in d or []:
            if isinstance(x, dict) and x.get("id"): mints.add(x["id"])
    mints -= {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY9NBvXBvyHB4ziM"}
    return mints

def fetch_pairs_for_mints(mints):
    pairs = []
    mints = list(mints)
    for i in range(0, len(mints), 30):
        d = get_json(f"{DS}/tokens/v1/solana/" + ",".join(mints[i:i + 30]))
        if isinstance(d, list):
            pairs += d
    return pairs

WATCH = {}  # mint -> last time it was in (or near) the window

def run(cycle):
    S = cfg()["scout"]
    AGE_MIN_H, AGE_MAX_H = S["age_min_h"], S["age_max_h"]
    MCAP_MIN, MCAP_MAX = S["mcap_min"], S["mcap_max"]
    mints = _collect_mints(cycle, S)
    found = len(mints)
    now = time.time()
    for m, t in list(WATCH.items()):
        if now - t > S["watch_hours"] * 3600: WATCH.pop(m)
    mints |= set(WATCH)
    pairs = fetch_pairs_for_mints(mints)
    best = {}
    for p in pairs:
        if p.get("chainId") != "solana":
            continue
        m = p["baseToken"]["address"]
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if m not in best or liq > ((best[m].get("liquidity") or {}).get("usd") or 0):
            best[m] = p  # main (deepest) pair per token
    now_ms = time.time() * 1000
    out = []
    for m, p in best.items():
        created = p.get("pairCreatedAt")
        if not created:
            continue
        age_h = (now_ms - created) / 3.6e6
        mcap = p.get("marketCap") or p.get("fdv") or 0
        if age_h <= AGE_MAX_H and mcap >= min(30_000, MCAP_MIN):
            WATCH[m] = time.time()  # young & growing: keep watching across cycles
        if not (AGE_MIN_H <= age_h <= AGE_MAX_H and MCAP_MIN <= mcap <= MCAP_MAX):
            continue
        tx = p.get("txns") or {}
        c = {
            "mint": m, "pair": p["pairAddress"], "symbol": p["baseToken"].get("symbol"), "dex": p.get("dexId"),
            "age_h": round(age_h, 3), "mcap": mcap, "liq": (p.get("liquidity") or {}).get("usd") or 0,
            "price": float(p.get("priceUsd") or 0), "vol": p.get("volume") or {}, "chg": p.get("priceChange") or {},
            "txns": tx, "url": p.get("url"), "icon": (p.get("info") or {}).get("imageUrl"), "fdv": p.get("fdv"),
        }
        out.append(c)
        jsonl("scout", {"cycle": cycle, **c})
    return out, {"mints_seen": len(mints), "new_discovered": found, "watchlist": len(WATCH), "pairs_fetched": len(pairs)}
