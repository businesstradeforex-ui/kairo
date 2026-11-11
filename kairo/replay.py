"""Replay recorded session-1 chart rows. Not a tick tape.

Each row in backtest_chart.json is a real archived trade label (symbol, pnl, why).
Agressif takes every row. Turbo takes a row only when the learner still allows
that feature bucket, then learns from the outcome. No fills are invented.
"""
import json, os
from learner import decide, multiplier, update

def load_rows(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    out = []
    for r in rows:
        pnl = r.get("pnl")
        if pnl is None:
            continue
        out.append({
            "symbol": r.get("symbol") or "?",
            "pnl": float(pnl),
            "setup": "chart_ok" if r.get("chart_ok") else "chart_fail",
            "liq": 50_000 if r.get("chart_ok") else 15_000,
            "why": r.get("why") or "",
        })
    return out

def run(rows):
    agressif = {"n": 0, "wins": 0, "pnl": 0.0}
    turbo = {"n": 0, "wins": 0, "pnl": 0.0, "raw_pnl": 0.0, "skipped": 0}
    stats = {}
    learned = []
    for row in rows:
        win = row["pnl"] > 0
        agressif["n"] += 1
        agressif["wins"] += 1 if win else 0
        agressif["pnl"] += row["pnl"]
        mult, key, status = multiplier(stats, row)
        if mult <= 0:
            turbo["skipped"] += 1
            update(stats, key, win)
            continue
        turbo["n"] += 1
        turbo["wins"] += 1 if win else 0
        turbo["raw_pnl"] += row["pnl"]
        turbo["pnl"] += row["pnl"] * mult
        update(stats, key, win)
        if not win:
            learned.append({"symbol": row["symbol"], "bucket": key, "pnl": row["pnl"]})
    def pack(s):
        return {"n": s["n"], "wins": s["wins"],
                "win_rate": (s["wins"] / s["n"]) if s["n"] else None,
                "pnl": round(s["pnl"], 2),
                "raw_pnl": round(s.get("raw_pnl", s["pnl"]), 2)}
    blocked = [k for k, v in stats.items() if decide(v["wins"], v["n"])[0] == "block"]
    return {"trades_in_tape": len(rows), "agressif": pack(agressif),
            "turbo": {**pack(turbo), "skipped": turbo["skipped"]},
            "blocked_buckets": blocked, "losses_seen": len(learned),
            "note": "Replay of archived chart labels in backtest_chart.json. PnL is the recorded trade pnl, not a new fill simulation. Turbo skips a bucket only after it has enough losses."}

def main():
    path = os.path.join(os.path.dirname(__file__), "backtest_chart.json")
    report = run(load_rows(path))
    print(json.dumps(report, indent=2))
    return report

if __name__ == "__main__":
    main()
