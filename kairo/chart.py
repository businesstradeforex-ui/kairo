"""Chart confirmation from free 1-minute OHLCV (GeckoTerminal public API). PAPER ONLY.
Implements the documented memecoin pullback entry: EMA9 > EMA21 uptrend, a dip to EMA21 / VWAP,
then a close back above EMA9 and VWAP on above-average volume, with a higher low (no falling knife).
Fail-closed: no candles -> no chart setup."""
import time
from common import get_json

GT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair}/ohlcv/minute?aggregate=1&limit=90&currency=usd&token={mint}"
_cache = {}

def candles(pair, mint, ttl=55):
    k = (pair, mint)
    hit = _cache.get(k)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    d = get_json(GT.format(pair=pair, mint=mint), use_cache=False)
    try:
        rows = sorted(d["data"]["attributes"]["ohlcv_list"], key=lambda r: r[0])
        out = [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in rows]
    except Exception:
        out = None
    _cache[k] = (time.time(), out)
    if len(_cache) > 500:
        for kk in sorted(_cache, key=lambda x: _cache[x][0])[:250]:
            _cache.pop(kk, None)
    return out

def ema(vals, n):
    k = 2 / (n + 1); e = vals[0]; out = []
    for v in vals:
        e = v * k + e * (1 - k); out.append(e)
    return out

def analyze(pair, mint, C=None):
    C = C or {}
    cs = candles(pair, mint)
    if not cs or len(cs) < 30:
        return {"ok": False, "why": "no_candles" if not cs else f"only_{len(cs)}_candles"}
    # GT omits empty minutes; require the last candle to be recent (live tape)
    if time.time() - cs[-1]["t"] > 4 * 60:
        return {"ok": False, "why": "stale_tape"}
    closes = [c["c"] for c in cs]
    e9, e21 = ema(closes, 9), ema(closes, 21)
    pv = sum(((c["h"] + c["l"] + c["c"]) / 3) * c["v"] for c in cs); vv = sum(c["v"] for c in cs)
    vwap = pv / vv if vv else closes[-1]
    last = cs[-1]; prev = cs[-2]
    avg10 = sum(c["v"] for c in cs[-11:-1]) / 10
    recent = cs[-6:-1]                                  # the dip window (5 candles before the trigger)
    dip_low = min(c["l"] for c in recent)
    support = min(e21[-2], vwap)
    touch = C.get("touch_pct", 0.02)
    trend = e9[-1] > e21[-1] and e21[-1] >= e21[-6] * 0.995          # uptrend, slow EMA not falling
    dipped = dip_low <= max(e21[-2], vwap) * (1 + touch)               # pulled back into EMA21/VWAP zone
    held = dip_low >= support * (1 - C.get("max_undercut_pct", 0.04))   # did not collapse through support
    higher_low = dip_low > min(c["l"] for c in cs[-16:-6])              # higher low vs the prior swing
    reclaim = last["c"] > e9[-1] and last["c"] > vwap and last["c"] > last["o"]
    vol_ok = last["v"] >= C.get("vol_mult", 1.0) * avg10 and avg10 > 0
    ext = last["c"] / vwap - 1                                          # extension above VWAP
    not_extended = ext <= C.get("max_ext_vwap", 0.12)
    ok = trend and dipped and held and higher_low and reclaim and vol_ok and not_extended
    why = [n for n, v in (("trend", trend), ("dip", dipped), ("held", held), ("higher_low", higher_low),
                          ("reclaim", reclaim), ("volume", vol_ok), ("not_extended", not_extended)) if not v]
    return {"ok": ok, "why": ",".join(why) or "setup", "ema9": e9[-1], "ema21": e21[-1], "vwap": vwap,
            "ext_vwap_pct": round(ext * 100, 2), "vol_ratio": round(last["v"] / avg10, 2) if avg10 else None,
            "above_vwap": last["c"] > vwap, "trend": trend, "n": len(cs)}
