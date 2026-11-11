"""Stage 5 - RISK. Input: Executor fills + open positions. Output: exits (and partial TPs).
Stop-loss -6% from the fill price, set before entry. Trailing stop activates after +12%; trails 6% below peak.
Profit profile: sell 50% at +15% from fill and move the stop to breakeven; time-exit only if still flat.
Price jumps >50% vs the last good tick are re-verified on a second DexScreener endpoint before we act.
PAPER ONLY."""
import datetime, time
from common import get_json, jsonl, now_iso, kv_get, kv_set
from config import cfg

DS_PAIRS = "https://api.dexscreener.com/latest/dex/pairs/solana/"
DS_TOKENS = "https://api.dexscreener.com/tokens/v1/solana/"

def attach_stop(order):
    R = cfg()["risk"]
    order["stop_price"] = order["fill_price"] * (1 - R["stop_pct"])
    extra = ""
    if R.get("partial_tp_pct"):
        extra += f"; TP 50% at +{R['partial_tp_pct']:.0%}, then stop to breakeven"
    if R.get("time_exit_s"):
        extra += f"; time-exit after {int(R['time_exit_s']//60)}m if flat"
    order["stop_rule"] = f"-{R['stop_pct']:.0%} hard stop from fill; trail {R['trail_pct']:.0%} from peak after +{R['trail_activate']:.0%}{extra}"
    return order

def _extract_pair(p, want_pair, want_mint=None):
    if not p or p.get("pairAddress") != want_pair:
        return None
    if want_mint and (p.get("baseToken") or {}).get("address") and p["baseToken"]["address"] != want_mint:
        return None
    px = float(p.get("priceUsd") or 0)
    liq = (p.get("liquidity") or {}).get("usd") or 0
    if px <= 0:
        return None
    return (px, liq)

def price_from_pairs_endpoint(pair, mint=None):
    d = get_json(DS_PAIRS + pair, use_cache=False)
    if not d:
        return None
    for p in (d.get("pairs") or ([d["pair"]] if d.get("pair") else [])):
        got = _extract_pair(p, pair, mint)
        if got:
            return got
    return None

def price_from_tokens_endpoint(mint, pair):
    if not mint:
        return None
    d = get_json(DS_TOKENS + mint, use_cache=False)
    if not isinstance(d, list):
        return None
    for p in d:
        got = _extract_pair(p, pair, mint)
        if got:
            return got
    return None

def verified_price(pair, mint, last_good, jump_pct):
    """Return (price, liq, note). Refuse an unconfirmed >jump_pct move vs last_good."""
    a = price_from_pairs_endpoint(pair, mint)
    if not a:
        a = price_from_tokens_endpoint(mint, pair)
        if not a:
            return None, None, "unavailable"
    px, liq = a
    if last_good and last_good > 0 and jump_pct and abs(px / last_good - 1) >= jump_pct:
        b = price_from_tokens_endpoint(mint, pair)
        if not b or b is a:
            # if first source was pairs, second is tokens; if first was already tokens, try pairs again
            b = price_from_pairs_endpoint(pair, mint) if not b else b
        if not b:
            return None, None, f"jump_unconfirmed {px} vs last {last_good}"
        px2, liq2 = b
        # both must agree the new level (within 15%)
        if min(px, px2) / max(px, px2) < 0.85:
            # disagreement: one source still near last_good?
            close_to_last = []
            for cand, lq in ((px, liq), (px2, liq2)):
                if abs(cand / last_good - 1) < jump_pct:
                    close_to_last.append((cand, lq))
            if close_to_last:
                # treat the outlier as a bad tick, keep the source near last_good
                cand, lq = close_to_last[0]
                return cand, lq, f"jump_rejected {px}/{px2} kept {cand}"
            return None, None, f"jump_disagreement {px} vs {px2}"
        # confirmed crash or spike: use the conservative (lower) price for downs, higher only if both agree up
        if px < last_good:
            px, liq = min(px, px2), liq if px <= px2 else liq2
            return px, liq, "jump_confirmed_down"
        px, liq = max(px, px2), liq if px >= px2 else liq2
        return px, liq, "jump_confirmed_up"
    return px, liq, "ok"

def live_prices(positions, jump_pct):
    """Map pair -> (price, liq, note). Verifies pairAddress + mint; re-checks big jumps."""
    out = {}
    # first pass: batch for speed, then verify jumps individually
    pairs = []
    by_pair = {}
    for r in positions:
        by_pair[r["pair"]] = r
        pairs.append(r["pair"])
    raw = {}
    for i in range(0, len(pairs), 30):
        chunk = pairs[i:i + 30]
        d = get_json(DS_PAIRS + ",".join(chunk), use_cache=False)
        for p in (d or {}).get("pairs") or []:
            addr = p.get("pairAddress")
            if addr in by_pair:
                got = _extract_pair(p, addr, by_pair[addr]["mint"])
                if got:
                    raw[addr] = got
    for r in positions:
        last_good = r["last_price"] or r["entry_price"] or r["ref_price"]
        if r["pair"] in raw:
            px, liq = raw[r["pair"]]
            if not last_good or not jump_pct or abs(px / last_good - 1) < jump_pct:
                out[r["pair"]] = (px, liq, "ok")
                continue
        # missing from the batch, or a >50% jump: do the two-source check
        px, liq, note = verified_price(r["pair"], r["mint"], last_good, jump_pct)
        if px:
            out[r["pair"]] = (px, liq, note)
        else:
            out[r["pair"]] = (None, None, note or "unavailable")
    return out

def _age_s(entry_ts):
    try:
        return time.time() - datetime.datetime.fromisoformat(entry_ts).timestamp()
    except Exception:
        return 0

def _col(r, k, default=None):
    try:
        if k in r.keys():
            v = r[k]
            return default if v is None else v
    except Exception:
        pass
    return default

def run(cycle, con, fills=None):
    from executor import slippage
    R = cfg()["risk"]
    TRAIL_ACTIVATE = R["trail_activate"]
    TRAIL_PCT = R["trail_pct"]
    TIME_EXIT_S = R.get("time_exit_s")
    FLAT_ABS = R.get("flat_abs_pct")
    PARTIAL_TP = R.get("partial_tp_pct")
    PARTIAL_FRAC = R.get("partial_tp_frac") or 0.5
    JUMP = R.get("jump_verify_pct") or 0.50
    for f in fills or []:
        jsonl("risk", {"cycle": cycle, "action": "armed", "position_id": f["position_id"], "symbol": f["symbol"], "stop": f["stop_price"]})
    opens = con.execute("SELECT * FROM positions WHERE status='open'").fetchall()
    if not opens:
        return []
    pxmap = live_prices(opens, JUMP)
    exits = []
    for r in opens:
        tup = pxmap.get(r["pair"])
        if not tup or not tup[0]:
            jsonl("risk", {"cycle": cycle, "action": "price_unavailable", "position_id": r["id"], "symbol": r["symbol"], "note": (tup or (None, None, "missing"))[2]})
            continue
        p, liq, note = tup
        if note and note not in ("ok",):
            jsonl("risk", {"cycle": cycle, "action": "price_note", "position_id": r["id"], "symbol": r["symbol"], "price": p, "note": note})
        con.execute("INSERT INTO price_samples VALUES(?,?,?)", (r["pair"], time.time(), p))
        peak = max(r["peak_price"] or 0, p)
        trail = r["trail_active"] or peak >= r["entry_price"] * (1 + TRAIL_ACTIVATE)
        stop = r["stop_price"]
        tp1 = int(_col(r, "tp1_done", 0) or 0)
        if tp1:
            stop = max(stop, r["entry_price"])  # breakeven after partial TP
        if trail:
            stop = max(stop, peak * (1 - TRAIL_PCT))

        # Scale out in tranches (profit profile): e.g. 1/3 at +15%, half the rest at +30%; stop to breakeven after the first
        levels = R.get("tp_levels") or ([(PARTIAL_TP, PARTIAL_FRAC)] if PARTIAL_TP else [])
        stage = tp1 + int(_col(r, "tp2_done", 0) or 0)
        while stage < len(levels) and p >= r["entry_price"] * (1 + levels[stage][0]):
            lvl, frac = levels[stage]
            qty0 = r["qty"]
            sell_qty = qty0 * frac
            remain_qty = qty0 - sell_qty
            if not (sell_qty > 0 and remain_qty > 0):
                break
            value = p * sell_qty
            slip = slippage(value, liq or r["liq"])
            exit_px = p * (1 - slip)
            proceeds = exit_px * sell_qty
            cost_sold = r["cost_usd"] * (sell_qty / qty0)
            pnl = proceeds - cost_sold
            col = "tp1_done" if stage == 0 else "tp2_done"
            new_stop = max(stop, r["entry_price"])
            kv_set(con, "cash", kv_get(con, "cash", 0.0) + proceeds)
            con.execute(f"""UPDATE positions SET qty=?, cost_usd=?, last_price=?, peak_price=?, stop_price=?, trail_active=?,
                           {col}=1, qty_initial=COALESCE(qty_initial, ?) WHERE id=?""",
                        (remain_qty, r["cost_usd"] - cost_sold, p, peak, new_stop, int(trail), qty0, r["id"]))
            con.execute("""INSERT INTO partial_exits(position_id,ts,symbol,mint,pair,qty,price,proceeds_usd,pnl_usd,reason)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (r["id"], now_iso(), r["symbol"], r["mint"], r["pair"], sell_qty, exit_px, proceeds, pnl, f"partial_tp_{int(lvl*100)}"))
            ev = {"cycle": cycle, "action": "paper_sell_partial", "position_id": r["id"], "symbol": r["symbol"],
                  "reason": f"partial_tp_{int(lvl*100)}", "trigger_price": p, "exit_price": exit_px, "qty": sell_qty,
                  "proceeds_usd": proceeds, "pnl_usd": pnl, "stop": new_stop}
            exits.append(ev); jsonl("risk", ev)
            r = con.execute("SELECT * FROM positions WHERE id=?", (r["id"],)).fetchone()
            tp1 = 1; stop = new_stop; stage += 1

        unreal_pct = (p / r["entry_price"] - 1) * 100 if r["entry_price"] else 0
        reason = None
        if p <= stop:
            reason = "trailing_stop" if trail and stop > r["initial_stop"] and (not tp1 or stop > r["entry_price"]) else "stop_loss"
            if tp1 and p <= r["entry_price"] and not (trail and stop > r["entry_price"] and p <= stop and stop > r["entry_price"]):
                # hit the breakeven stop
                if p <= r["entry_price"] and not (trail and stop > r["entry_price"]):
                    reason = "stop_breakeven"
        elif R.get("max_hold_s") and _age_s(r["entry_ts"]) >= R["max_hold_s"]:
            reason = "time_exit_max_hold"
        elif TIME_EXIT_S and FLAT_ABS is not None and not trail and not tp1 and _age_s(r["entry_ts"]) >= TIME_EXIT_S and abs(unreal_pct) < FLAT_ABS:
            reason = "time_exit_flat"
        if reason:
            value = p * r["qty"]
            slip = slippage(value, liq or r["liq"])
            exit_px = p * (1 - slip)
            proceeds = exit_px * r["qty"]
            pnl = proceeds - r["cost_usd"]
            con.execute("""UPDATE positions SET status='closed', exit_ts=?, exit_price=?, exit_reason=?, proceeds_usd=?, pnl_usd=?, pnl_pct=?,
                           last_price=?, peak_price=?, stop_price=?, trail_active=? WHERE id=?""",
                        (now_iso(), exit_px, reason, proceeds, pnl, pnl / r["cost_usd"] * 100 if r["cost_usd"] else 0, p, peak, stop, int(trail), r["id"]))
            kv_set(con, "cash", kv_get(con, "cash", 0.0) + proceeds)
            ev = {"cycle": cycle, "action": "paper_sell", "position_id": r["id"], "symbol": r["symbol"], "reason": reason,
                  "trigger_price": p, "exit_price": exit_px, "stop": stop, "peak": peak, "pnl_usd": pnl,
                  "entry_trigger": _col(r, "entry_trigger"), "note": note}
            exits.append(ev); jsonl("risk", ev)
        else:
            con.execute("UPDATE positions SET last_price=?, peak_price=?, stop_price=?, trail_active=? WHERE id=?",
                        (p, peak, stop, int(trail), r["id"]))
            if trail and not r["trail_active"]:
                jsonl("risk", {"cycle": cycle, "action": "trail_activated", "position_id": r["id"], "symbol": r["symbol"], "peak": peak, "stop": stop})
    con.commit()
    return exits
