"""Shared plumbing: HTTP with backoff, SQLite, JSONL, time.

Paper by default. No private keys are read here. Trading math is unchanged from the
original desk; only the data directory can be switched per account (context var)
so each user has an isolated portfolio. When the context is unset, paths match
the original single-folder desk (MEMEDESK_DATA or this directory).
"""
import contextvars, json, os, sqlite3, time, random, threading, datetime
import requests

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
# Données (DB, état, logs) : MEMEDESK_DATA si défini (Docker / systemd), sinon le dossier du code.
BASE = os.path.abspath(os.environ.get("MEMEDESK_DATA") or CODE_DIR)
os.makedirs(BASE, exist_ok=True)
DB_PATH = os.path.join(BASE, "desk.db")
LOG_DIR = os.path.join(BASE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_data_dir = contextvars.ContextVar("kairo_data_dir", default=None)

def data_dir():
    """Active portfolio directory. Defaults to BASE (original single-desk layout)."""
    v = _data_dir.get()
    return v if v else BASE

def bind_data_dir(path):
    """Point this thread/task at one account's portfolio. Does not change trading rules."""
    path = os.path.abspath(path)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "logs"), exist_ok=True)
    _data_dir.set(path)
    return path

def clear_data_dir():
    _data_dir.set(None)

def db_path():
    d = data_dir()
    return DB_PATH if os.path.abspath(d) == os.path.abspath(BASE) else os.path.join(d, "desk.db")

def log_dir():
    d = data_dir()
    p = LOG_DIR if os.path.abspath(d) == os.path.abspath(BASE) else os.path.join(d, "logs")
    os.makedirs(p, exist_ok=True)
    return p

_S = requests.Session()
_S.headers["User-Agent"] = "memedesk-paper/1.0 (read-only research)"
def reset_session():
    """Drop pooled (possibly wedged) connections after a hard timeout."""
    global _S
    try:
        _S.close()
    except Exception:
        pass
    _S = requests.Session()
    _S.headers["User-Agent"] = "memedesk-paper/1.0 (read-only research)"

_last_call = {}
_MIN_GAP = {"api.dexscreener.com": 0.25, "api.rugcheck.xyz": 1.1, "api.mainnet-beta.solana.com": 0.6, "api.geckoterminal.com": 6.5, "lite-api.jup.ag": 1.0}
STATS = {"http_ok": 0, "http_err": 0, "http_429": 0}
_resp_cache = {}  # key -> (epoch, data)
_CACHE_TTL = {"api.geckoterminal.com": 90, "lite-api.jup.ag": 45}
_CACHE_PATH_OK = ("/token-profiles/", "/token-boosts/", "/community-takeovers/", "/ads/", "/latest/dex/search")

def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

def get_json(url, params=None, timeout=(5, 10), tries=2, method="GET", body=None, use_cache=True):
    host = url.split("/")[2]
    cache_key = None
    ttl = _CACHE_TTL.get(host, 0) if use_cache else 0
    if method == "GET" and host == "api.dexscreener.com" and use_cache:
        ttl = 20 if any(s in url for s in _CACHE_PATH_OK) else 0
    if method == "GET" and ttl:
        cache_key = (url, tuple(sorted((params or {}).items())))
        hit = _resp_cache.get(cache_key)
        if hit and (time.time() - hit[0]) < ttl:
            return hit[1]
    for attempt in range(tries):
        gap = _MIN_GAP.get(host, 0.3)
        dt = time.time() - _last_call.get(host, 0)
        if dt < gap:
            time.sleep(gap - dt)
        _last_call[host] = time.time()
        try:
            if method == "POST":
                r = _S.post(url, json=body, timeout=timeout)
            else:
                r = _S.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                if r.status_code == 429:
                    STATS["http_429"] += 1
                wait = float(r.headers.get("Retry-After") or 0) or (2 ** attempt) * 3 + random.random()
                time.sleep(min(wait, 15 if 'geckoterminal' in host else 20))
                if 'geckoterminal' in host and attempt >= 1: return None
                continue
            if r.status_code != 200:
                STATS["http_err"] += 1
                return None
            STATS["http_ok"] += 1
            data = r.json()
            if cache_key is not None:
                _resp_cache[cache_key] = (time.time(), data)
            return data
        except Exception:
            STATS["http_err"] += 1
            time.sleep((2 ** attempt) + random.random())
    return None

_jl_lock = threading.Lock()
def jsonl(stage, obj):
    obj = dict(obj)
    obj.setdefault("ts", now_iso())
    with _jl_lock, open(os.path.join(log_dir(), f"{stage}.jsonl"), "a") as f:
        f.write(json.dumps(obj, default=str) + "\n")

def db():
    c = sqlite3.connect(db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY, ts TEXT, scanned INT, killed INT, scored INT, passed INT, entries INT, exits INT, equity REAL, note TEXT);
    CREATE TABLE IF NOT EXISTS candidates(cycle INT, ts TEXT, mint TEXT, pair TEXT, symbol TEXT, age_h REAL, mcap REAL, liq REAL, vol_h1 REAL);
    CREATE TABLE IF NOT EXISTS kills(cycle INT, ts TEXT, mint TEXT, pair TEXT, symbol TEXT, reason TEXT, value TEXT, threshold TEXT);
    CREATE TABLE IF NOT EXISTS scores(cycle INT, ts TEXT, mint TEXT, pair TEXT, symbol TEXT, score REAL, passed INT, components TEXT);
    CREATE TABLE IF NOT EXISTS holders(mint TEXT, ts_epoch REAL, holders INT);
    CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, mint TEXT, pair TEXT, symbol TEXT, status TEXT,
        entry_ts TEXT, entry_price REAL, ref_price REAL, qty REAL, cost_usd REAL, entry_slip REAL,
        stop_price REAL, initial_stop REAL, trail_active INT, peak_price REAL, last_price REAL, liq REAL,
        exit_ts TEXT, exit_price REAL, exit_reason TEXT, proceeds_usd REAL, pnl_usd REAL, pnl_pct REAL, score REAL);
    CREATE TABLE IF NOT EXISTS equity(ts TEXT, cash REAL, open_value REAL, equity REAL, n_open INT);
    CREATE TABLE IF NOT EXISTS token_meta(mint TEXT PRIMARY KEY, symbol TEXT, pair TEXT, icon TEXT, ts TEXT, snap TEXT);
    CREATE TABLE IF NOT EXISTS price_samples(pair TEXT, ts_epoch REAL, price REAL);
    CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
    """)
    cols = {r[1] for r in c.execute("PRAGMA table_info(positions)")}
    if "entry_trigger" not in cols:
        c.execute("ALTER TABLE positions ADD COLUMN entry_trigger TEXT")
    if "profile" not in cols:
        c.execute("ALTER TABLE positions ADD COLUMN profile TEXT")
    if "tp1_done" not in cols:
        c.execute("ALTER TABLE positions ADD COLUMN tp1_done INTEGER DEFAULT 0")
    if "tp2_done" not in cols:
        c.execute("ALTER TABLE positions ADD COLUMN tp2_done INTEGER DEFAULT 0")
    if "qty_initial" not in cols:
        c.execute("ALTER TABLE positions ADD COLUMN qty_initial REAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS partial_exits(
        id INTEGER PRIMARY KEY, position_id INT, ts TEXT, symbol TEXT, mint TEXT, pair TEXT,
        qty REAL, price REAL, proceeds_usd REAL, pnl_usd REAL, reason TEXT);
    """)
    c.commit()
    return c

def kv_get(c, k, default=None):
    r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default

def kv_set(c, k, v):
    c.execute("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (k, json.dumps(v)))
    c.commit()

# ---- EUR/USD (portfolio is shown in EUR; token prices are USD) ----
FX_FALLBACK = 1.08
_fx_mem = {"rate": None, "ts": 0}

def eurusd(con=None, max_age_s=900):
    """Live EUR->USD rate (USD per 1 EUR). ECB via frankfurter, then open.er-api; else last known (kv), else fallback."""
    forced = os.environ.get("KAIRO_FX")
    if forced:
        try:
            rate = float(forced)
            if 0.5 < rate < 2.5:
                return rate
        except ValueError:
            pass
    if _fx_mem["rate"] and time.time() - _fx_mem["ts"] < max_age_s:
        return _fx_mem["rate"]
    rate, src = None, None
    try:
        d = get_json("https://api.frankfurter.app/latest", params={"from": "EUR", "to": "USD"}, use_cache=False)
        rate = float(((d or {}).get("rates") or {}).get("USD") or 0) or None; src = "frankfurter(ECB)"
    except Exception:
        rate = None
    if not rate:
        try:
            d = get_json("https://open.er-api.com/v6/latest/EUR", use_cache=False)
            rate = float(((d or {}).get("rates") or {}).get("USD") or 0) or None; src = "open.er-api"
        except Exception:
            rate = None
    if rate and 0.5 < rate < 2.5:
        _fx_mem.update(rate=rate, ts=time.time())
        if con is not None:
            try: kv_set(con, "eurusd", {"rate": rate, "ts": now_iso(), "src": src})
            except Exception: pass
        return rate
    if con is not None:
        last = kv_get(con, "eurusd")
        if last and last.get("rate"):
            _fx_mem.update(rate=float(last["rate"]), ts=time.time() - max_age_s + 120)  # retry in 2 min
            return float(last["rate"])
    return _fx_mem["rate"] or FX_FALLBACK

def bankroll_usd(con):
    """USD value of the session's starting bankroll (1000 EUR converted at session start)."""
    return float(kv_get(con, "bankroll_usd", 10_000.0))
