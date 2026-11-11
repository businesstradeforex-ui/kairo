"""Stage 2 - FILTER. Input: Scout candidates. Output: survivors (+ on-chain facts attached).
Every kill is logged with token, pair, reason, value, threshold, timestamp.
Strict profile: fail-closed. Agressif: hard kills only for mint/freeze + liquidity (+ extreme concentration);
other checks become score penalties. Missing data is a penalty except mint/freeze (fail-closed or defer if budget)."""
import time
from common import get_json, jsonl, now_iso
from config import cfg, profile_name

RC = "https://api.rugcheck.xyz/v1/tokens"
RPC = "https://api.mainnet-beta.solana.com"
BURN_ADDRS = {"11111111111111111111111111111111", "1nc1nerator11111111111111111111111111111111"}
_cache = {}  # mint -> (epoch, report)
_budget_used = 0
_budget_skips = set()

def _cache_s():
    return cfg()["filter"].get("rugcheck_cache_s", 600)

def reset_budget():
    global _budget_used, _budget_skips
    _budget_used = 0
    _budget_skips = set()

def rugcheck(mint, cap=None):
    """Return report or None. Budget skips are recorded in _budget_skips (distinct from API failure)."""
    global _budget_used
    hit = _cache.get(mint)
    if hit and time.time() - hit[0] < _cache_s():
        return hit[1]
    if cap is not None and _budget_used >= cap:
        _budget_skips.add(mint)
        return None
    _budget_used += 1
    d = get_json(f"{RC}/{mint}/report", timeout=20, tries=2)
    if d and isinstance(d, dict) and d.get("mint"):
        _cache[mint] = (time.time(), d)
        return d
    return None

def rpc(method, params):
    d = get_json(RPC, method="POST", body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, tries=3)
    return (d or {}).get("result")

def rpc_fallback(mint):
    """Public-RPC fallback: mint/freeze authority + raw largest accounts (cannot see LP lock, creator, bundles)."""
    out = {}
    ai = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    try:
        info = ai["value"]["data"]["parsed"]["info"]
        out["mintAuthority"] = info.get("mintAuthority")
        out["freezeAuthority"] = info.get("freezeAuthority")
        out["supply"] = float(info["supply"]) / 10 ** info["decimals"]
    except Exception:
        pass
    la = rpc("getTokenLargestAccounts", [mint])
    try:
        out["largest"] = [float(a["uiAmount"] or 0) for a in la["value"]]
    except Exception:
        pass
    return out

def _kill(kills, reason, value, threshold):
    kills.append({"reason": reason, "value": value, "threshold": threshold})

def _pen(pens, reason, value, threshold, points):
    pens.append({"reason": reason, "value": value, "threshold": threshold, "points": points})

def onchain_facts(c, rep):
    """Derive the facts used by on-chain checks. Missing facts -> None (fail closed in strict)."""
    f = {"source": "rugcheck" if rep else None}
    if not rep:
        fb = rpc_fallback(c["mint"])
        f["source"] = "solana_rpc_fallback" if fb else None
        f["mint_auth"] = fb.get("mintAuthority", "UNKNOWN") if "mintAuthority" in fb else "UNKNOWN"
        f["freeze_auth"] = fb.get("freezeAuthority", "UNKNOWN") if "freezeAuthority" in fb else "UNKNOWN"
        f["lp_safe_pct"] = None; f["top10_pct"] = None; f["dev_pct"] = None; f["dev_rugs"] = None
        f["bundle_pct"] = None; f["holders"] = None
        f["token_rugged"] = False
        return f
    f["mint_auth"] = rep.get("mintAuthority")
    f["freeze_auth"] = rep.get("freezeAuthority")
    tok = rep.get("token") or {}
    dec = tok.get("decimals") or 0
    supply_raw = float(tok.get("supply") or 0)
    # LP: prefer the market matching the DexScreener pair; else liquidity-weighted average over markets
    mk = [m for m in rep.get("markets") or [] if m.get("pubkey") == c["pair"]]
    if mk and mk[0].get("lp"):
        f["lp_safe_pct"] = float(mk[0]["lp"].get("lpLockedPct") or 0)
        f["lp_market"] = mk[0].get("marketType")
    elif rep.get("markets"):
        tot = sum(float((m.get("lp") or {}).get("quoteUSD") or 0) for m in rep["markets"])
        if tot > 0:
            f["lp_safe_pct"] = sum(float((m.get("lp") or {}).get("lpLockedPct") or 0) * float((m.get("lp") or {}).get("quoteUSD") or 0) for m in rep["markets"]) / tot
        else:
            f["lp_safe_pct"] = None
        f["lp_market"] = "aggregate"
    else:
        f["lp_safe_pct"] = None
    # Top-10 excluding AMM / pool / locker / burn accounts
    known = rep.get("knownAccounts") or {}
    excl = set(BURN_ADDRS) | {m.get("pubkey") for m in rep.get("markets") or []}
    for m in rep.get("markets") or []:
        for k in ("liquidityAAccount", "liquidityBAccount", "mintLPAccount"):
            if m.get(k): excl.add(m[k] if isinstance(m[k], str) else (m[k] or {}).get("pubkey"))
    for addr, meta in known.items():
        if (meta or {}).get("type") in ("AMM", "LOCKER"):
            excl.add(addr)
    th = rep.get("topHolders")
    if th is None:
        f["top10_pct"] = None
    else:
        real = [h for h in th if h.get("owner") not in excl and h.get("address") not in excl]
        f["top10_pct"] = round(sum(float(h.get("pct") or 0) for h in real[:10]), 3)
        f["top10_excluded"] = len(th) - len(real)
    # Dev holding: creatorBalance/supply and any top holder owned by creator
    creator = rep.get("creator")
    dev = None
    if rep.get("creatorBalance") is not None and supply_raw > 0:
        dev = float(rep["creatorBalance"]) / supply_raw * 100
    if creator and th:
        for h in th:
            if h.get("owner") == creator:
                dev = max(dev or 0, float(h.get("pct") or 0))
    f["dev_pct"] = None if dev is None else round(dev, 3)
    # Dev past rugs (approximation): RugCheck creator-history risk flags + rugged creatorTokens if present
    risks = [r.get("name", "") for r in rep.get("risks") or []]
    rug_flags = [r for r in risks if "rug" in r.lower() or "creator history" in r.lower()]
    ct = rep.get("creatorTokens") or []
    rugged_prev = [t for t in ct if isinstance(t, dict) and (t.get("rugged") or t.get("isRugged"))]
    f["dev_rugs"] = len(rug_flags) + len(rugged_prev) + (1 if rep.get("rugged") else 0)
    f["dev_prev_tokens"] = len(ct)
    f["token_rugged"] = bool(rep.get("rugged"))
    # Bundle / insider % (approximation): RugCheck insider-network holdings and insider-flagged top holders
    nets = rep.get("insiderNetworks")
    gi = rep.get("graphInsidersDetected")
    if nets is None and gi is None and th is None:
        f["bundle_pct"] = None
    else:
        net_pct = 0.0
        if nets and supply_raw > 0:
            net_pct = sum(float(n.get("currentHolding") or n.get("tokenAmount") or 0) for n in nets) / supply_raw * 100
        ins_pct = sum(float(h.get("pct") or 0) for h in (th or []) if h.get("insider") and h.get("owner") not in excl)
        f["bundle_pct"] = round(max(net_pct, ins_pct), 3)
        f["insider_accounts"] = gi
    f["holders"] = rep.get("totalHolders")
    f["rc_score_norm"] = rep.get("score_normalised")
    return f

def _apply_onchain(F, c, facts, kills, pens):
    if facts.get("token_rugged"):
        _kill(kills, "token_rugged", True, "must not be rugged")
    ma, fa = facts.get("mint_auth"), facts.get("freeze_auth")
    if ma == "UNKNOWN":
        if F["mint_freeze_fail_closed"]:
            _kill(kills, "data_unavailable:mint_authority", None, "fail_closed")
        else:
            _pen(pens, "data_unavailable:mint_authority", None, "penalty", 12)
    elif ma:
        _kill(kills, "mint_authority_not_revoked", ma, "must be null")
    if fa == "UNKNOWN":
        if F["mint_freeze_fail_closed"]:
            _kill(kills, "data_unavailable:freeze_authority", None, "fail_closed")
        else:
            _pen(pens, "data_unavailable:freeze_authority", None, "penalty", 12)
    elif fa:
        _kill(kills, "freeze_authority_not_revoked", fa, "must be null")

    lp = facts.get("lp_safe_pct")
    if lp is None:
        if F["lp_is_kill"] or F["fail_closed"]:
            _kill(kills, "data_unavailable:lp_lock", None, "fail_closed")
        else:
            _pen(pens, "data_unavailable:lp_lock", None, "penalty", 6)
    elif lp < F["lp_safe_min"]:
        if F["lp_is_kill"]:
            _kill(kills, "lp_not_burned_or_locked", round(lp, 2), f"<{F['lp_safe_min']}% locked/burned")
        else:
            pts = 12 if lp < 20 else 8
            _pen(pens, "lp_not_burned_or_locked", round(lp, 2), f"<{F['lp_safe_min']}%", pts)

    t10 = facts.get("top10_pct")
    if t10 is None:
        if not F["soft_as_penalty"] or F["fail_closed"]:
            _kill(kills, "data_unavailable:top10", None, "fail_closed")
        else:
            _pen(pens, "data_unavailable:top10", None, "penalty", 5)
    elif F.get("top10_hard") is not None and t10 > F["top10_hard"]:
        _kill(kills, "top10_extreme", t10, f">{F['top10_hard']}%")
    elif t10 > F["top10_max"]:
        if F["soft_as_penalty"]:
            pts = 18 if t10 > 80 else (12 if t10 > 60 else 8)
            _pen(pens, "top10_high", t10, f">{F['top10_max']}%", pts)
        else:
            _kill(kills, "top10_gt_25pct", t10, f">{F['top10_max']}%")

    dv = facts.get("dev_pct")
    if dv is None:
        if not F["soft_as_penalty"] or F["fail_closed"]:
            _kill(kills, "data_unavailable:dev_holding", None, "fail_closed")
        else:
            _pen(pens, "data_unavailable:dev_holding", None, "penalty", 5)
    elif F.get("dev_hard") is not None and dv > F["dev_hard"]:
        _kill(kills, "dev_holding_extreme", dv, f">{F['dev_hard']}%")
    elif dv > F["dev_max"]:
        if F["soft_as_penalty"]:
            pts = 15 if dv > 25 else 8
            _pen(pens, "dev_holding_high", dv, f">{F['dev_max']}%", pts)
        else:
            _kill(kills, "dev_holding_gt_3pct", dv, f">{F['dev_max']}%")

    dr = facts.get("dev_rugs")
    if dr is None:
        if not F["soft_as_penalty"] or F["fail_closed"]:
            _kill(kills, "data_unavailable:dev_past_rugs", None, "fail_closed")
        else:
            _pen(pens, "data_unavailable:dev_past_rugs", None, "penalty", 5)
    elif dr > 0:
        if F["dev_rugs_is_kill"]:
            _kill(kills, "dev_past_rugs", dr, ">0")
        else:
            _pen(pens, "dev_past_rugs", dr, ">0", min(20, 10 + 5 * int(dr)))

    b = facts.get("bundle_pct")
    if b is None:
        if not F["soft_as_penalty"] or F["fail_closed"]:
            _kill(kills, "data_unavailable:bundle", None, "fail_closed")
        else:
            _pen(pens, "data_unavailable:bundle", None, "penalty", 5)
    elif F.get("bundle_hard") is not None and b > F["bundle_hard"]:
        _kill(kills, "bundled_launch_extreme", b, f">{F['bundle_hard']}%")
    elif b > F["bundle_max"]:
        if F["soft_as_penalty"]:
            pts = 14 if b > 40 else 8
            _pen(pens, "bundled_launch_high", b, f">{F['bundle_max']}%", pts)
        else:
            _kill(kills, "bundled_launch_gt_10pct", b, f">{F['bundle_max']}%")

def run(cycle, candidates):
    F = cfg()["filter"]
    survivors, kill_rows = [], []
    reset_budget()
    # High-volume first so the RugCheck budget is spent on the liveliest coins
    ordered = sorted(candidates, key=lambda c: float((c.get("vol") or {}).get("h1") or 0), reverse=True)
    for c in ordered:
        kills, pens = [], []
        v1 = float(c["vol"].get("h1") or 0); ch1 = float(c["chg"].get("h1") or 0)
        if profile_name() == "turbo":
            from quality import turbo_block
            reason = turbo_block(c)
            if reason:
                _kill(kills, reason, None, "turbo")
        if c["liq"] < F["liq_min"]:
            _kill(kills, "liquidity_too_low", round(c["liq"]), f"<{F['liq_min']}")
        if v1 < F["vol1h_kill"]:
            _kill(kills, "vol1h_too_low", round(v1), f"<{F['vol1h_kill']}")
        elif F.get("vol1h_penalty_below") and v1 < F["vol1h_penalty_below"]:
            pts = 12 if v1 < 8_000 else 6
            _pen(pens, "vol1h_soft", round(v1), f"<{F['vol1h_penalty_below']}", pts)
        if F.get("liq_mcap_min") and c.get("mcap") and c["liq"] / c["mcap"] < F["liq_mcap_min"]:
            _kill(kills, "liq_mcap_too_low", round(c["liq"] / c["mcap"], 3), f"<{F['liq_mcap_min']}")
        if F.get("chase_h1_max") is not None and ch1 > F["chase_h1_max"]:
            _kill(kills, "chasing_pump_h1", ch1, f">{F['chase_h1_max']}%")
        if F.get("young_dex_min_age_h") and c.get("dex") in F.get("young_dexes", ()) and c["age_h"] < F["young_dex_min_age_h"]:
            _kill(kills, "too_young_launchpad_pair", round(c["age_h"], 2), f"<{F['young_dex_min_age_h']}h on {c.get('dex')}")
        if ch1 > F["pump1h_max"]:
            if F["pump_is_kill"]:
                _kill(kills, "already_pumped_gt80pct_1h", ch1, f">{F['pump1h_max']}%")
            else:
                _pen(pens, "already_pumped_gt80pct_1h", ch1, f">{F['pump1h_max']}%", 10)

        facts = {}
        if not kills:
            cap = F.get("rugcheck_cap_per_cycle")
            cached = _cache.get(c["mint"])
            have_cache = cached and time.time() - cached[0] < _cache_s()
            rep = rugcheck(c["mint"], cap=cap)
            if rep is None and c["mint"] in _budget_skips and not have_cache:
                jsonl("filter_defer", {"cycle": cycle, "mint": c["mint"], "pair": c["pair"], "symbol": c["symbol"], "reason": "rugcheck_budget"})
                continue
            if rep is None and F["fail_closed"]:
                # strict: still try RPC via onchain_facts, then fail closed on missing fields
                facts = onchain_facts(c, None)
                if facts.get("source") is None:
                    _kill(kills, "data_unavailable:rugcheck_and_rpc", None, "fail_closed")
                else:
                    _apply_onchain(F, c, facts, kills, pens)
            elif rep is None and not F["fail_closed"]:
                # agressif: try RPC for mint/freeze only when RugCheck failed (not budget-skipped)
                facts = onchain_facts(c, None)
                if facts.get("source") is None:
                    if F["mint_freeze_fail_closed"]:
                        _kill(kills, "data_unavailable:rugcheck_and_rpc", None, "fail_closed")
                    else:
                        _pen(pens, "data_unavailable:rugcheck_and_rpc", None, "penalty", 12)
                else:
                    _apply_onchain(F, c, facts, kills, pens)
            else:
                facts = onchain_facts(c, rep)
                _apply_onchain(F, c, facts, kills, pens)

        if kills:
            for k in kills:
                row = {"cycle": cycle, "ts": now_iso(), "mint": c["mint"], "pair": c["pair"], "symbol": c["symbol"], **k}
                kill_rows.append(row)
                jsonl("filter_kills", row)
        else:
            s = {**c, "facts": facts, "penalties": pens, "penalty_pts": sum(p["points"] for p in pens)}
            survivors.append(s)
            jsonl("filter_pass", {"cycle": cycle, "mint": c["mint"], "pair": c["pair"], "symbol": c["symbol"], "facts": facts, "penalties": pens})
    return survivors, kill_rows
