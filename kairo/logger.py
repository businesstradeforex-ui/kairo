"""Stage 6 - LOGGER. Input: outputs of all prior stages for a cycle. Persists kills, scores (already in db by Analyst),
entries/exits, equity curve, per-agent status; writes state.json consumed by the dashboard."""
import json, os
from common import jsonl, now_iso, kv_get, kv_set, data_dir, eurusd, bankroll_usd

AGENTS = ["scout", "filter", "analyst", "executor", "risk", "logger"]

def set_agent(con, name, status, last, counters):
    if not counters:  # keep last counters while the stage is running
        counters = (kv_get(con, f"agent_{name}", {}) or {}).get("counters", {})
    kv_set(con, f"agent_{name}", {"status": status, "last_action": last, "counters": counters, "ts": now_iso()})

def log_cycle(con, cycle, cands, kills, scored, passes, fills, exits, note=""):
    from executor import equity
    ts = now_iso()
    for c in cands:
        con.execute("INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?,?)", (cycle, ts, c["mint"], c["pair"], c["symbol"], c["age_h"], c["mcap"], c["liq"], c["vol"].get("h1")))
    for c in cands:
        con.execute("INSERT OR REPLACE INTO token_meta VALUES(?,?,?,?,?,?)", (c["mint"], c["symbol"], c["pair"], c.get("icon"), ts,
                    json.dumps({k: c.get(k) for k in ("dex", "age_h", "mcap", "fdv", "liq", "price", "vol", "chg", "txns", "url", "facts")}, default=str)))
    for s in scored:
        con.execute("UPDATE token_meta SET snap=json_set(snap, '$.facts', json(?)) WHERE mint=?", (json.dumps(s.get("facts") or {}, default=str), s["mint"]))
    for k in kills:
        con.execute("INSERT INTO kills VALUES(?,?,?,?,?,?,?,?)", (cycle, k["ts"], k["mint"], k["pair"], k["symbol"], k["reason"], json.dumps(k["value"]), k["threshold"]))
    eq, ov = equity(con)
    n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
    con.execute("INSERT INTO equity VALUES(?,?,?,?,?)", (ts, kv_get(con, "cash", 0.0), ov, eq, n_open))
    killed_tokens = len({k["mint"] for k in kills})
    con.execute("INSERT INTO cycles(id,ts,scanned,killed,scored,passed,entries,exits,equity,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (cycle, ts, len(cands), killed_tokens, len(scored), len(passes), len(fills), len(exits), eq, note))
    con.commit()
    jsonl("logger", {"cycle": cycle, "scanned": len(cands), "killed_tokens": killed_tokens, "kill_reasons": len(kills),
                     "scored": len(scored), "passed": len(passes), "entries": len(fills), "exits": len(exits), "equity": eq})
    tot_k = con.execute("SELECT COUNT(*) FROM kills").fetchone()[0]
    set_agent(con, "logger", "idle", f"cycle {cycle} enregistré (equity {eq/eurusd(con):,.2f} €)", {"cycles": cycle, "kill_rows": tot_k})
    write_state(con)

def write_state(con):
    from executor import equity
    from config import cfg, profile_name
    st = {"ts": now_iso(), "mode": "PAPER", "profile": profile_name(), "profile_label": cfg()["label_fr"],
          "agents": {a: kv_get(con, f"agent_{a}", {}) for a in AGENTS}}
    eq, ov = equity(con)
    st["equity"] = eq; st["cash"] = kv_get(con, "cash", 0.0); st["bankroll"] = bankroll_usd(con); fx = eurusd(con); st["eurusd"] = fx; st["bankroll_eur"] = kv_get(con, "bankroll_eur", 1000.0); st["equity_eur"] = eq / fx; st["session"] = kv_get(con, "session")
    st["kills"] = [dict(r) for r in con.execute("SELECT * FROM kills ORDER BY rowid DESC LIMIT 80")]
    st["kills_by_reason"] = {r[0]: r[1] for r in con.execute("SELECT reason, COUNT(DISTINCT mint) FROM kills GROUP BY reason ORDER BY 2 DESC")}
    last_cycle = con.execute("SELECT MAX(cycle) FROM scores").fetchone()[0]
    rows = con.execute("SELECT * FROM scores WHERE cycle >= ? ORDER BY cycle DESC, score DESC LIMIT 40", ((last_cycle or 0) - 3,)).fetchall()
    seen, sc = set(), []
    for r in rows:
        if r["mint"] in seen: continue
        seen.add(r["mint"]); d = dict(r); d["components"] = json.loads(d["components"]); sc.append(d)
    st["scores"] = sorted(sc, key=lambda x: -x["score"])[:20]
    st["open"] = [dict(r) for r in con.execute("SELECT * FROM positions WHERE status='open' ORDER BY id DESC")]
    st["closed"] = [dict(r) for r in con.execute("SELECT * FROM positions WHERE status='closed' ORDER BY id DESC LIMIT 30")]
    st["equity_curve"] = [dict(r) for r in con.execute("SELECT ts, equity FROM (SELECT rowid, ts, equity FROM equity ORDER BY rowid DESC LIMIT 1500) ORDER BY rowid")]
    st["cycles"] = [dict(r) for r in con.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT 15")]
    folder = data_dir()
    tmp = os.path.join(folder, "state.json.tmp")
    with open(tmp, "w") as f:
        json.dump(st, f, default=str)
    os.replace(tmp, os.path.join(folder, "state.json"))
