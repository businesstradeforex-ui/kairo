"""'Learn from mistakes' (PAPER ONLY). Rolling expectancy per setup / token / hour (Paris).
A key with >= MIN_N trades in the rolling window and negative expectancy is DISABLED for PROBATION_S,
then re-allowed at half size (so it can prove itself again). 10 <= n < MIN_N with negative expectancy
=> size x0.5 (down-weight). Used by Mode intensif and Mode profit."""
import datetime, json

MIN_N = 20
SOFT_N = 10
WINDOW = 60          # last 60 trades per key
PROBATION_S = 2 * 3600

def _hour(ts):
    try:
        return datetime.datetime.fromisoformat(ts).astimezone().hour
    except Exception:
        return None

def keys_for(setup, token, ts, combo=False):
    h = _hour(ts) if ts else datetime.datetime.now().astimezone().hour
    ks = [f"setup:{s}" for s in (setup or "").split(",") if s and not s.startswith("signal_")] or ["setup:none"]
    ks = ks + [f"token:{token}", f"hour:{h:02d}"]
    if combo:   # strategy x market x hour (Mode intensif)
        ks += [f"combo:{setup}|{token}", f"combo:{setup}|{token}|{h:02d}"]
    return ks

def compute(trades):
    """trades: list of dicts {setup, token, ts (exit), pnl, cost}. Returns {key: stats}."""
    by = {}
    for t in trades:
        for k in keys_for(t.get("setup"), t.get("token"), t.get("entry_ts") or t.get("ts"), t.get("combo", False)):
            by.setdefault(k, []).append(t)
    out = {}
    for k, arr in by.items():
        arr = arr[-WINDOW:]
        n = len(arr); wins = sum(1 for t in arr if t["pnl"] > 0)
        exp = sum(t["pnl"] for t in arr) / n
        exp_pct = sum((t["pnl"] / t["cost"] * 100) if t.get("cost") else 0 for t in arr) / n
        if n >= MIN_N and exp < 0:
            status = "disabled"
        elif n >= SOFT_N and exp < 0:
            status = "downweight"
        else:
            status = "ok"
        out[k] = {"key": k, "n": n, "wins": wins, "win_rate": wins / n * 100, "expectancy": exp, "expectancy_pct": exp_pct,
                  "pnl": sum(t["pnl"] for t in arr), "status": status}
    return out

def refresh(con, trades, now_iso):
    """Persist lessons; keep disabled_since for probation."""
    from common import kv_get, kv_set
    prev = kv_get(con, "lessons", {}) or {}
    st = compute(trades)
    for k, v in st.items():
        p = prev.get(k) or {}
        if v["status"] == "disabled":
            v["disabled_since"] = p.get("disabled_since") or now_iso
        # probation: a key disabled for > PROBATION_S comes back at half size until its stats turn positive
        if v["status"] == "disabled" and p.get("disabled_since"):
            try:
                age = datetime.datetime.now().timestamp() - datetime.datetime.fromisoformat(p["disabled_since"]).timestamp()
            except Exception:
                age = 0
            if age > PROBATION_S:
                v["status"] = "probation"; v["disabled_since"] = p["disabled_since"]
    kv_set(con, "lessons", st)
    return st

def size_mult(lessons, setup, token, ts=None, combo=False):
    """0 => blocked, 0.5 => down-weighted, 1 => normal. Returns (mult, reasons)."""
    m, why = 1.0, []
    for k in keys_for(setup, token, ts, combo):
        s = (lessons or {}).get(k)
        if not s:
            continue
        if s["status"] == "disabled":
            return 0.0, [k]
        if s["status"] in ("downweight", "probation"):
            m = min(m, 0.5); why.append(k)
    return m, why

LABEL_FR = {"setup": "Stratégie", "token": "Marché", "hour": "Heure", "combo": "Stratégie × marché"}

def lessons_fr(lessons, sym=None, limit=30):
    """French rows for the dashboard 'Leçons apprises'."""
    rows = []
    for k, s in (lessons or {}).items():
        kind, val = k.split(":", 1)
        if kind == "token" and sym:
            val = sym.get(val, val[:6])
        if kind == "hour":
            val = f"{val} h (Paris)"
        if kind == "combo":
            parts = val.split("|")
            if len(parts) == 3:
                parts[2] = parts[2] + " h"
            val = " × ".join(parts)
        st = {"disabled": "désactivé", "downweight": "taille ÷2", "probation": "en probation (taille ÷2)", "ok": "ok"}[s["status"]]
        rows.append({"kind": LABEL_FR.get(kind, kind), "value": val, "n": s["n"], "win_rate": round(s["win_rate"], 1),
                     "expectancy_pct": round(s["expectancy_pct"], 2), "pnl": s["pnl"], "status": s["status"], "status_fr": st})
    rows.sort(key=lambda r: ({"disabled": 0, "probation": 1, "downweight": 2, "ok": 3}[r["status"]], -r["n"]))
    return rows[:limit]
