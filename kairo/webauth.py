"""Accounts for Kairo.

- Password hashing: hashlib.scrypt (16-byte salt, N=2^14, r=8, p=1).
- Sessions: random token, only SHA-256 stored, cookie HttpOnly + SameSite=Lax.
  Lax (not Strict) so a top-level return from Google/Apple can finish login.
  State-changing requests still require a CSRF token.
- Roles: owner (private admin + remote assistant), user (own portfolio),
  viewer (read only), admin (legacy alias of user: can order, not owner).
- The first account is the owner, unless KAIRO_OWNER_EMAIL names someone else.
- Optional TOTP for password accounts. Magic links, Google, Apple and SIWS
  are enabled only when their configuration is present (SIWS needs no secret).
"""
import base64, hashlib, hmac, os, re, secrets, sqlite3, struct, time
import common
from crypto import decrypt, encrypt

DATA = common.BASE
WEB_DB = os.path.join(DATA, "web.db")
AGENT_TOKEN_FILE = os.path.join(DATA, "agent_token.txt")
SESSION_COOKIE = "kairo_session"
CSRF_COOKIE = "kairo_csrf"
SESSION_MAX_S = 30 * 86400
SESSION_IDLE_S = 7 * 86400
SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)
FAIL_WINDOW_S = 15 * 60
FAIL_MAX = 5
MAGIC_TTL_S = 15 * 60
SIWS_TTL_S = 10 * 60
OAUTH_TTL_S = 10 * 60
ROLES = ("owner", "user", "viewer", "admin")
SCOPES = ("read", "params", "orders", "ui", "live")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,24}$")
USER_RE = re.compile(r"^[A-Za-z0-9._-]{2,32}$")

def wdb():
    os.makedirs(DATA, exist_ok=True)
    c = sqlite3.connect(WEB_DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE,
        salt BLOB, pwhash BLOB, params TEXT,
        role TEXT NOT NULL DEFAULT 'user',
        created TEXT,
        totp_secret BLOB,
        totp_enabled INTEGER NOT NULL DEFAULT 0,
        live_enabled INTEGER NOT NULL DEFAULT 0,
        kill_switch INTEGER NOT NULL DEFAULT 0,
        live_max_order REAL NOT NULL DEFAULT 25,
        live_max_daily REAL NOT NULL DEFAULT 100,
        paper_eur REAL NOT NULL DEFAULT 1000
    );
    CREATE TABLE IF NOT EXISTS identities(
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        subject TEXT NOT NULL,
        UNIQUE(provider, subject)
    );
    CREATE TABLE IF NOT EXISTS sessions(
        tok_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created REAL, last_seen REAL, ip TEXT, csrf TEXT
    );
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY,
        ts TEXT, source TEXT, actor TEXT, raw TEXT, status TEXT,
        action TEXT, result TEXT, model TEXT, done_ts TEXT,
        user_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS audit(
        id INTEGER PRIMARY KEY, ts TEXT, source TEXT, actor TEXT, order_id INT,
        action TEXT, params TEXT, outcome TEXT, detail TEXT, ip TEXT
    );
    CREATE TABLE IF NOT EXISTS auth_fails(
        k TEXT PRIMARY KEY, hits TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS magic(
        tok_hash TEXT PRIMARY KEY, email TEXT, purpose TEXT, created REAL, used INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS oauth_state(
        state_hash TEXT PRIMARY KEY, provider TEXT, created REAL, used INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS siws(
        nonce_hash TEXT PRIMARY KEY, message TEXT, address TEXT, created REAL, used INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS totp_pending(
        tok_hash TEXT PRIMARY KEY, user_id INTEGER, created REAL
    );
    CREATE TABLE IF NOT EXISTS agent_tokens(
        id INTEGER PRIMARY KEY,
        name TEXT, prefix TEXT, tok_hash TEXT UNIQUE,
        scopes TEXT, created TEXT, revoked INTEGER NOT NULL DEFAULT 0, last_used TEXT
    );
    CREATE TABLE IF NOT EXISTS live_confirms(
        tok_hash TEXT PRIMARY KEY, user_id INTEGER, payload TEXT, created REAL, used INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS connectors(
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        label TEXT,
        public_json TEXT,
        secret_blob BLOB,
        created TEXT,
        UNIQUE(user_id, kind)
    );
    """)
    c.commit()
    return c

def audit(c, source, actor, order_id, action, params, outcome, detail="", ip=""):
    import json
    c.execute(
        "INSERT INTO audit(ts,source,actor,order_id,action,params,outcome,detail,ip) VALUES(?,?,?,?,?,?,?,?,?)",
        (common.now_iso(), source, actor, order_id, action,
         json.dumps(params, ensure_ascii=False, default=str)[:4000], outcome, str(detail)[:2000], ip or ""),
    )
    c.commit()

def _th(tok):
    return hashlib.sha256((tok or "").encode()).hexdigest()

def can_order(role):
    return role in ("owner", "user", "admin")

def is_owner(role):
    return role == "owner"

# ---------- passwords ----------
def hash_password(pw, salt=None):
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, maxmem=64 * 1024 * 1024, **SCRYPT)
    return salt, h

def _check_pw_len(pw):
    if not isinstance(pw, str) or len(pw) < 10 or len(pw) > 200:
        raise ValueError("mot de passe : 10 à 200 caractères")
    if "\x00" in pw:
        raise ValueError("mot de passe invalide")

def _valid_username(username):
    if not USER_RE.match(username or ""):
        raise ValueError("identifiant : 2 à 32 caractères (lettres, chiffres, . _ -)")

def _valid_email(email):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise ValueError("adresse e-mail invalide")
    return email

def user_count():
    c = wdb(); n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]; c.close(); return n

def owner_exists():
    c = wdb(); n = c.execute("SELECT COUNT(*) FROM users WHERE role='owner'").fetchone()[0]; c.close(); return n > 0

def _role_for_new(email, requested=None):
    if requested in ROLES and requested != "owner":
        return requested
    want = (os.environ.get("KAIRO_OWNER_EMAIL") or "").strip().lower()
    if requested == "owner":
        if owner_exists() and not (want and email and email == want):
            raise ValueError("un propriétaire existe déjà")
        return "owner"
    if want and email and email == want and not owner_exists():
        return "owner"
    if not want and user_count() == 0:
        return "owner"
    return "user"

def create_user(username, password=None, role=None, email=None):
    _valid_username(username)
    email_n = _valid_email(email) if email else None
    role = _role_for_new(email_n, role)
    salt = pwhash = None
    if password is not None:
        _check_pw_len(password)
        salt, pwhash = hash_password(password)
    c = wdb()
    try:
        cur = c.execute(
            """INSERT INTO users(username,email,salt,pwhash,params,role,created)
               VALUES(?,?,?,?,?,?,?)""",
            (username, email_n, salt, pwhash, "scrypt:n=16384,r=8,p=1" if password else "none",
             role, common.now_iso()),
        )
        c.commit()
        uid = cur.lastrowid
    finally:
        c.close()
    trading_dir_for({"id": uid, "role": role})
    return uid

def set_password(username, pw, role="user"):
    """Create or reset a password account. Used by manage.py."""
    _check_pw_len(pw)
    if role not in ROLES:
        raise ValueError("rôle inconnu")
    _valid_username(username)
    salt, h = hash_password(pw)
    c = wdb()
    row = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if row:
        if role == "owner" and owner_exists():
            existing = c.execute("SELECT role FROM users WHERE id=?", (row["id"],)).fetchone()
            if existing["role"] != "owner":
                raise ValueError("un propriétaire existe déjà")
        c.execute("UPDATE users SET salt=?, pwhash=?, params=?, role=? WHERE id=?",
                  (salt, h, "scrypt:n=16384,r=8,p=1", role, row["id"]))
        c.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
    else:
        if role == "owner" and owner_exists():
            c.close()
            raise ValueError("un propriétaire existe déjà")
        c.execute(
            "INSERT INTO users(username,salt,pwhash,params,role,created) VALUES(?,?,?,?,?,?)",
            (username, salt, h, "scrypt:n=16384,r=8,p=1", role, common.now_iso()),
        )
    c.commit(); c.close()

_DUMMY_SALT = os.urandom(16)

def find_user(login):
    login = (login or "").strip()
    if not login or len(login) > 254:
        return None
    c = wdb()
    try:
        return c.execute(
            "SELECT * FROM users WHERE username=? OR lower(email)=lower(?)",
            (login, login),
        ).fetchone()
    finally:
        c.close()

def check_password(username, pw):
    if not isinstance(pw, str) or len(pw) > 200 or len(pw) == 0:
        hash_password("invalid-password", _DUMMY_SALT)
        return False
    r = find_user(username)
    if not r or not r["pwhash"]:
        hash_password(pw, _DUMMY_SALT)
        return False
    _, h = hash_password(pw, r["salt"])
    return hmac.compare_digest(h, r["pwhash"])

def public_user(row):
    if not row:
        return None
    return {
        "id": row["id"], "username": row["username"], "email": row["email"],
        "role": row["role"], "can_order": can_order(row["role"]), "is_owner": is_owner(row["role"]),
        "totp_enabled": bool(row["totp_enabled"]), "live_enabled": bool(row["live_enabled"]),
        "kill_switch": bool(row["kill_switch"]),
        "live_max_order": row["live_max_order"], "live_max_daily": row["live_max_daily"],
        "paper_eur": row["paper_eur"],
    }

# ---------- lockout (persisted) ----------
def _load_hits(c, key, now):
    import json
    r = c.execute("SELECT hits FROM auth_fails WHERE k=?", (key,)).fetchone()
    hits = json.loads(r["hits"]) if r else []
    return [t for t in hits if now - t < FAIL_WINDOW_S]

def _save_hits(c, key, hits):
    import json
    c.execute("INSERT INTO auth_fails(k,hits) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET hits=excluded.hits",
              (key, json.dumps(hits)))
    c.commit()

def login_blocked(ip, username):
    now = time.time()
    c = wdb()
    try:
        for key in (f"ip:{ip}", f"u:{(username or '').lower()}"):
            hits = _load_hits(c, key, now)
            if len(hits) >= FAIL_MAX:
                return int(FAIL_WINDOW_S - (now - hits[0]))
        return 0
    finally:
        c.close()

def login_failed(ip, username):
    now = time.time()
    c = wdb()
    try:
        for key in (f"ip:{ip}", f"u:{(username or '').lower()}"):
            hits = _load_hits(c, key, now)
            hits.append(now)
            _save_hits(c, key, hits)
    finally:
        c.close()

def login_ok(ip, username):
    c = wdb()
    c.execute("DELETE FROM auth_fails WHERE k=?", (f"u:{(username or '').lower()}",))
    c.commit(); c.close()

# ---------- sessions ----------
def new_session(username, ip):
    row = find_user(username)
    if not row:
        raise ValueError("utilisateur introuvable")
    tok = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    c = wdb()
    now = time.time()
    c.execute("DELETE FROM sessions WHERE created < ? OR last_seen < ?", (now - SESSION_MAX_S, now - SESSION_IDLE_S))
    c.execute("INSERT INTO sessions(tok_hash,user_id,created,last_seen,ip,csrf) VALUES(?,?,?,?,?,?)",
              (_th(tok), row["id"], now, now, ip, csrf))
    c.commit(); c.close()
    return tok, csrf

def session_user(tok):
    if not tok:
        return None
    c = wdb()
    try:
        r = c.execute(
            """SELECT s.user_id, s.created, s.last_seen, s.csrf, u.*
               FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.tok_hash=?""",
            (_th(tok),)).fetchone()
        now = time.time()
        if not r or now - r["created"] > SESSION_MAX_S or now - r["last_seen"] > SESSION_IDLE_S:
            return None
        if now - r["last_seen"] > 60:
            c.execute("UPDATE sessions SET last_seen=? WHERE tok_hash=?", (now, _th(tok)))
            c.commit()
        info = public_user(r)
        info["csrf"] = r["csrf"]
        return info
    finally:
        c.close()

def end_session(tok):
    if tok:
        c = wdb(); c.execute("DELETE FROM sessions WHERE tok_hash=?", (_th(tok),)); c.commit(); c.close()

def csrf_ok(user, presented):
    if not user or not presented:
        return False
    return hmac.compare_digest(str(user.get("csrf") or ""), str(presented))

# ---------- per-user trading directory ----------
def trading_dir_for(row):
    multi = os.environ.get("KAIRO_MULTIUSER", "1") != "0"
    if (not multi) and row["role"] == "owner":
        path = common.BASE
    else:
        path = os.path.join(common.BASE, "users", str(row["id"]))
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "logs"), exist_ok=True)
    prof = os.path.join(path, "profile.txt")
    if not os.path.exists(prof):
        with open(prof, "w", encoding="utf-8") as f:
            f.write("profit\n")
    return path

def bind_user_id(uid):
    c = wdb()
    r = c.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
    c.close()
    if not r:
        raise ValueError("utilisateur introuvable")
    return common.bind_data_dir(trading_dir_for(r))

def bind_owner():
    c = wdb()
    r = c.execute("SELECT * FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone()
    c.close()
    if not r:
        return common.bind_data_dir(common.BASE)
    return common.bind_data_dir(trading_dir_for(r))

def trading_accounts():
    c = wdb()
    rows = list(c.execute("SELECT id, username, role FROM users WHERE role != 'viewer' ORDER BY id"))
    c.close()
    return [{"id": r["id"], "username": r["username"], "role": r["role"], "dir": trading_dir_for(r)} for r in rows]

def user_by_id(uid):
    c = wdb()
    r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return r

# ---------- TOTP (RFC 6238, SHA-1, 30s, 6 digits) ----------
def _hotp(secret, counter):
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF
    return f"{code % 1000000:06d}"

def totp_now(secret, step=30, skew=1):
    counter = int(time.time()) // step
    return {_hotp(secret, counter + d) for d in range(-skew, skew + 1)}

def totp_begin(user_id):
    secret = os.urandom(20)
    c = wdb()
    c.execute("UPDATE users SET totp_secret=?, totp_enabled=0 WHERE id=?",
              (encrypt(base64.b32encode(secret).decode()), user_id))
    c.commit(); c.close()
    b32 = base64.b32encode(secret).decode().rstrip("=")
    return b32

def totp_enable(user_id, code):
    c = wdb()
    r = c.execute("SELECT totp_secret, username FROM users WHERE id=?", (user_id,)).fetchone()
    if not r or not r["totp_secret"]:
        c.close()
        raise ValueError("lancez d'abord la configuration")
    secret = base64.b32decode(decrypt(r["totp_secret"]))
    if str(code).strip() not in totp_now(secret):
        c.close()
        raise ValueError("code incorrect")
    c.execute("UPDATE users SET totp_enabled=1 WHERE id=?", (user_id,))
    c.commit(); c.close()

def totp_disable(user_id, code):
    c = wdb()
    r = c.execute("SELECT totp_secret, totp_enabled FROM users WHERE id=?", (user_id,)).fetchone()
    if not r or not r["totp_enabled"]:
        c.close()
        return
    secret = base64.b32decode(decrypt(r["totp_secret"]))
    if str(code).strip() not in totp_now(secret):
        c.close()
        raise ValueError("code incorrect")
    c.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE id=?", (user_id,))
    c.commit(); c.close()

def totp_check_user(row, code):
    if not row["totp_enabled"]:
        return True
    secret = base64.b32decode(decrypt(row["totp_secret"]))
    return str(code or "").strip() in totp_now(secret)

def new_totp_pending(user_id):
    tok = secrets.token_urlsafe(24)
    c = wdb()
    c.execute("INSERT INTO totp_pending(tok_hash,user_id,created) VALUES(?,?,?)", (_th(tok), user_id, time.time()))
    c.commit(); c.close()
    return tok

def consume_totp_pending(tok, code):
    c = wdb()
    r = c.execute("SELECT * FROM totp_pending WHERE tok_hash=?", (_th(tok),)).fetchone()
    if not r or time.time() - r["created"] > 300:
        c.close()
        return None
    user = c.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
    if not user or not totp_check_user(user, code):
        c.close()
        return None
    c.execute("DELETE FROM totp_pending WHERE tok_hash=?", (_th(tok),))
    c.commit(); c.close()
    return user

# ---------- magic link ----------
def create_magic(email, purpose="login"):
    email = _valid_email(email)
    tok = secrets.token_urlsafe(32)
    c = wdb()
    c.execute("INSERT INTO magic(tok_hash,email,purpose,created,used) VALUES(?,?,?,?,0)",
              (_th(tok), email, purpose, time.time()))
    c.commit(); c.close()
    return tok

def consume_magic(tok):
    c = wdb()
    r = c.execute("SELECT * FROM magic WHERE tok_hash=?", (_th(tok or ""),)).fetchone()
    if not r or r["used"] or time.time() - r["created"] > MAGIC_TTL_S:
        c.close()
        return None
    c.execute("UPDATE magic SET used=1 WHERE tok_hash=?", (r["tok_hash"],))
    c.commit(); c.close()
    return r["email"]

def user_for_email(email):
    c = wdb()
    r = c.execute("SELECT * FROM users WHERE lower(email)=lower(?)", (email,)).fetchone()
    c.close()
    return r

def login_or_create_email(email, provider, subject):
    email = _valid_email(email)
    c = wdb()
    ident = c.execute("SELECT user_id FROM identities WHERE provider=? AND subject=?", (provider, subject)).fetchone()
    if ident:
        user = c.execute("SELECT * FROM users WHERE id=?", (ident["user_id"],)).fetchone()
        c.close()
        return user
    user = c.execute("SELECT * FROM users WHERE lower(email)=lower(?)", (email,)).fetchone()
    if user:
        c.execute("INSERT OR IGNORE INTO identities(user_id,provider,subject) VALUES(?,?,?)",
                  (user["id"], provider, subject))
        c.commit(); c.close()
        return user
    c.close()
    base = re.sub(r"[^A-Za-z0-9._-]", "", email.split("@")[0])[:24] or "user"
    name = base
    n = 1
    while find_user(name):
        n += 1
        name = f"{base[:24]}{n}"
    uid = create_user(name, password=None, email=email)
    c = wdb()
    c.execute("INSERT OR IGNORE INTO identities(user_id,provider,subject) VALUES(?,?,?)", (uid, provider, subject))
    c.commit()
    user = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return user

# ---------- oauth state / siws ----------
def new_oauth_state(provider):
    state = secrets.token_urlsafe(24)
    c = wdb()
    c.execute("INSERT INTO oauth_state(state_hash,provider,created,used) VALUES(?,?,?,0)",
              (_th(state), provider, time.time()))
    c.commit(); c.close()
    return state

def consume_oauth_state(state, provider):
    c = wdb()
    r = c.execute("SELECT * FROM oauth_state WHERE state_hash=?", (_th(state or ""),)).fetchone()
    if not r or r["used"] or r["provider"] != provider or time.time() - r["created"] > OAUTH_TTL_S:
        c.close()
        return False
    c.execute("UPDATE oauth_state SET used=1 WHERE state_hash=?", (r["state_hash"],))
    c.commit(); c.close()
    return True

def new_siws(message, address):
    nonce = secrets.token_urlsafe(16)
    # nonce is embedded in the message by the caller; we store the full message
    c = wdb()
    c.execute("INSERT INTO siws(nonce_hash,message,address,created,used) VALUES(?,?,?,?,0)",
              (_th(message), message, address, time.time()))
    c.commit(); c.close()
    return nonce

def consume_siws(message):
    c = wdb()
    r = c.execute("SELECT * FROM siws WHERE nonce_hash=?", (_th(message or ""),)).fetchone()
    if not r or r["used"] or time.time() - r["created"] > SIWS_TTL_S or r["message"] != message:
        c.close()
        return None
    c.execute("UPDATE siws SET used=1 WHERE nonce_hash=?", (r["nonce_hash"],))
    c.commit(); c.close()
    return r["address"]

# ---------- agent tokens (owner's remote assistant) ----------
def ensure_agent_token():
    """Bootstrap file token, registered as a scoped DB token. chmod 600. Never printed by the server."""
    if not os.path.exists(AGENT_TOKEN_FILE):
        old = os.umask(0o077)
        try:
            with open(AGENT_TOKEN_FILE, "w") as f:
                f.write(secrets.token_urlsafe(48) + "\n")
        finally:
            os.umask(old)
    try:
        os.chmod(AGENT_TOKEN_FILE, 0o600)
    except OSError:
        pass
    raw = open(AGENT_TOKEN_FILE).read().strip()
    if len(raw) >= 32:
        _register_token_hash("bootstrap", raw, "read,params,orders,ui")
    return AGENT_TOKEN_FILE

def _register_token_hash(name, raw, scopes):
    c = wdb()
    h = _th(raw)
    if not c.execute("SELECT 1 FROM agent_tokens WHERE tok_hash=?", (h,)).fetchone():
        c.execute(
            "INSERT INTO agent_tokens(name,prefix,tok_hash,scopes,created,revoked) VALUES(?,?,?,?,?,0)",
            (name, raw[:6], h, scopes, common.now_iso()),
        )
        c.commit()
    c.close()

def create_agent_token(name, scopes):
    bad = [s for s in scopes if s not in SCOPES]
    if bad or not scopes:
        raise ValueError("scopes inconnus")
    raw = secrets.token_urlsafe(48)
    c = wdb()
    c.execute(
        "INSERT INTO agent_tokens(name,prefix,tok_hash,scopes,created,revoked) VALUES(?,?,?,?,?,0)",
        (name[:40], raw[:6], _th(raw), ",".join(scopes), common.now_iso()),
    )
    c.commit(); c.close()
    return raw

def revoke_agent_token(token_id):
    c = wdb()
    c.execute("UPDATE agent_tokens SET revoked=1 WHERE id=?", (int(token_id),))
    c.commit(); c.close()

def rotate_agent_token(token_id, scopes=None):
    c = wdb()
    r = c.execute("SELECT * FROM agent_tokens WHERE id=?", (int(token_id),)).fetchone()
    c.close()
    if not r:
        raise ValueError("jeton introuvable")
    revoke_agent_token(token_id)
    use = scopes or [s for s in (r["scopes"] or "").split(",") if s]
    return create_agent_token((r["name"] or "rotated") + "-2", use)

def list_agent_tokens():
    c = wdb()
    rows = [dict(r) for r in c.execute(
        "SELECT id, name, prefix, scopes, created, revoked, last_used FROM agent_tokens ORDER BY id DESC")]
    c.close()
    return rows

def agent_token_info(presented):
    if not presented or len(presented) < 20 or len(presented) > 200:
        return None
    c = wdb()
    r = c.execute("SELECT * FROM agent_tokens WHERE tok_hash=? AND revoked=0", (_th(presented.strip()),)).fetchone()
    if not r:
        c.close()
        return None
    c.execute("UPDATE agent_tokens SET last_used=? WHERE id=?", (common.now_iso(), r["id"]))
    c.commit(); c.close()
    scopes = [s for s in (r["scopes"] or "").split(",") if s]
    return {"id": r["id"], "name": r["name"], "scopes": scopes, "prefix": r["prefix"]}

def agent_token_ok(presented):
    return bool(agent_token_info(presented))

def admin_ip_allowed(ip):
    raw = (os.environ.get("KAIRO_ADMIN_ALLOWLIST") or "").strip()
    if not raw:
        return True
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    return ip in allowed

def providers():
    smtp = bool(os.environ.get("SMTP_HOST"))
    google = bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
    apple = all(os.environ.get(k) for k in ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY"))
    return {"password": True, "magic": smtp, "google": google, "apple": bool(apple), "siws": True}

def public_base():
    return (os.environ.get("KAIRO_PUBLIC_URL") or "http://127.0.0.1:%s" % os.environ.get("DESK_PORT", "8787")).rstrip("/")
