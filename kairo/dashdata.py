"""Dashboard backend — version web (stdlib only). Endpoints JSON en lecture sur desk.db/state.json + interface statique.
Accès : page de connexion (identifiant + mot de passe, session HttpOnly/SameSite=Strict). API agent : jeton agent_token.txt.
Port : DESK_PORT (8787 par défaut), écoute sur DESK_HOST (127.0.0.1 par défaut ; mettre 0.0.0.0 en Docker)."""
import json, os, sqlite3

import common
CODE_DIR = os.path.dirname(os.path.abspath(__file__))

def _base():
    return common.data_dir()

UI_DIR = os.environ.get("MEMEDESK_UI_DIR", "")

def static_dir():
    if UI_DIR and os.path.isfile(os.path.join(UI_DIR, "static", "index.html")):
        return os.path.join(os.path.abspath(UI_DIR), "static")
    return os.path.join(CODE_DIR, "static")

REASONS_FR = {
    "liquidity_lt_40k": "Liquidité < 40 k$",
    "liquidity_too_low": "Liquidité trop faible",
    "vol1h_lt_50k": "Volume 1 h < 50 k$",
    "vol1h_too_low": "Volume 1 h trop faible",
    "vol1h_soft": "Volume 1 h faible (pénalité)",
    "already_pumped_gt80pct_1h": "Déjà +80 % en 1 h",
    "mint_authority_not_revoked": "Mint authority non révoquée",
    "freeze_authority_not_revoked": "Freeze authority non révoquée",
    "lp_not_burned_or_locked": "LP ni brûlée ni verrouillée",
    "top10_gt_25pct": "Top 10 détenteurs > 25 %",
    "top10_high": "Top 10 élevé",
    "top10_extreme": "Top 10 extrême",
    "dev_holding_gt_3pct": "Dev détient > 3 %",
    "dev_holding_high": "Part du dev élevée",
    "dev_holding_extreme": "Part du dev extrême",
    "dev_past_rugs": "Dev avec rugs passés",
    "bundled_launch_gt_10pct": "Lancement bundlé > 10 %",
    "bundled_launch_high": "Lancement bundlé élevé",
    "bundled_launch_extreme": "Lancement bundlé extrême",
    "token_rugged": "Token signalé rugged",
    "liq_mcap_too_low": "Liquidité / mcap < 10 %",
    "chasing_pump_h1": "Déjà +40 % en 1 h (pas de chasse)",
    "too_young_launchpad_pair": "Paire pump trop jeune (< 3 h)",
    "data_unavailable:rugcheck_and_rpc": "Données indisponibles : RugCheck + RPC",
    "data_unavailable:mint_authority": "Données indisponibles : mint authority",
    "data_unavailable:freeze_authority": "Données indisponibles : freeze authority",
    "data_unavailable:lp_lock": "Données indisponibles : verrouillage LP",
    "data_unavailable:top10": "Données indisponibles : top 10",
    "data_unavailable:dev_holding": "Données indisponibles : part du dev",
    "data_unavailable:dev_past_rugs": "Données indisponibles : historique du dev",
    "data_unavailable:bundle": "Données indisponibles : bundle",
}
EXIT_FR = {"stop_loss": "Stop-loss -6 %", "trailing_stop": "Trailing stop (6 % sous le pic)",
           "time_exit_flat": "Sortie temps (position plate)", "partial_tp": "Take-profit partiel +15 %",
           "stop_breakeven": "Stop au breakeven"}
COMP_FR = {"momentum": "Momentum", "unique_buyers": "Acheteurs uniques (proxy)", "buy_sell": "Ratio achats/ventes",
           "holder_growth": "Croissance des détenteurs", "liq_mcap": "Liquidité / mcap", "smart_wallets": "Smart wallets (désactivé)"}
TRIGGER_FR = {"score": "Score", "signal_momentum": "Signal momentum 5 min",
              "signal_volume_spike": "Signal spike de volume", "signal_breakout": "Signal cassure",
              "setup_pullback": "Setup pullback", "setup_breakout": "Cassure confirmée",
              "setup_ema_vwap_pullback": "Repli EMA/VWAP repris"}
STATUS_FR = {"running": "en cours", "idle": "en attente", "monitoring": "surveillance"}

def _agent_fr():
    from config import cfg
    C = cfg(); S, A, E, R = C["scout"], C["analyst"], C["executor"], C["risk"]
    age = f"{S['age_min_h']*60:.0f} min–{S['age_max_h']:.0f} h" if S["age_min_h"] < 1 else f"{S['age_min_h']:.0f}–{S['age_max_h']:.0f} h"
    filt = "Élimine surtout mint/freeze et la liquidité trop faible ; le reste est une pénalité" if C["filter"]["soft_as_penalty"] else "Élimine les tokens dangereux (sécurité on-chain, liquidité, volume)"
    sig = " ou signal rapide" if A["signals_enabled"] else ""
    te = f", sortie temps si plat après {int(R['time_exit_s']//60)} min" if R.get("time_exit_s") else ""
    return {"scout": f"Repère les paires Solana {age}, mcap {S['mcap_min']/1e3:.0f} k$–{S['mcap_max']/1e6:.0f} M$",
            "filter": filt,
            "analyst": f"Note 0–100, seuls les ≥ {A['pass_score']}{sig} passent",
            "executor": f"Ordres papier, {int(E['min_frac']*100)}–{int(E['max_frac']*100)} % du capital, max {E['max_open']} positions",
            "risk": f"Stop -6 % avant entrée, trailing après +12 %{te}",
            "logger": "Journalise kills, scores, trades, PnL"}

AGENT_FR = _agent_fr()  # refreshed in config()/agents() as well

def trigger_fr(raw):
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).replace(";", ",").split(",") if p.strip()]
    return " · ".join(TRIGGER_FR.get(p, p) for p in parts)

def con():
    c = sqlite3.connect(f"file:{os.path.join(_base(), 'desk.db')}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def state():
    try:
        with open(os.path.join(_base(), "state.json")) as f:
            return json.load(f)
    except Exception:
        return {}

def q(sql, args=()):
    c = con()
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()

def _kv(key):
    try:
        rows = q("SELECT v FROM kv WHERE k=?", (key,))
        return json.loads(rows[0]["v"]) if rows else None
    except Exception:
        return None

def summary():
    s = state()
    if not s.get("equity"):
        # Before the first cycle writes state.json, the book already lives in kv.
        s = dict(s)
        fx = _kv("session_eurusd") or _kv("eurusd") or 1.08
        if isinstance(fx, dict):
            fx = fx.get("rate") or 1.08
        bank = _kv("bankroll_usd")
        cash = _kv("cash")
        s["eurusd"] = float(fx)
        s["bankroll"] = float(bank if bank is not None else (cash if cash is not None else 10000))
        s["bankroll_eur"] = float(_kv("bankroll_eur") or (s["bankroll"] / s["eurusd"]))
        s["equity"] = float(cash if cash is not None else s["bankroll"])
        sess = _kv("session") or {}
        s["session"] = sess
        s.setdefault("profile", None)
    closed = q("""SELECT p.id, p.pnl_usd + COALESCE((SELECT SUM(x.pnl_usd) FROM partial_exits x WHERE x.position_id=p.id), 0) AS pnl_usd
                  FROM positions p WHERE p.status='closed'""")
    partial_open = q("""SELECT COALESCE(SUM(x.pnl_usd),0) v FROM partial_exits x JOIN positions p ON p.id=x.position_id WHERE p.status='open'""")[0]["v"]
    wins = sum(1 for r in closed if (r["pnl_usd"] or 0) > 0)
    tot = q("""SELECT (SELECT COUNT(DISTINCT mint) FROM candidates) scanned, (SELECT COUNT(*) FROM candidates) scanned_rows,
               (SELECT COUNT(DISTINCT mint) FROM kills) killed_tokens, (SELECT COUNT(*) FROM kills) kill_rows,
               (SELECT COUNT(*) FROM scores) scores, (SELECT COUNT(*) FROM scores WHERE passed=1) passes,
               (SELECT COUNT(*) FROM positions) trades, (SELECT COUNT(*) FROM positions WHERE status='open') open_n,
               (SELECT MAX(id) FROM cycles) cycle""")[0]
    bank = float(s.get("bankroll") or 10000.0)
    fx = float(s.get("eurusd") or 1.0)
    bank_eur = float(s.get("bankroll_eur") or bank / fx)
    eq = s.get("equity", bank)
    eq_eur = eq / fx
    return {**tot, "equity": eq, "cash": s.get("cash"), "bankroll": bank, "pnl_usd": eq - bank,
            "pnl_pct": (eq_eur / bank_eur - 1) * 100, "closed": len(closed), "wins": wins,
            "win_rate": (wins / len(closed) * 100) if closed else None,
            "realized_pnl": sum((r["pnl_usd"] or 0) for r in closed) + partial_open, "ts": s.get("ts"), "mode": "PAPIER",
            "profile": s.get("profile"), "profile_label": s.get("profile_label"),
            "eurusd": fx, "bankroll_eur": bank_eur, "equity_eur": eq_eur, "pnl_eur": eq_eur - bank_eur, "session": s.get("session")}

def agents():
    roles = _agent_fr()
    s = state().get("agents") or {}
    order = ["scout", "filter", "analyst", "executor", "risk", "logger"]
    return [{"id": a, "name": a.capitalize(), "role_fr": roles[a], **(s.get(a) or {}),
             "status_fr": STATUS_FR.get((s.get(a) or {}).get("status"), "—"),
             "handoff_to": order[i + 1] if i + 1 < len(order) else None} for i, a in enumerate(order)]

def _pass_label():
    from config import cfg
    A = cfg()["analyst"]
    return f"score ≥ {A['pass_score']}" + (" ou signal" if A.get("signals_enabled") else "")

def handoffs():
    c = q("SELECT * FROM cycles ORDER BY id DESC LIMIT 1")
    if not c: return []
    c = c[0]
    return [{"from": "scout", "to": "filter", "count": c["scanned"], "label_fr": "candidats"},
            {"from": "filter", "to": "analyst", "count": c["scored"], "label_fr": "survivants"},
            {"from": "analyst", "to": "executor", "count": c["passed"], "label_fr": _pass_label()},
            {"from": "executor", "to": "risk", "count": c["entries"], "label_fr": "ordres papier"},
            {"from": "risk", "to": "logger", "count": c["exits"], "label_fr": "sorties"},
            {"cycle": c["id"], "ts": c["ts"]}]

def kills(limit=100):
    rows = q("SELECT * FROM kills ORDER BY rowid DESC LIMIT ?", (limit,))
    for r in rows:
        r["reason_fr"] = REASONS_FR.get(r["reason"], r["reason"])
    return rows

def kills_by_reason():
    rows = q("SELECT reason, COUNT(DISTINCT mint) tokens, COUNT(*) occurrences FROM kills GROUP BY reason ORDER BY tokens DESC")
    for r in rows: r["reason_fr"] = REASONS_FR.get(r["reason"], r["reason"])
    return rows

def scores(limit=25):
    rows = q("""SELECT s.* FROM scores s JOIN (SELECT mint, MAX(rowid) rid FROM scores GROUP BY mint) m ON s.rowid=m.rid
                ORDER BY s.cycle DESC, s.score DESC LIMIT ?""", (limit,))
    for r in rows:
        r["components"] = json.loads(r["components"])
    return rows

def positions():
    o = q("SELECT * FROM positions WHERE status='open' ORDER BY id DESC")
    for r in o:
        lp = r["last_price"] or r["entry_price"]
        r["value_usd"] = lp * r["qty"]; r["pnl_usd"] = r["value_usd"] - r["cost_usd"]; r["pnl_pct"] = r["pnl_usd"] / r["cost_usd"] * 100
        r["trail_activation_price"] = r["entry_price"] * 1.12
    for r in o:
        r["trigger_fr"] = trigger_fr(r.get("entry_trigger"))
        r["tp1_done"] = int(r.get("tp1_done") or 0)
    c = q("SELECT * FROM positions WHERE status='closed' ORDER BY id DESC LIMIT 50")
    for r in c:
        r["exit_reason_fr"] = EXIT_FR.get(r["exit_reason"], r["exit_reason"])
        r["trigger_fr"] = trigger_fr(r.get("entry_trigger"))
    return {"open": o, "closed": c}

def equity_curve():
    return q("SELECT ts, cash, open_value, equity, n_open FROM (SELECT rowid, * FROM equity ORDER BY rowid DESC LIMIT 2000) ORDER BY rowid")

def cycles(limit=30):
    return q("SELECT * FROM cycles ORDER BY id DESC LIMIT ?", (limit,))

def labels():
    return {"reasons": REASONS_FR, "exits": EXIT_FR, "components": COMP_FR, "agents": _agent_fr(),
            "status": STATUS_FR, "triggers": TRIGGER_FR}

import time, urllib.request
_ohlcv_cache = {}

def _short_fr(reason, value):
    v = value
    try: v = json.loads(value) if isinstance(value, str) else value
    except Exception: pass
    def k(x):
        try: x = float(x)
        except Exception: return str(x)
        return f"${x/1e6:.1f}M" if x >= 1e6 else f"${x/1e3:.0f}K"
    m = {"liquidity_lt_40k": lambda: f"liq faible {k(v)}", "liquidity_too_low": lambda: f"liq faible {k(v)}",
         "vol1h_lt_50k": lambda: f"volume 1h {k(v)}", "vol1h_too_low": lambda: f"volume 1h {k(v)}", "vol1h_soft": lambda: f"volume 1h {k(v)}",
         "already_pumped_gt80pct_1h": lambda: f"déjà +{float(v):.0f} % en 1h", "top10_gt_25pct": lambda: f"top 10 {float(v):.0f} %",
         "top10_high": lambda: f"top 10 {float(v):.0f} %", "top10_extreme": lambda: f"top 10 {float(v):.0f} %",
         "dev_holding_gt_3pct": lambda: f"dev {float(v):.1f} %", "dev_holding_high": lambda: f"dev {float(v):.1f} %",
         "dev_holding_extreme": lambda: f"dev {float(v):.1f} %",
         "bundled_launch_gt_10pct": lambda: f"bundle {float(v):.0f} %", "bundled_launch_high": lambda: f"bundle {float(v):.0f} %",
         "bundled_launch_extreme": lambda: f"bundle {float(v):.0f} %",
         "lp_not_burned_or_locked": lambda: f"LP verrouillée {float(v):.0f} %", "mint_authority_not_revoked": lambda: "mint actif",
         "freeze_authority_not_revoked": lambda: "freeze actif", "dev_past_rugs": lambda: "dev déjà rug",
         "token_rugged": lambda: "token rugged"}
    try: return m[reason]()
    except Exception: return REASONS_FR.get(reason, reason).lower()

def _meta():
    return {r["mint"]: r for r in q("SELECT mint, symbol, icon, pair FROM token_meta")} if _has("token_meta") else {}

def _has(t):
    return bool(q("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)))

def activity(limit=60, include_kills=True):
    meta = _meta(); ev = []
    for p in q("SELECT * FROM positions ORDER BY id DESC LIMIT 200"):
        icon = (meta.get(p["mint"]) or {}).get("icon")
        trig = trigger_fr(p.get("entry_trigger"))
        detail = "score %.0f" % (p["score"] or 0)
        if trig:
            detail += " · " + trig
        ev.append({"type": "buy", "ts": p["entry_ts"], "symbol": p["symbol"], "mint": p["mint"], "icon": icon, "agent": "Executor",
                   "title_fr": f"Acheté {p['symbol']}", "amount": p["cost_usd"], "sub_fr": trig, "pct_capital": None, "id": f"b{p['id']}",
                   "detail": detail, "entry_trigger": p.get("entry_trigger"), "trigger_fr": trig})
        if p["status"] == "closed":
            stopped = p["exit_reason"] == "stop_loss"
            ev.append({"type": "stop" if stopped else "sell", "ts": p["exit_ts"], "symbol": p["symbol"], "mint": p["mint"], "icon": icon,
                       "agent": "Risk", "title_fr": f"{'Stoppé' if stopped else 'Vendu'} {p['symbol']}",
                       "detail": EXIT_FR.get(p["exit_reason"], p["exit_reason"] or ""), "amount": p["pnl_usd"], "pnl_pct": p["pnl_pct"], "id": f"s{p['id']}"})
    if _has("partial_exits"):
        for u in q("SELECT * FROM partial_exits ORDER BY id DESC LIMIT 200"):
            ev.append({"type": "sell", "ts": u["ts"], "symbol": u["symbol"], "mint": u["mint"],
                       "icon": (meta.get(u["mint"]) or {}).get("icon"), "agent": "Risk",
                       "title_fr": f"TP partiel {u['symbol']}",
                       "detail": EXIT_FR.get(u["reason"], u["reason"] or "take-profit partiel"),
                       "amount": u["pnl_usd"], "pnl_pct": (u["pnl_usd"] / (u["proceeds_usd"] - u["pnl_usd"]) * 100) if u["proceeds_usd"] and (u["proceeds_usd"] - u["pnl_usd"]) else None,
                       "id": f"p{u['id']}"})
    if include_kills:
        for k in q("""SELECT k.* FROM kills k JOIN (SELECT mint, cycle, MIN(rowid) rid FROM kills GROUP BY mint, cycle) f ON k.rowid=f.rid
                      ORDER BY k.rowid DESC LIMIT ?""", (limit,)):
            ev.append({"type": "kill", "ts": k["ts"], "symbol": k["symbol"], "mint": k["mint"], "icon": (meta.get(k["mint"]) or {}).get("icon"),
                       "agent": "Filter", "title_fr": f"Éliminé {k['symbol']}", "detail": _short_fr(k["reason"], k["value"]),
                       "reason_fr": REASONS_FR.get(k["reason"], k["reason"]), "id": f"k{k['cycle']}{k['mint']}"})
    ev.sort(key=lambda e: e["ts"] or "", reverse=True)
    return ev[:limit]

def scout_feed():
    last = q("SELECT MAX(id) c FROM cycles")[0]["c"]
    if not last: return {"lines": [], "pass_lines": []}
    lines = [{"symbol": k["symbol"], "text_fr": _short_fr(k["reason"], k["value"]), "kind": "kill"}
             for k in q("SELECT * FROM kills WHERE cycle=? GROUP BY mint ORDER BY rowid DESC LIMIT 8", (last,))]
    passes = [{"symbol": s["symbol"], "text_fr": "validé", "kind": "pass", "score": s["score"]} for s in q("SELECT * FROM scores WHERE cycle=?", (last,))]
    return {"lines": (passes + lines)[:8], "cycle": last}

def token(mint):
    t = q("SELECT * FROM token_meta WHERE mint=?", (mint,))
    t = t[0] if t else {"mint": mint}
    t["snap"] = json.loads(t.get("snap") or "{}")
    pos = q("SELECT * FROM positions WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,))
    if pos:
        pos[0]["trigger_fr"] = trigger_fr(pos[0].get("entry_trigger"))
        if pos[0].get("exit_reason"):
            pos[0]["exit_reason_fr"] = EXIT_FR.get(pos[0]["exit_reason"], pos[0]["exit_reason"])
    t["position"] = pos[0] if pos else None
    sc = q("SELECT * FROM scores WHERE mint=? ORDER BY rowid DESC LIMIT 1", (mint,))
    if sc: sc[0]["components"] = json.loads(sc[0]["components"])
    t["score"] = sc[0] if sc else None
    last_score_cycle = sc[0]["cycle"] if sc else -1
    t["kills"] = [] if q("SELECT MAX(cycle) c FROM kills WHERE mint=?", (mint,))[0]["c"] is not None and q("SELECT MAX(cycle) c FROM kills WHERE mint=?", (mint,))[0]["c"] < last_score_cycle else [dict(k, reason_fr=REASONS_FR.get(k["reason"], k["reason"])) for k in q("SELECT * FROM kills WHERE mint=? AND cycle=(SELECT MAX(cycle) FROM kills WHERE mint=?)", (mint, mint))]
    h = q("SELECT holders FROM holders WHERE mint=? ORDER BY ts_epoch DESC LIMIT 1", (mint,))
    t["holders"] = h[0]["holders"] if h else (t["snap"].get("facts") or {}).get("holders")
    eq = state().get("equity", state().get("bankroll", 10000.0)); t["equity"] = eq
    return t

def ohlcv(pair, tf="minute", agg=5, mint=""):
    key = (pair, tf, agg, mint); hit = _ohlcv_cache.get(key)
    if hit and time.time() - hit[0] < 60: return hit[1]
    out = {"source": None, "candles": []}
    try:
        url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair}/ohlcv/{tf}?aggregate={agg}&limit=200&currency=usd" + (f"&token={mint}" if mint else "")
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "memedesk-paper/1.0"})
        d = json.load(urllib.request.urlopen(req, timeout=12))
        rows = d["data"]["attributes"]["ohlcv_list"]
        out = {"source": "geckoterminal", "candles": sorted([{"time": int(r[0]), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in rows], key=lambda c: c["time"])}
    except Exception as e:
        out["error"] = str(e)
    if not out["candles"] and _has("price_samples"):  # fallback: candles built from Risk's own price samples
        b = {}
        for r in q("SELECT ts_epoch, price FROM price_samples WHERE pair=? ORDER BY ts_epoch", (pair,)):
            t0 = int(r["ts_epoch"] // (agg * 60) * agg * 60)
            c = b.setdefault(t0, {"time": t0, "open": r["price"], "high": r["price"], "low": r["price"], "close": r["price"]})
            c["high"] = max(c["high"], r["price"]); c["low"] = min(c["low"], r["price"]); c["close"] = r["price"]
        out = {"source": "price_samples", "candles": list(b.values())}
    _ohlcv_cache[key] = (time.time(), out)
    return out

def config():
    from config import cfg, profile_name
    C = cfg(); S, F, A, E, R = C["scout"], C["filter"], C["analyst"], C["executor"], C["risk"]
    age = f"{S['age_min_h']*60:.0f} min – {S['age_max_h']:.0f} h" if S["age_min_h"] < 1 else f"{S['age_min_h']:.0f} h – {S['age_max_h']:.0f} h"
    if F["soft_as_penalty"]:
        filt = ["Mint / freeze authority non révoquée (élimination)", f"Liquidité < {F['liq_min']/1e3:.0f} k$ (élimination)",
                "Volume 1 h < 3 k$ (élimination) ; pénalité sous 20 k$", "LP, top 10, part du dev, bundle : pénalités (seuils durs seulement si extrême)",
                "Déjà +80 % en 1 h : pénalité, plus une élimination", "Token signalé rugged : élimination"]
        notes = ["Mint/freeze : données manquantes = élimination (ou report si budget RugCheck)",
                 "Autres données manquantes = pénalité, pas d'élimination automatique",
                 "LP : pénalité si < 50 % brûlée/verrouillée",
                 "Bundle ≈ réseaux d'initiés RugCheck (approximation)",
                 "Rugs passés du dev : pénalité (approximation RugCheck)"]
    else:
        def _k(x):
            return f"{x/1e3:.0f} k$" if x >= 1000 else str(x)
        filt = [
            "Mint / freeze authority non révoquée (élimination)",
            f"Liquidité < {_k(F['liq_min'])} (élimination)",
            f"Volume 1 h < {_k(F['vol1h_kill'])} (élimination)",
            f"LP brûlée/verrouillée < {F['lp_safe_min']:.0f} % (élimination)" if F.get("lp_is_kill") else f"LP < {F['lp_safe_min']:.0f} % : pénalité",
            f"Top 10 > {F['top10_max']:.0f} % (élimination)",
            f"Dev > {F['dev_max']:.0f} % (élimination)",
            f"Bundle / initiés > {F['bundle_max']:.0f} % (élimination)",
            "Dev avec rugs passés (élimination)" if F.get("dev_rugs_is_kill") else "Dev avec rugs passés : pénalité",
            "Déjà +80 % en 1 h (élimination)" if F.get("pump_is_kill") else "Déjà +80 % en 1 h : pénalité",
        ]
        notes = ["Données manquantes = élimination (fail-closed)", f"LP considérée sûre si ≥ {F['lp_safe_min']:.0f} % brûlée/verrouillée", "Bundle ≈ réseaux d'initiés RugCheck (approximation)", "Rugs passés du dev ≈ signaux RugCheck (approximation)"]
    te = f"sortie après {int(R['time_exit_s']//60)} min si le PnL est plat (±{R['flat_abs_pct']:.0f} %)" if R.get("time_exit_s") else "aucune"
    return {"mode": "PAPIER", "profile": profile_name(), "profile_label": C["label_fr"],
            "bankroll": state().get("bankroll", 10000), "bankroll_eur": state().get("bankroll_eur", 1000), "eurusd": state().get("eurusd"),
            "scout": {"age": age, "mcap": f"{S['mcap_min']/1e3:.0f} k$ – {S['mcap_max']/1e6:.0f} M$", "source": "DexScreener (+ découverte GeckoTerminal, Jupiter)"},
            "filter": filt, "filter_notes_fr": notes,
            "analyst": {"seuil": A["pass_score"], "signals": A["signals_enabled"], "signal_min": A["signal_min_score"],
                        "poids": {"Momentum": 23.5, "Acheteurs uniques (proxy nb d'achats)": 20, "Ratio achats/ventes": 20, "Croissance des détenteurs": 20, "Liquidité / mcap": 16.5, "Smart wallets": 0},
                        "note_fr": "Smart wallets : aucune source gratuite, poids 0, renormalisé"
                                   + (" · Signal uniquement si score ≥ %s" % A["signal_min_score"] if A["signals_enabled"] else "")
                                   + ((" · Setup requis (bougies 1 min) : tendance EMA9 > EMA21, repli vers EMA21/VWAP avec plus bas plus haut, reprise au-dessus d'EMA9 et du VWAP sur volume ≥ moyenne 10 ; ou cassure confirmée au-dessus du VWAP. Pression acheteuse : achats/ventes 5 min ≥ 1,1" if A.get("chart_confirm") else " · Setup requis : pullback après force ou cassure confirmée") if A.get("require_setup") else "")},
            "executor": {"max_par_trade": f"{int(E['min_frac']*100)}–{int(E['max_frac']*100)} % du capital (selon score/signal, max 8 %)",
                         "max_open": E["max_open"],
                         "fill": "prix DexScreener + slippage estimé (impact x/y + 0,25 % frais)"},
            "risk": {"stop": f"-{R['stop_pct']*100:g} % fixé avant l'entrée", "trailing": f"activé après +{R['trail_activate']*100:g} %, {R['trail_pct']*100:g} % sous le plus haut",
                     "sorties": "1/3 vendu à +15 % (stop au prix d'entrée), 1/3 à +30 %, le reste en trailing ; sortie max 4 h",
                     "surveillance": f"toutes les ~{C['risk_tick_s']} s", "time_exit": te},
            "cycle_s": C["cycle_s"]}

def intensif():
    try:
        with open(os.path.join(_base(), "intensif_state.json")) as f:
            d = json.load(f)
        d.pop("equity_curve_full", None)
        return d
    except Exception:
        return {}

def lessons():
    import learn
    try:
        rows = q("SELECT v FROM kv WHERE k='lessons'")
        les = json.loads(rows[0]["v"]) if rows else {}
        sym = {r["mint"]: r["symbol"] for r in q("SELECT DISTINCT mint, symbol FROM positions")}
        return {"profit": learn.lessons_fr(les, sym), "min_n": learn.MIN_N}
    except Exception as e:
        return {"profit": [], "error": str(e)}

ROUTES = {"/api/intensif": intensif, "/api/lessons": lessons, "/api/activity": activity, "/api/scout_feed": scout_feed, "/api/config": config, "/api/summary": summary, "/api/agents": agents, "/api/handoffs": handoffs, "/api/kills": kills,
          "/api/kills_by_reason": kills_by_reason, "/api/scores": scores, "/api/positions": positions,
          "/api/equity": equity_curve, "/api/cycles": cycles, "/api/labels": labels}

def everything():
    return {k.split("/")[-1]: f() for k, f in ROUTES.items()}

