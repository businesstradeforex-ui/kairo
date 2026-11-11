"""External accounts. Public wallet addresses only for Phantom and Solflare.

API secrets (Kraken, Binance, Coinbase) are encrypted at rest and never returned.
A private key, seed phrase or mnemonic is rejected. Adding a connector does not
enable live trading.
"""
import json, re
import base58
import webauth
from crypto import decrypt, encrypt

SECRET_NAMES = re.compile(r"private|seed|mnemonic|phrase|secret_key", re.I)
SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

CONNECTORS = {
    "phantom": {"secrets": False, "live": False, "label_fr": "Phantom (adresse publique)"},
    "solflare": {"secrets": False, "live": False, "label_fr": "Solflare (adresse publique)"},
    "kraken": {"secrets": True, "live": True, "label_fr": "Kraken (clé API, sans retrait)"},
    "binance": {"secrets": True, "live": True, "label_fr": "Binance (clé API, sans retrait)"},
    "coinbase": {"secrets": True, "live": True, "label_fr": "Coinbase (clé API, sans retrait)"},
    "jupiter": {"secrets": False, "live": False, "label_fr": "Jupiter (cotations publiques)"},
}

def _reject_secrets(payload):
    for k, v in (payload or {}).items():
        if SECRET_NAMES.search(k) or (isinstance(v, str) and SECRET_NAMES.search(v[:80]) and " " in v and len(v.split()) >= 12):
            raise ValueError("refusé : jamais de clé privée, de seed ou de phrase secrète")

def _sol_address(addr):
    addr = (addr or "").strip()
    if not SOL_RE.match(addr):
        raise ValueError("adresse Solana invalide")
    try:
        raw = base58.b58decode(addr)
    except Exception as e:
        raise ValueError("adresse Solana invalide") from e
    if len(raw) != 32:
        raise ValueError("adresse Solana invalide")
    return addr

def list_for(user_id):
    c = webauth.wdb()
    rows = []
    for r in c.execute("SELECT id, kind, label, public_json, created FROM connectors WHERE user_id=? ORDER BY id", (user_id,)):
        pub = json.loads(r["public_json"] or "{}")
        rows.append({"id": r["id"], "kind": r["kind"], "label": r["label"], "public": pub,
                     "created": r["created"], "label_fr": CONNECTORS.get(r["kind"], {}).get("label_fr", r["kind"])})
    c.close()
    return rows

def upsert(user_id, kind, payload):
    if kind not in CONNECTORS:
        raise ValueError("connecteur inconnu")
    _reject_secrets(payload)
    spec = CONNECTORS[kind]
    public, secret = {}, None
    if kind in ("phantom", "solflare"):
        public["address"] = _sol_address(payload.get("address"))
    elif kind == "jupiter":
        public["mode"] = "quotes-only"
    elif spec["secrets"]:
        key = (payload.get("api_key") or "").strip()
        sec = (payload.get("api_secret") or "").strip()
        if len(key) < 8 or len(key) > 200 or len(sec) < 8 or len(sec) > 400:
            raise ValueError("clé API invalide")
        if SECRET_NAMES.search(key):
            raise ValueError("refusé : ceci ressemble à une clé privée")
        public = {"key_last4": key[-4:], "withdrawal": False,
                  "advice_fr": "Utilisez une clé sans permission de retrait."}
        secret = encrypt(json.dumps({"api_key": key, "api_secret": sec}))
    c = webauth.wdb()
    c.execute(
        """INSERT INTO connectors(user_id,kind,label,public_json,secret_blob,created)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(user_id, kind) DO UPDATE SET
             public_json=excluded.public_json, secret_blob=excluded.secret_blob, created=excluded.created""",
        (user_id, kind, CONNECTORS[kind]["label_fr"], json.dumps(public), secret, __import__("common").now_iso()),
    )
    c.commit(); c.close()
    return public

def delete(user_id, kind):
    c = webauth.wdb()
    c.execute("DELETE FROM connectors WHERE user_id=? AND kind=?", (user_id, kind))
    c.commit(); c.close()

def secrets_for(user_id, kind):
    c = webauth.wdb()
    r = c.execute("SELECT secret_blob FROM connectors WHERE user_id=? AND kind=?", (user_id, kind)).fetchone()
    c.close()
    if not r or not r["secret_blob"]:
        return None
    return json.loads(decrypt(r["secret_blob"]))
