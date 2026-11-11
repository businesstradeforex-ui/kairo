"""Find a local AI server. Stdlib only. No secrets, no trading.

The desk runs without a model. This probe only tells the launcher which URL to
hand to the whitelisted executor (Ollama or an OpenAI-compatible server).
"""
import json, os, urllib.request

PROBES = (
    {"id": "ollama", "name": "Ollama", "base": "http://127.0.0.1:11434", "path": "/api/tags", "backend": "ollama"},
    {"id": "lmstudio", "name": "LM Studio", "base": "http://127.0.0.1:1234/v1", "path": "/models", "backend": "openai"},
    {"id": "llamacpp", "name": "llama.cpp", "base": "http://127.0.0.1:8080/v1", "path": "/models", "backend": "openai"},
)

def default_data_dir(system=None, home=None, environ=None):
    """Per-user folder for the desktop build. Overridden by MEMEDESK_DATA."""
    environ = os.environ if environ is None else environ
    if environ.get("MEMEDESK_DATA"):
        return os.path.abspath(environ["MEMEDESK_DATA"])
    system = system if system is not None else __import__("platform").system()
    home = home or environ.get("HOME") or environ.get("USERPROFILE") or "."
    if system == "Darwin":
        return os.path.join(home, "Library", "Application Support", "Kairo")
    if system == "Windows":
        base = environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, "Kairo")
    base = environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, "kairo")

def _default_fetch(url, timeout):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(200)

def probe(fetch=None, timeout=0.6, extra=()):
    """Return {ok, matches:[{id,name,base,backend}], checked:[...]}."""
    fetch = fetch or _default_fetch
    matches, checked = [], []
    seen = list(PROBES) + list(extra)
    for item in seen:
        url = item["base"].rstrip("/") + item["path"]
        row = {"id": item["id"], "name": item["name"], "url": url, "ok": False}
        try:
            status, _body = fetch(url, timeout)
            row["ok"] = 200 <= int(status) < 300
        except Exception as exc:
            row["error"] = type(exc).__name__
        checked.append(row)
        if row["ok"]:
            matches.append({"id": item["id"], "name": item["name"], "base": item["base"], "backend": item["backend"]})
    return {"ok": bool(matches), "matches": matches, "checked": checked}

def apply_match(match, environ=None):
    """Point the process at the first detected server unless the user already chose one."""
    environ = os.environ if environ is None else environ
    if not match:
        return
    if match["backend"] == "ollama":
        environ.setdefault("OLLAMA_URL", match["base"].rstrip("/"))
        environ.setdefault("KAIRO_LLM_BACKEND", "ollama")
    else:
        base = match["base"].rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        environ.setdefault("OPENAI_BASE_URL", base)
        environ.setdefault("OPENAI_API_KEY", environ.get("OPENAI_API_KEY") or "local")
        environ.setdefault("KAIRO_LLM_BACKEND", "openai")

def save_report(directory, report):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "ai_detected.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path

def load_report(directory):
    try:
        with open(os.path.join(directory, "ai_detected.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def setup_page(report):
    """French first-run page. No external assets, so it works before login."""
    report = report or {"ok": False, "matches": [], "checked": []}
    if report.get("ok"):
        names = ", ".join(m["name"] for m in report.get("matches") or [])
        status = f'<p class="ok">Serveur détecté : { _esc(names) }. Le desk peut lui envoyer des ordres de la liste blanche.</p>'
    else:
        status = (
            '<p class="warn">Aucun serveur local détecté sur les ports habituels '
            '(Ollama 11434, LM Studio 1234, llama.cpp 8080).</p>'
            '<p>Le desk papier démarre quand même. Les phrases simples (« pause », « mode profit », '
            '« liquidité min 20k ») marchent sans modèle. Branchez une IA puis rechargez cette page.</p>'
        )
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IA locale · Kairo</title>
<style>
body{{margin:0;background:#000;color:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}
main{{max-width:640px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:28px;letter-spacing:-.4px}} a{{color:#32D74B}}
.ok{{color:#32D74B}} .warn{{color:#FF9F0A}}
code,pre{{background:#1C1C1E;border-radius:12px;padding:12px;overflow:auto}}
.card{{background:#1C1C1E;border-radius:16px;padding:16px;margin:16px 0}}
</style></head><body><main>
<h1>Kairo · brancher l'IA locale</h1>
{status}
<div class="card"><h2>Ollama</h2>
<pre>brew install ollama    # macOS
ollama serve
ollama pull qwen3:4b</pre>
<p>16 Go ou plus : <code>ollama pull gemma4:12b</code> puis <code>KAIRO_LLM_MODEL=gemma4:12b</code>.</p></div>
<div class="card"><h2>LM Studio ou llama.cpp</h2>
<p>Démarrez le serveur compatible OpenAI, puis :</p>
<pre>export KAIRO_LLM_BACKEND=openai
export OPENAI_BASE_URL=http://127.0.0.1:1234/v1
export OPENAI_API_KEY=local</pre></div>
<p>Le trading réel reste <strong>éteint</strong>. Paper uniquement, tant que vous ne l'activez pas dans le compte.</p>
<p><a href="/login">Créer un compte et ouvrir le desk</a></p>
<p class="warn">English: install Ollama or any OpenAI-compatible local server, then open the desk. Live trading stays off.</p>
</main></body></html>"""

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
