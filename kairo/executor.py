"""Stage 4 - EXECUTOR (PAPER). Input: Analyst passes. Output: filled paper orders (each carries its stop).
Virtual bankroll $10,000. Max 8% of equity per trade. PAPER ONLY — no wallets, no keys, no real orders.
Fill = DexScreener priceUsd * (1 + slippage), slippage from constant-product price impact on liquidity."""
import datetime, os, time
from common import jsonl, now_iso, kv_get, kv_set, data_dir
from config import cfg, profile_name
import risk, learn

BANKROLL = 10_000.0  # legacy default only; sessions store bankroll_usd/cash in kv (1000 EUR session)
FEE = 0.0025  # assumed swap fee
MAX_FRAC = 0.08  # hard cap, never exceeded

def _turbo_stats_path():
    return os.path.join(data_dir(), "turbo_learner.json")

def _turbo_journal_path():
    return os.path.join(data_dir(), "journal_turbo.jsonl")

def slippage(size_usd, liq_usd):
    quote_side = max(liq_usd / 2.0, 1.0)  # ~half of pool liquidity sits on the quote side
    return min(size_usd / quote_side + FEE, 0.25)

def cash(con):
    return kv_get(con, "cash", BANKROLL)

def equity(con):
    ov = sum((r["last_price"] or r["entry_price"]) * r["qty"] for r in con.execute("SELECT * FROM positions WHERE status='open'"))
    return cash(con) + ov, ov

def _parse_ts(ts):
    if not ts:
        return 0
    try:
        return datetime.datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0

def size_frac(c, E):
    """3–8% of equity by score / signal strength, never above 8%."""
    lo, hi = E["min_frac"], E["max_frac"]
    score = float(c.get("score") or 0)
    triggers = c.get("triggers") or []
    frac = lo + (hi - lo) * max(0.0, min(1.0, (score - 30.0) / 50.0))
    if any(t.startswith("signal_") for t in triggers):
        frac = min(hi, frac + 0.01)
    if "score" in triggers and score >= 70:
        frac = hi
    return max(lo, min(hi, min(frac, MAX_FRAC)))

def _paris_day():
    # box clock is Europe/Paris
    return datetime.datetime.now().astimezone().date().isoformat()

def ensure_dd_baseline(con):
    """Daily (Paris) drawdown baseline. Reset when the day or the profile changes.
    On the first tick of a new profile we snapshot *current* equity so a past
    drawdown vs the original $10k bankroll does not immediately trip the breaker."""
    today = _paris_day()
    prof = profile_name()
    if kv_get(con, "dd_day") != today or kv_get(con, "dd_profile") != prof:
        eq, _ = equity(con)
        kv_set(con, "dd_day", today)
        kv_set(con, "dd_profile", prof)
        kv_set(con, "dd_start_eq", eq)
        kv_set(con, "dd_hwm", eq)
        return eq
    eq, _ = equity(con)
    hwm = kv_get(con, "dd_hwm", eq)
    if eq > hwm:
        kv_set(con, "dd_hwm", eq)
    return kv_get(con, "dd_start_eq", eq)

def circuit_tripped(con, E):
    pct = E.get("daily_dd_pct")
    if not pct:
        return False, None
    start = ensure_dd_baseline(con)
    eq, _ = equity(con)
    if start and eq <= start * (1 - pct):
        return True, {"equity": eq, "start": start, "dd_pct": (eq / start - 1) * 100}
    return False, {"equity": eq, "start": start}

def loss_pause_active(con, E):
    n = E.get("consec_loss_pause_n") or 0
    pause_s = E.get("consec_loss_pause_s") or 0
    if n < 1 or not pause_s:
        return False, None
    # Only the active profile's closes count — a streak from a previous profile
    # must not lock the new one the moment we switch.
    rows = list(con.execute(
        "SELECT id, pnl_usd, exit_ts FROM positions WHERE status='closed' AND profile=? ORDER BY id DESC LIMIT ?",
        (profile_name(), n)))
    if len(rows) < n:
        return False, None
    if not all((r["pnl_usd"] or 0) < 0 for r in rows):
        return False, None
    last = _parse_ts(rows[0]["exit_ts"])
    age = time.time() - last if last else 1e9
    if age < pause_s:
        return True, {"remaining_s": int(pause_s - age), "last_exit": rows[0]["exit_ts"]}
    return False, None

def learn_refresh(con):
    """Rolling expectancy per setup/token/hour for this profile + journal of losing trades with their features."""
    rows = [dict(r) for r in con.execute("""SELECT p.*, p.pnl_usd + COALESCE((SELECT SUM(x.pnl_usd) FROM partial_exits x WHERE x.position_id=p.id),0) AS tot,
                   COALESCE(p.qty_initial, p.qty) * p.entry_price AS cost0 FROM positions p WHERE status='closed' AND profile=? ORDER BY id""", (profile_name(),))]
    trades = [{"setup": r["entry_trigger"], "token": r["mint"], "entry_ts": r["entry_ts"], "pnl": r["tot"], "cost": r["cost0"]} for r in rows]
    done = set(kv_get(con, "journaled", []) or [])
    for r in rows:
        if r["tot"] < 0 and r["id"] not in done:
            hold = _parse_ts(r["exit_ts"]) - _parse_ts(r["entry_ts"])
            jsonl("journal_losses", {"mode": profile_name(), "id": r["id"], "symbol": r["symbol"], "mint": r["mint"], "setup": r["entry_trigger"],
                                     "score": r["score"], "liq": r["liq"], "entry_slip": r["entry_slip"], "exit_reason": r["exit_reason"],
                                     "pnl_usd": r["tot"], "hold_s": hold, "peak_pct": (r["peak_price"] / r["entry_price"] - 1) * 100 if r["entry_price"] else None,
                                     "entry_ts": r["entry_ts"], "exit_ts": r["exit_ts"]})
            done.add(r["id"])
    if profile_name() == "turbo":
        import learner as bayes
        seen = set(kv_get(con, "turbo_learned", []) or [])
        stats = bayes.load(_turbo_stats_path())
        changed = False
        for r in rows:
            if r["id"] in seen:
                continue
            feat = {"setup": r["entry_trigger"] or "score", "liq": r["liq"], "symbol": r["symbol"],
                    "pnl_usd": r["tot"], "exit_reason": r["exit_reason"], "id": r["id"]}
            bayes.update(stats, bayes.bucket(feat), r["tot"] > 0)
            if r["tot"] < 0:
                bayes.journal_loss(_turbo_journal_path(), feat)
            seen.add(r["id"])
            changed = True
        if changed:
            bayes.save(_turbo_stats_path(), stats)
            kv_set(con, "turbo_learned", sorted(seen))
    kv_set(con, "journaled", sorted(done))
    return learn.refresh(con, trades, now_iso())

def run(cycle, con, passes):
    E = cfg()["executor"]
    fills = []
    tripped, dd_info = circuit_tripped(con, E)
    if tripped:
        jsonl("executor", {"cycle": cycle, "action": "pause_daily_drawdown", **(dd_info or {})})
        return fills
    paused, pause_info = loss_pause_active(con, E)
    if paused:
        jsonl("executor", {"cycle": cycle, "action": "pause_consecutive_losses", **(pause_info or {})})
        return fills
    lessons = learn_refresh(con)
    n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
    max_slip = E.get("max_slip")
    min_size = E.get("min_size_usd") or 10
    for c in sorted(passes, key=lambda x: (-len(x.get("triggers") or []), -x["score"])):
        if con.execute("SELECT 1 FROM positions WHERE mint=? AND status='open'", (c["mint"],)).fetchone():
            jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_duplicate"})
            continue
        if n_open >= E["max_open"]:
            jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_max_open", "max_open": E["max_open"]})
            continue
        if E["reentry_cooldown_s"]:
            last = con.execute("SELECT exit_ts FROM positions WHERE mint=? AND status='closed' ORDER BY id DESC LIMIT 1", (c["mint"],)).fetchone()
            if last and last["exit_ts"]:
                age = time.time() - _parse_ts(last["exit_ts"])
                if age < E["reentry_cooldown_s"]:
                    jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_cooldown", "remaining_s": int(E["reentry_cooldown_s"] - age)})
                    continue
        trig0 = ",".join(c.get("triggers") or ["score"])
        mult, why = learn.size_mult(lessons, trig0, c["mint"])
        if mult <= 0:
            jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_learned", "keys": why})
            continue
        eq, _ = equity(con)
        frac = size_frac(c, E) * mult
        priority = 0.0
        turbo_key = None
        if profile_name() == "turbo":
            import learner as bayes
            stats = bayes.load(_turbo_stats_path())
            bmult, turbo_key, _bstatus = bayes.multiplier(stats, {"setup": trig0, "liq": c.get("liq")})
            if bmult <= 0:
                jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_turbo_bucket", "bucket": turbo_key})
                continue
            frac *= bmult
        size = min(frac * eq, cash(con))
        if size < min_size or c["price"] <= 0:
            jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_no_cash"})
            continue
        if profile_name() == "turbo":
            from fills import paper_buy
            quote = paper_buy(c["price"], size, c["liq"])
            slip = quote["slip"]
            priority = quote["priority_fee_usd"]
            if cash(con) < size + priority:
                jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_no_cash"})
                continue
        else:
            slip = slippage(size, c["liq"])
        if max_slip is not None and slip > max_slip:
            # size down to liquidity so slip <= max_slip, otherwise skip
            # slip = size/(liq/2) + FEE  => size = (max_slip - FEE) * liq/2
            cap = max(max_slip - FEE, 0) * (max(c["liq"], 1.0) / 2.0)
            if cap < min_size:
                jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_slippage",
                                   "slip": slip, "max_slip": max_slip, "liq": c["liq"], "size_usd": size})
                continue
            size = min(size, cap)
            slip = slippage(size, c["liq"])
            if slip > max_slip + 1e-9:
                jsonl("executor", {"cycle": cycle, "mint": c["mint"], "symbol": c["symbol"], "action": "skip_slippage",
                                   "slip": slip, "max_slip": max_slip, "liq": c["liq"]})
                continue
        if profile_name() == "turbo":
            quote = paper_buy(c["price"], size, c["liq"])
            slip = quote["slip"]
            fill = quote["fill_price"]
            priority = quote["priority_fee_usd"]
        else:
            fill = c["price"] * (1 + slip)
        triggers = c.get("triggers") or ["score"]
        trigger = ",".join(triggers)
        order = {"mint": c["mint"], "pair": c["pair"], "symbol": c["symbol"], "ref_price": c["price"], "fill_price": fill,
                 "slip": slip, "size_usd": size, "qty": size / fill, "liq": c["liq"], "score": c["score"],
                 "entry_trigger": trigger, "profile": profile_name()}
        order = risk.attach_stop(order)  # stop is set BEFORE the entry is recorded, from the fill
        assert order.get("stop_price"), "refusing entry without stop"
        cur = con.execute("""INSERT INTO positions(mint,pair,symbol,status,entry_ts,entry_price,ref_price,qty,cost_usd,entry_slip,
                       stop_price,initial_stop,trail_active,peak_price,last_price,liq,score,entry_trigger,profile,tp1_done,qty_initial)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (c["mint"], c["pair"], c["symbol"], "open", now_iso(), fill, c["price"], order["qty"], size, slip,
                     order["stop_price"], order["stop_price"], 0, fill, c["price"], c["liq"], c["score"], trigger,
                     profile_name(), 0, order["qty"]))
        kv_set(con, "cash", cash(con) - size - priority)
        order["position_id"] = cur.lastrowid
        fills.append(order)
        n_open += 1
        jsonl("executor", {"cycle": cycle, "action": "paper_buy", **order})
    con.commit()
    return fills
