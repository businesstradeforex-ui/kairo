"""Live orders. Off unless the server AND the account opt in.

Every real order needs a one-time confirmation token and the phrase CONFIRMER.
Hard caps (env) cannot be raised from the API. A kill switch blocks everything.
Paper trading does not go through this module.
"""
import hashlib, json, os, time, urllib.parse, urllib.request
import common, connectors, webauth

def master_on():
    return os.environ.get("KAIRO_LIVE_ENABLED", "0") == "1"

def hard_order_cap():
    return float(os.environ.get("KAIRO_LIVE_MAX_ORDER_USD", "50"))

def hard_daily_cap():
    return float(os.environ.get("KAIRO_LIVE_MAX_DAILY_USD", "200"))

def global_kill_path():
    return os.path.join(common.BASE, "kill_switch.on")

def killed(user_row):
    return bool(user_row["kill_switch"]) or os.path.exists(global_kill_path())

def set_global_kill(on):
    p = global_kill_path()
    if on:
        with open(p, "w", encoding="utf-8") as f:
            f.write(common.now_iso() + "\n")
    elif os.path.exists(p):
        os.remove(p)

def blockers(user_row):
    reasons = []
    if not master_on():
        reasons.append("trading réel désactivé sur ce serveur (KAIRO_LIVE_ENABLED n'est pas à 1)")
    if not user_row["live_enabled"]:
        reasons.append("ce compte n'a pas activé le trading réel")
    if killed(user_row):
        reasons.append("kill switch actif")
    return reasons

def opt_in(user_id, enabled):
    c = webauth.wdb()
    c.execute("UPDATE users SET live_enabled=? WHERE id=?", (1 if enabled else 0, user_id))
    c.commit(); c.close()

def set_kill_user(user_id, on):
    c = webauth.wdb()
    c.execute("UPDATE users SET kill_switch=? WHERE id=?", (1 if on else 0, user_id))
    c.commit(); c.close()

def set_caps(user_id, order_usd, daily_usd):
    order_usd = min(float(order_usd), hard_order_cap())
    daily_usd = min(float(daily_usd), hard_daily_cap())
    if order_usd <= 0 or daily_usd <= 0 or order_usd > daily_usd:
        raise ValueError("plafonds invalides")
    c = webauth.wdb()
    c.execute("UPDATE users SET live_max_order=?, live_max_daily=? WHERE id=?", (order_usd, daily_usd, user_id))
    c.commit(); c.close()
    return {"live_max_order": order_usd, "live_max_daily": daily_usd}

def _daily_spent(c, user_id):
    import datetime
    day = datetime.datetime.now().astimezone().date().isoformat()
    rows = c.execute(
        "SELECT detail FROM audit WHERE actor=? AND action='live_order' AND outcome='executed' AND ts LIKE ?",
        (str(user_id), day + "%"),
    ).fetchall()
    total = 0.0
    for r in rows:
        try:
            total += float(json.loads(r["detail"]).get("usd") or 0)
        except Exception:
            pass
    return total

def preview(user_row, kind, symbol, side, usd):
    why = blockers(user_row)
    if why:
        raise ValueError("; ".join(why))
    if kind not in ("kraken", "binance", "coinbase"):
        raise ValueError("ce connecteur ne passe pas d'ordre réel")
    if side not in ("buy", "sell"):
        raise ValueError("side : buy ou sell")
    usd = float(usd)
    if usd <= 0 or usd > min(float(user_row["live_max_order"]), hard_order_cap()):
        raise ValueError("montant au-dessus du plafond par ordre")
    if not connectors.secrets_for(user_row["id"], kind):
        raise ValueError("connecteur non relié")
    c = webauth.wdb()
    spent = _daily_spent(c, user_row["id"])
    c.close()
    if spent + usd > min(float(user_row["live_max_daily"]), hard_daily_cap()):
        raise ValueError("plafond journalier atteint")
    payload = {"kind": kind, "symbol": str(symbol)[:32], "side": side, "usd": round(usd, 2)}
    tok = __import__("secrets").token_urlsafe(24)
    c = webauth.wdb()
    c.execute("INSERT INTO live_confirms(tok_hash,user_id,payload,created,used) VALUES(?,?,?,?,0)",
              (hashlib.sha256(tok.encode()).hexdigest(), user_row["id"], json.dumps(payload), time.time()))
    c.commit(); c.close()
    return {"confirm_token": tok, "expires_s": 120, "order": payload,
            "phrase": "CONFIRMER",
            "warning_fr": "Ordre réel. Vérifiez le montant. Le papier reste le mode par défaut."}

def execute(user_row, token, phrase, transport=None):
    if phrase != "CONFIRMER":
        raise ValueError("confirmation requise : envoyez phrase=CONFIRMER")
    why = blockers(user_row)
    if why:
        raise ValueError("; ".join(why))
    c = webauth.wdb()
    h = hashlib.sha256((token or "").encode()).hexdigest()
    row = c.execute("SELECT * FROM live_confirms WHERE tok_hash=?", (h,)).fetchone()
    if not row or row["used"] or row["user_id"] != user_row["id"] or time.time() - row["created"] > 120:
        c.close()
        raise ValueError("confirmation expirée ou invalide")
    c.execute("UPDATE live_confirms SET used=1 WHERE tok_hash=?", (h,))
    c.commit()
    payload = json.loads(row["payload"])
    c.close()
    secrets = connectors.secrets_for(user_row["id"], payload["kind"])
    result = _dispatch(payload, secrets, transport)
    return {"ok": True, "result": result, "order": payload}

def _dispatch(payload, secrets, transport):
    kind = payload["kind"]
    if kind == "kraken":
        return _kraken(payload, secrets, transport)
    if kind == "binance":
        return _signed_hint(payload, "binance", transport)
    if kind == "coinbase":
        return _signed_hint(payload, "coinbase", transport)
    raise ValueError("connecteur sans ordre réel")

def _kraken(payload, secrets, transport):
    nonce = str(int(time.time() * 1000))
    data = urllib.parse.urlencode({
        "nonce": nonce,
        "ordertype": "market",
        "type": payload["side"],
        "volume": f"{payload['usd']:.2f}",
        "pair": payload["symbol"],
        "oflags": "viqc",  # volume in quote currency when the pair supports it
    })
    path = "/0/private/AddOrder"
    import base64, hmac
    digest = hashlib.sha256((nonce + data).encode()).digest()
    sig = hmac.new(base64.b64decode(secrets["api_secret"]), path.encode() + digest, hashlib.sha512).digest()
    headers = {"API-Key": secrets["api_key"], "API-Sign": base64.b64encode(sig).decode(),
               "Content-Type": "application/x-www-form-urlencoded"}
    url = "https://api.kraken.com" + path
    send = transport or _http
    return send(url, data.encode(), headers)

def _signed_hint(payload, venue, transport):
    """Binance and Coinbase use their own signing schemes. The call is still gated above.
    Without a transport override this posts nothing until a venue module is filled in:
    we refuse rather than send a half-signed order."""
    if transport is None:
        raise ValueError(f"{venue} : connecteur enregistré, envoi réel non activé dans cette version (Kraken est branché). Aucun ordre n'a été envoyé.")
    return transport(venue, payload, {})

def _http(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)
