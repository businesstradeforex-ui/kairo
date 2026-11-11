"""Paper-account capital and reset. Does not change order sizing math (executor.py).

A reset wipes the simulated book and starts a new session at the chosen euro amount,
converted with the same EUR/USD helper as the original desk.
"""
import json, os
import common

MIN_EUR = 50.0
MAX_EUR = 1_000_000.0

def _pref_path():
    return os.path.join(common.data_dir(), "paper_eur.txt")

def clamp_eur(eur):
    eur = float(eur)
    if eur != eur or eur in (float("inf"), float("-inf")):
        raise ValueError("montant invalide")
    if not MIN_EUR <= eur <= MAX_EUR:
        raise ValueError(f"capital papier entre {MIN_EUR:.0f} et {MAX_EUR:.0f} €")
    return eur

def ensure_session(con):
    """Fresh book: 1000 EUR (or paper_eur.txt / DESK_BANKROLL_EUR) at the live FX rate."""
    if common.kv_get(con, "cash") is not None:
        return
    pref = None
    try:
        pref = open(_pref_path(), encoding="utf-8").read().strip()
    except OSError:
        pref = None
    bank_eur = float(pref or os.environ.get("DESK_BANKROLL_EUR", "1000"))
    bank_eur = clamp_eur(bank_eur)
    fx = common.eurusd(con)
    usd = bank_eur * fx
    common.kv_set(con, "bankroll_eur", bank_eur)
    common.kv_set(con, "session_eurusd", fx)
    common.kv_set(con, "bankroll_usd", usd)
    common.kv_set(con, "cash", usd)
    common.kv_set(con, "session", {"started": common.now_iso(), "bankroll_eur": bank_eur, "eurusd": fx})

def open_count(con):
    return con.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]

def archive_session(con):
    """Copy the current book to data_dir/archives. The live tables are cleared after this returns."""
    folder = os.path.join(common.data_dir(), "archives")
    os.makedirs(folder, exist_ok=True)
    stamp = common.now_iso().replace(":", "").replace("-", "")
    path = os.path.join(folder, f"session-{stamp}.json")
    positions = [dict(r) for r in con.execute("SELECT * FROM positions")]
    exits = [dict(r) for r in con.execute("SELECT * FROM partial_exits")]
    equity = [dict(r) for r in con.execute("SELECT * FROM equity")]
    payload = {
        "archived": common.now_iso(),
        "bankroll_eur": common.kv_get(con, "bankroll_eur"),
        "bankroll_usd": common.kv_get(con, "bankroll_usd"),
        "cash": common.kv_get(con, "cash"),
        "session": common.kv_get(con, "session"),
        "positions": positions,
        "partial_exits": exits,
        "equity": equity,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str)
    os.replace(tmp, path)
    return path

def reset(con, eur):
    eur = clamp_eur(eur)
    archive = archive_session(con)
    con.execute("DELETE FROM positions")
    con.execute("DELETE FROM partial_exits")
    con.execute("DELETE FROM equity")
    con.commit()
    fx = common.eurusd(con)
    usd = eur * fx
    common.kv_set(con, "bankroll_eur", eur)
    common.kv_set(con, "session_eurusd", fx)
    common.kv_set(con, "bankroll_usd", usd)
    common.kv_set(con, "cash", usd)
    common.kv_set(con, "cycle", 0)
    common.kv_set(con, "session", {"started": common.now_iso(), "bankroll_eur": eur, "eurusd": fx, "reset": True})
    try:
        with open(_pref_path(), "w", encoding="utf-8") as f:
            f.write(f"{eur}\n")
    except OSError:
        pass
    return {"ok": True, "bankroll_eur": eur, "bankroll_usd": usd, "eurusd": fx, "archive": archive}

def set_capital(con, eur):
    """Change the starting bankroll only when nothing is open. Otherwise ask for a reset."""
    eur = clamp_eur(eur)
    if open_count(con):
        raise ValueError("des positions sont ouvertes : faites une remise à zéro pour changer le capital")
    if common.kv_get(con, "cash") is None:
        with open(_pref_path(), "w", encoding="utf-8") as f:
            f.write(f"{eur}\n")
        ensure_session(con)
        return {"ok": True, "bankroll_eur": eur, "applied": "session"}
    fx = float(common.kv_get(con, "session_eurusd") or common.eurusd(con))
    usd = eur * fx
    common.kv_set(con, "bankroll_eur", eur)
    common.kv_set(con, "bankroll_usd", usd)
    common.kv_set(con, "cash", usd)
    with open(_pref_path(), "w", encoding="utf-8") as f:
        f.write(f"{eur}\n")
    return {"ok": True, "bankroll_eur": eur, "bankroll_usd": usd}

def apply_control_file(con):
    path = os.path.join(common.data_dir(), "control.json")
    if not os.path.exists(path):
        return None
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    op = data.get("op")
    if op == "reset":
        return reset(con, data.get("eur") or 1000)
    if op == "capital":
        return set_capital(con, data["eur"])
    return None

def request(op, eur):
    eur = clamp_eur(eur)
    path = os.path.join(common.data_dir(), "control.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"op": op, "eur": eur, "ts": common.now_iso()}, f)
    os.replace(tmp, path)
    return path
