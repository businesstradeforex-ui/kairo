"""Superviseur multi-plateforme (remplace supervise.sh + watchdog.sh de la version box).

  python3 run.py all                      lance et surveille server, desk, intensif, ai (Docker / systemd / terminal)
  python3 run.py desk|server|intensif|ai  un seul composant (un service launchd par composant sur macOS)

- Redémarre un composant qui s'arrête (pause 5 s, puis jusqu'à 60 s si ça boucle).
- Desk / intensif figés (heartbeat > 180 s) : redémarrage.
- Intensif : si intensif_off.flag existe (ordre « coupe l'intensif »), le processus est arrêté et n'est pas relancé.
- Logs : <données>/logs/<composant>.log (tronqués au-delà de 50 Mo).
PAPIER UNIQUEMENT.
"""
import os, signal, subprocess, sys, threading, time

CODE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.environ.get("MEMEDESK_DATA") or CODE)
LOGS = os.path.join(DATA, "logs")
os.makedirs(LOGS, exist_ok=True)
PY = sys.executable
_MULTI = os.environ.get("KAIRO_MULTIUSER", "1") != "0"
COMPONENTS = {
    "server": ["server.py"],
    "desk": ["userdesk.py"] if _MULTI else ["desk.py"],
    "intensif": ["intensif.py"],
    "ai": ["ai_local.py"],
}
HEARTBEATS = {"desk": "heartbeat", "intensif": "heartbeat_intensif", "ai": "heartbeat_ai"}
STALE_S = 180
STALE = {"desk": 300, "intensif": 180, "ai": 600}   # desk : un cycle peut durer jusqu'à 240 s
def intensif_off():
    return os.path.join(_component_data("intensif"), "intensif_off.flag")
_stop = threading.Event()

def _component_data(name):
    """Intensif follows the owner portfolio when every account has its own folder."""
    if name == "intensif" and _MULTI:
        try:
            import webauth
            for acc in webauth.trading_accounts():
                if acc["role"] == "owner":
                    return acc["dir"]
        except Exception:
            pass
    return DATA

def log(msg):
    line = f"[{time.strftime('%F %T %Z')}] run: {msg}"
    print(line, flush=True)
    with open(os.path.join(LOGS, "supervisor.log"), "a") as f:
        f.write(line + "\n")

def _logfile(name):
    p = os.path.join(LOGS, f"{name}.log")
    try:
        if os.path.getsize(p) > 50 * 1024 * 1024:
            os.replace(p, p + ".1")
    except OSError:
        pass
    return open(p, "a")

def supervise(name):
    backoff = 5
    while not _stop.is_set():
        if name == "intensif" and os.path.exists(intensif_off()):
            time.sleep(3); continue
        env = dict(os.environ, PYTHONUNBUFFERED="1", MEMEDESK_DATA=_component_data(name))
        t0 = time.time()
        with _logfile(name) as lf:
            p = subprocess.Popen([PY, os.path.join(CODE, *COMPONENTS[name])], cwd=CODE, env=env,
                                 stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
            log(f"{name} démarré (pid {p.pid})")
            while p.poll() is None and not _stop.is_set():
                time.sleep(2)
                if name == "intensif" and os.path.exists(intensif_off()):
                    log("intensif_off.flag présent -> arrêt de l'intensif"); p.terminate(); break
                hb = HEARTBEATS.get(name)
                lim = STALE.get(name, STALE_S)
                if hb and time.time() - t0 > lim:
                    try:
                        age = time.time() - os.path.getmtime(os.path.join(_component_data(name), hb))
                    except OSError:
                        age = time.time() - t0
                    if age > lim:
                        log(f"{name} figé ({age:.0f} s sans heartbeat) -> redémarrage"); p.kill(); break
            if _stop.is_set():
                p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill(); p.wait()
        if _stop.is_set():
            break
        backoff = 5 if time.time() - t0 > 120 else min(backoff * 2, 60)
        log(f"{name} arrêté (code {p.returncode}) -> relance dans {backoff} s")
        _stop.wait(backoff)

def shutdown():
    """Ask the supervisor thread to stop its children. Used by the desktop app on Quit."""
    _stop.set()

def main(argv):
    which = argv[0] if argv else "all"
    names = list(COMPONENTS) if which == "all" else [which]
    if any(n not in COMPONENTS for n in names):
        print(__doc__); return 1
    def _sig(*_):
        _stop.set()
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _sig); signal.signal(signal.SIGINT, _sig)
    log(f"superviseur ({', '.join(names)}) — données : {DATA}")
    ts = [threading.Thread(target=supervise, args=(n,), daemon=True) for n in names]
    for t in ts: t.start()
    while not _stop.is_set() and any(t.is_alive() for t in ts):
        time.sleep(1)
    _stop.set()
    for t in ts: t.join(timeout=20)
    log("superviseur arrêté")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
