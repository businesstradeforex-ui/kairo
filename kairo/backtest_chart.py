"""Validate the 1m EMA/VWAP pullback rule on archived trades: would it have allowed each entry?"""
import sqlite3, json, sys, time, datetime
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chart
from common import get_json
db = sys.argv[1]
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
rows = list(c.execute("select p.*, (select coalesce(sum(pnl_usd),0) from partial_exits x where x.position_id=p.id) part from positions p order by id"))
out = []
for r in rows:
    ts = int(datetime.datetime.fromisoformat(r["entry_ts"]).timestamp())
    url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{r['pair']}/ohlcv/minute?aggregate=1&limit=90&currency=usd&token={r['mint']}&before_timestamp={ts}"
    d = get_json(url, use_cache=False)
    try:
        cs = sorted(d["data"]["attributes"]["ohlcv_list"], key=lambda x: x[0])
        cs = [{"t": int(x[0]), "o": float(x[1]), "h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in cs]
    except Exception:
        cs = None
    chart._cache[(r["pair"], r["mint"])] = (time.time(), cs)
    real_time = time.time
    chart.time.time = lambda: ts + 30
    res = chart.analyze(r["pair"], r["mint"], {"touch_pct": 0.02, "max_undercut_pct": 0.04, "vol_mult": 1.0, "max_ext_vwap": 0.12})
    chart.time.time = real_time
    pnl = (r["pnl_usd"] or 0) + r["part"]
    out.append({"id": r["id"], "symbol": r["symbol"], "pnl": round(pnl, 1), "status": r["status"], "chart_ok": res.get("ok"), "why": res.get("why"), "ext": res.get("ext_vwap_pct"), "above_vwap": res.get("above_vwap"), "trend": res.get("trend")})
    print(json.dumps(out[-1]), flush=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_chart.json"), "w"), indent=1)
