"""Stage 3 - ANALYST. Input: Filter survivors. Output: scored candidates.
Pass if score >= profile threshold, or (agressif) a signal fires above signal_min_score.
Components (each 0-100). Smart wallets has NO free data source -> weight 0, rest renormalized.
Filter penalties (agressif) are subtracted from the raw score."""
import math, time, json
from common import jsonl
from config import cfg

NOMINAL = {"momentum": 20, "unique_buyers": 17, "buy_sell": 17, "holder_growth": 17, "liq_mcap": 14, "smart_wallets": 15}
SMART_WALLETS_AVAILABLE = False
W = dict(NOMINAL)
if not SMART_WALLETS_AVAILABLE:
    W["smart_wallets"] = 0
_tot = sum(W.values())
WEIGHTS = {k: v / _tot for k, v in W.items()}  # effective weights, sum to 1

def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))

def lin(x, a, b):
    """map a->0, b->100 linearly, clamped"""
    return clamp((x - a) / (b - a) * 100.0) if b != a else 0.0

def momentum(c):
    ch = c["chg"]; m5 = float(ch.get("m5") or 0); h1 = float(ch.get("h1") or 0); h6 = float(ch.get("h6") or 0)
    s = 0.6 * lin(h1, -20, 40) + 0.25 * lin(m5, -5, 5) + 0.15 * lin(h6, -30, 100)
    return clamp(s)

def unique_buyers(c):
    # PROXY: DexScreener public API exposes buy tx counts, not distinct buyer wallets.
    b1 = float((c["txns"].get("h1") or {}).get("buys") or 0)
    return clamp(lin(math.log10(b1 + 1), math.log10(50), math.log10(1500)))

def buy_sell(c):
    t = c["txns"].get("h1") or {}; b = float(t.get("buys") or 0); s = float(t.get("sells") or 0)
    r = b / s if s > 0 else (3.0 if b > 0 else 0)
    vt = c["txns"].get("m5") or {}; b5 = float(vt.get("buys") or 0); s5 = float(vt.get("sells") or 0)
    r5 = b5 / s5 if s5 > 0 else (3.0 if b5 > 0 else 1.0)
    return clamp(0.75 * lin(r, 0.8, 2.0) + 0.25 * lin(r5, 0.8, 2.0))

def holder_growth(con, c):
    h = (c.get("facts") or {}).get("holders")
    if not h:
        return 0.0, "no_holder_data"
    con.execute("INSERT INTO holders(mint, ts_epoch, holders) VALUES(?,?,?)", (c["mint"], time.time(), int(h)))
    con.commit()
    rows = con.execute("SELECT ts_epoch, holders FROM holders WHERE mint=? AND ts_epoch > ? ORDER BY ts_epoch",
                       (c["mint"], time.time() - 3 * 3600)).fetchall()
    first = rows[0]
    dt_h = (time.time() - first["ts_epoch"]) / 3600
    if len(rows) >= 2 and dt_h >= 10 / 60:
        pct_per_h = (h - first["holders"]) / max(first["holders"], 1) * 100 / dt_h
        return lin(pct_per_h, 0, 15), f"tracked {pct_per_h:.1f}%/h over {dt_h*60:.0f}m"
    rate = h / max(c["age_h"], 0.5)
    return min(80.0, lin(rate, 20, 800)), f"lifetime {rate:.0f} holders/h (no history yet, capped 80)"

def liq_mcap(c):
    r = c["liq"] / c["mcap"] if c["mcap"] else 0
    return lin(r, 0.05, 0.25)

def detect_signals(con, c):
    """Fast entry signals from 5m tape, volume spike, and recent-high breakout."""
    out = []
    ch = c.get("chg") or {}
    tx = c.get("txns") or {}
    vol = c.get("vol") or {}
    m5 = float(ch.get("m5") or 0)
    t5 = tx.get("m5") or {}
    b5 = float(t5.get("buys") or 0); s5 = float(t5.get("sells") or 0)
    r5 = b5 / s5 if s5 > 0 else (3.0 if b5 >= 3 else 0)
    if m5 >= 3.0 and r5 >= 1.3 and (b5 + s5) >= 6:
        out.append("signal_momentum")
    v5 = float(vol.get("m5") or 0)
    v1 = float(vol.get("h1") or 0)
    avg5 = v1 / 12.0 if v1 else 0
    if v5 >= 1_500 and avg5 > 0 and v5 >= 2.5 * avg5:
        out.append("signal_volume_spike")
    try:
        rows = con.execute(
            "SELECT price FROM price_samples WHERE pair=? AND ts_epoch > ? ORDER BY ts_epoch",
            (c["pair"], time.time() - 3600),
        ).fetchall()
    except Exception:
        rows = []
    if len(rows) >= 5 and c.get("price"):
        prices = [float(r["price"] if hasattr(r, "keys") else r[0]) for r in rows]
        hi = max(prices[:-1]) if len(prices) > 1 else prices[0]
        if hi > 0 and c["price"] >= hi * 1.01 and m5 > 0:
            out.append("signal_breakout")
    return out

def _bs5(c):
    t5 = (c.get("txns") or {}).get("m5") or {}
    b5 = float(t5.get("buys") or 0); s5 = float(t5.get("sells") or 0)
    r5 = b5 / s5 if s5 > 0 else (3.0 if b5 >= 3 else 0)
    return r5, b5 + s5

def pullback_setup(c, A):
    """Consolidation / pullback after 1h strength: 5m in [-3%, +8%], 1h up, 5m buy/sell > 1.2."""
    ch = c.get("chg") or {}
    m5 = float(ch.get("m5") or 0); h1 = float(ch.get("h1") or 0)
    r5, n5 = _bs5(c)
    return (A.get("pullback_m5_min", -3.0) <= m5 <= A.get("pullback_m5_max", 8.0)
            and h1 >= A.get("pullback_h1_min", 5.0)
            and r5 >= A.get("pullback_bs5_min", 1.2)
            and n5 >= 6)

def confirmed_breakout(con, c, cycle, A):
    """A breakout of the recent high must hold for `breakout_confirm_cycles` later cycles."""
    from common import kv_get, kv_set
    pending = kv_get(con, "breakout_watch", {}) or {}
    sigs = detect_signals(con, c)
    is_bo = "signal_breakout" in sigs
    mint = c["mint"]
    need = int(A.get("breakout_confirm_cycles") or 1)
    ok = False
    if is_bo and c.get("price"):
        prev = pending.get(mint)
        if prev and cycle - prev.get("cycle", cycle) >= need and c["price"] >= prev.get("high", c["price"]) * 0.998:
            ok = True
        high = max(c["price"], (prev or {}).get("high") or 0)
        pending[mint] = {"cycle": cycle, "high": high, "price": c["price"]}
    else:
        pending.pop(mint, None)
    # prune stale
    pending = {k: v for k, v in pending.items() if cycle - v.get("cycle", 0) <= 8}
    kv_set(con, "breakout_watch", pending)
    return ok

def run(cycle, con, survivors):
    A = cfg()["analyst"]
    # record a price tick so breakout signals can form on later cycles
    now = time.time()
    for c in survivors:
        if c.get("price") and c.get("pair"):
            try:
                con.execute("INSERT INTO price_samples VALUES(?,?,?)", (c["pair"], now, c["price"]))
            except Exception:
                pass
    scored, passed = [], []
    chart_budget = [int(A.get("chart_calls_per_cycle") or 0)]
    # chart calls are rate-limited (GeckoTerminal ~10/min): spend them on the best tape first
    survivors = sorted(survivors, key=lambda x: -float(((x.get("txns") or {}).get("h1") or {}).get("buys") or 0))
    for c in survivors:
        hg, hg_note = holder_growth(con, c)
        comp = {"momentum": round(momentum(c), 1), "unique_buyers": round(unique_buyers(c), 1),
                "buy_sell": round(buy_sell(c), 1), "holder_growth": round(hg, 1),
                "liq_mcap": round(liq_mcap(c), 1), "smart_wallets": 0.0}
        raw = sum(comp[k] * WEIGHTS[k] for k in WEIGHTS)
        penalty = float(c.get("penalty_pts") or 0)
        score = round(clamp(raw - penalty), 1)
        sigs = detect_signals(con, c) if A.get("signals_enabled") else []
        triggers = []
        if A.get("require_setup"):
            pb = pullback_setup(c, A)
            bo = confirmed_breakout(con, c, cycle, A)
            r5, n5 = _bs5(c)
            t1 = (c.get("txns") or {}).get("h1") or {}
            pressure = r5 >= A.get("bs5_min", 1.1) and n5 >= 6 and float(t1.get("buys") or 0) > float(t1.get("sells") or 0)
            score_ok = score >= A["pass_score"] or (bool(sigs) and score >= A.get("signal_min_score", 0))
            ch = None
            if A.get("chart_confirm") and score_ok and pressure and chart_budget[0] > 0:
                chart_budget[0] -= 1
                import chart
                ch = chart.analyze(c["pair"], c["mint"], A.get("chart") or {})
            chart_pb = bool(ch and ch.get("ok"))
            chart_bo = bool(bo and ch and ch.get("trend") and ch.get("above_vwap") and ch.get("ext_vwap_pct", 99) <= (A.get("chart") or {}).get("max_ext_vwap", 0.12) * 100)
            if A.get("chart_confirm"):
                setup = chart_pb or chart_bo
                if chart_pb: triggers.append("setup_ema_vwap_pullback")
                if chart_bo: triggers.append("setup_breakout")
            else:
                setup = bool(pb or bo)
                if pb: triggers.append("setup_pullback")
                if bo: triggers.append("setup_breakout")
            qualifies = setup and score_ok and pressure
            if qualifies:
                if score >= A["pass_score"]:
                    triggers.insert(0, "score")
                triggers.extend(s_ for s_ in sigs if s_ not in triggers)
            ok = bool(qualifies)
            if not qualifies:
                triggers = [x for x in triggers if x.startswith("setup_")]
            c["chart"] = ch
            c["gate"] = {"score_ok": score_ok, "pressure": pressure, "bs5": round(r5, 2), "dex_pullback": pb, "breakout": bo,
                         "chart": (ch or {}).get("why") if ch else ("skipped" if not (score_ok and pressure) else "budget")}
        else:
            if score >= A["pass_score"]:
                triggers.append("score")
            if sigs and score >= A.get("signal_min_score", 0):
                triggers.extend(sigs)
            ok = bool(triggers)
        rec = {**c, "score": score, "score_raw": round(raw, 1), "components": comp, "holder_note": hg_note,
               "passed": ok, "triggers": triggers, "penalties": c.get("penalties") or []}
        scored.append(rec)
        payload = {**comp, "gate": c.get("gate"), "chart": c.get("chart"), "holder_note": hg_note, "penalty": penalty, "triggers": triggers,
                   "penalties": c.get("penalties") or [], "score_raw": round(raw, 1)}
        con.execute("INSERT INTO scores VALUES(?,?,?,?,?,?,?,?)",
                    (cycle, rec.get("ts") or "", c["mint"], c["pair"], c["symbol"], score, int(ok), json.dumps(payload)))
        jsonl("analyst", {"cycle": cycle, "mint": c["mint"], "pair": c["pair"], "symbol": c["symbol"], "score": score,
                          "score_raw": round(raw, 1), "passed": ok, "components": comp, "holder_note": hg_note,
                          "weights": WEIGHTS, "triggers": triggers, "penalty": penalty, "gate": c.get("gate"), "chart": c.get("chart")})
        if ok:
            passed.append(rec)
    con.commit()
    return scored, passed
