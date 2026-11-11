"""Local-only helpers for the desktop onboarding screen. No shell. Ollama HTTP only."""
import json, os, re, shutil, subprocess, sys, threading, urllib.request
import model_advice

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,80}$")
_lock = threading.Lock()
_pull = {"running": False, "model": "", "status": "", "completed": 0, "total": 0, "error": "", "done": False}

def ollama_base():
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

def safe_name(name):
    return bool(name) and bool(NAME_RE.match(str(name)))

def ram_gb():
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=2)
            return int(out.strip()) / (1024 ** 3)
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) / (1024 ** 2)
        if sys.platform == "win32":
            import ctypes
            class M(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = M()
            m.dwLength = ctypes.sizeof(M)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / (1024 ** 3)
    except Exception:
        return 0.0
    return 0.0

def free_disk_gb(path=None):
    path = path or os.path.expanduser("~")
    try:
        return shutil.disk_usage(path).free / (1024 ** 3)
    except Exception:
        return 0.0

def ollama_models(fetch=None):
    fetch = fetch or _get
    try:
        status, body = fetch(ollama_base() + "/api/tags", 1.5)
    except Exception:
        return {"up": False, "models": []}
    if status != 200:
        return {"up": False, "models": []}
    try:
        data = json.loads(body.decode() if isinstance(body, bytes) else body)
    except Exception:
        data = {}
    names = []
    for m in data.get("models") or []:
        if isinstance(m, dict) and m.get("name"):
            names.append(m["name"])
    return {"up": True, "models": names}

def _get(url, timeout):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()

def status(ram=None, disk=None, installed=None):
    tags = ollama_models() if installed is None else {"up": True, "models": list(installed)}
    if ram is None:
        ram = ram_gb()
    if disk is None:
        disk = free_disk_gb()
    advice = model_advice.recommend(ram, disk, tags.get("models") or [])
    chosen = ""
    try:
        import common
        path = os.path.join(common.data_dir(), "model.txt")
        if os.path.exists(path):
            chosen = open(path, encoding="utf-8").read().strip()
    except Exception:
        chosen = ""
    with _lock:
        pull = dict(_pull)
    return {"ollama": tags.get("up"), "models": tags.get("models") or [], "ram_gb": round(ram, 1),
            "free_disk_gb": round(disk, 1), "advice": advice, "selected": chosen, "pull": pull,
            "paper": True, "live": os.environ.get("KAIRO_LIVE_ENABLED", "0") == "1"}

def use_model(name):
    if not safe_name(name):
        raise ValueError("nom de modèle refusé")
    import common
    path = os.path.join(common.data_dir(), "model.txt")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(name + "\n")
    os.replace(tmp, path)
    return {"ok": True, "model": name}

def test_model(name, post=None):
    if not safe_name(name):
        raise ValueError("nom de modèle refusé")
    def _post(url, payload, timeout):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    post = post or _post
    status_code, body = post(ollama_base() + "/api/chat", {
        "model": name, "stream": False,
        "messages": [{"role": "user", "content": "Réponds uniquement par OK"}],
        "options": {"temperature": 0, "num_predict": 8},
    }, 90)
    data = json.loads(body.decode() if isinstance(body, bytes) else body)
    text = ((data.get("message") or {}).get("content") or "").strip()
    return {"ok": status_code == 200 and bool(text), "reply": text[:200]}

def pull_snapshot():
    with _lock:
        return dict(_pull)

def start_pull(name):
    if not safe_name(name):
        raise ValueError("nom de modèle refusé")
    with _lock:
        if _pull["running"]:
            raise ValueError("un téléchargement est déjà en cours")
        _pull.update(running=True, model=name, status="démarrage", completed=0, total=0, error="", done=False)
    threading.Thread(target=_worker, args=(name,), daemon=True).start()
    return pull_snapshot()

def _worker(name):
    req = urllib.request.Request(ollama_base() + "/api/pull", data=json.dumps({"name": name, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            while True:
                line = r.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                except Exception:
                    continue
                with _lock:
                    _pull["status"] = str(msg.get("status") or _pull["status"])[:200]
                    if msg.get("completed") is not None:
                        _pull["completed"] = int(msg.get("completed") or 0)
                    if msg.get("total") is not None:
                        _pull["total"] = int(msg.get("total") or 0)
                    if msg.get("error"):
                        _pull["error"] = str(msg["error"])[:300]
        with _lock:
            if _pull["error"]:
                _pull.update(running=False, done=True)
            else:
                _pull.update(running=False, done=True, status="terminé")
    except Exception as exc:
        with _lock:
            _pull.update(running=False, done=True, error=type(exc).__name__, status="échec")
