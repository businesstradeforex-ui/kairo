"""IA locale — exécute des ORDRES sur le desk papier, via une liste blanche stricte.

Entrées : file d'attente `orders` de web.db, alimentée par le panneau « Ordres & IA locale » (session Mael)
ou par POST /api/orders (jeton agent de Grok Bot). Un ordre est :
  * du JSON structuré : {"action": "set_profile", "profile": "profit"}
  * ou du français : « passe en mode profit », « liquidité min 20k », « résumé des 6 dernières heures »…
Le français est traduit par un petit modèle local (Ollama, gratuit) en UNE action de la liste blanche.
Si Ollama ne répond pas, un petit analyseur à règles prend le relais ; le JSON structuré marche toujours.

Liste blanche (rien d'autre n'est exécuté, jamais de shell, jamais de code issu du modèle) :
  set_profile   {"profile": "strict"|"agressif"|"profit"}
  set_intensif  {"enabled": true|false}
  set_param     {"param": liq_min|max_open|stop_pct|trail_pct|trail_activate|max_frac, "value": nombre}  (bornes : config.OVERRIDABLE)
  reset_params  {}
  pause_desk    {}   (plus aucune entrée ; Risk continue de gérer les positions ouvertes)
  resume_desk   {}
  summary       {"hours": 1..168}
Tout est journalisé dans la table `audit`. PAPIER UNIQUEMENT : aucun wallet, aucune clé, aucun ordre réel.
"""
import json, os, re, sqlite3, time, traceback, urllib.request

import common, config, webauth

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
# OpenAI-compatible local servers (LM Studio, llama.cpp server, vLLM, …).
# KAIRO_LLM_BACKEND = ollama | openai | auto (auto uses OpenAI when OPENAI_BASE_URL is set).
LLM_BACKEND = os.environ.get("KAIRO_LLM_BACKEND", "auto").strip().lower()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("KAIRO_LLM_MODEL") or os.environ.get("OLLAMA_MODEL") or "qwen3:4b"
LLM_TIMEOUT_S = float(os.environ.get("OLLAMA_TIMEOUT_S", os.environ.get("KAIRO_LLM_TIMEOUT_S", "180")))
LLM_MIN_INTERVAL_S = float(os.environ.get("KAIRO_LLM_MIN_INTERVAL_S", "2"))
_llm_lock = __import__("threading").Lock()
_llm_next = [0.0]

def pause_flag():
    return os.path.join(common.data_dir(), "paused.flag")

def intensif_off_flag():
    return os.path.join(common.data_dir(), "intensif_off.flag")

def heartbeat_path():
    return os.path.join(common.data_dir(), "heartbeat_ai")

def _backend():
    if LLM_BACKEND == "openai":
        return "openai"
    if LLM_BACKEND == "ollama":
        return "ollama"
    return "openai" if OPENAI_BASE_URL else "ollama"
PROFILES = ("strict", "agressif", "profit")
ACTIONS = ("set_profile", "set_intensif", "set_param", "reset_params", "pause_desk", "resume_desk", "summary")
PCT_PARAMS = {"stop_pct", "trail_pct", "trail_activate", "max_frac"}
PARAM_FR = {"liq_min": "liquidité minimale ($)", "max_open": "positions ouvertes max", "stop_pct": "stop-loss",
            "trail_pct": "trailing (écart au plus haut)", "trail_activate": "activation du trailing",
            "max_frac": "taille max par position"}

class Refused(Exception):
    pass

# ---------- file d'attente ----------
def enqueue(raw, source, actor, user_id=None):
    raw = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    raw = raw.strip()[:2000]
    if not raw:
        raise ValueError("ordre vide")
    c = webauth.wdb()
    cur = c.execute("INSERT INTO orders(ts,source,actor,raw,status,user_id) VALUES(?,?,?,?,?,?)",
                    (common.now_iso(), source, actor, raw, "pending", user_id))
    c.commit(); oid = cur.lastrowid
    webauth.audit(c, source, actor, oid, "order_received", {"raw": raw}, "queued")
    c.close()
    return oid

# ---------- validation (le seul endroit qui décide de ce qui est permis) ----------
def _num(v):
    if isinstance(v, bool):
        raise Refused("valeur numérique attendue")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().replace(" ", "").replace(",", ".").replace("$", "").replace("€", "")
    mult = 1
    if s.endswith("%"):
        s = s[:-1]
    if s.endswith("k"):
        s, mult = s[:-1], 1000
    try:
        return float(s) * mult
    except ValueError:
        raise Refused(f"valeur non numérique : {v!r}")

def validate(a):
    if not isinstance(a, dict):
        raise Refused("format d'ordre invalide")
    act = str(a.get("action", "")).strip().lower()
    if act not in ACTIONS:
        raise Refused(f"action non autorisée : {act or '(vide)'}")
    if act == "set_profile":
        p = str(a.get("profile", "")).strip().lower()
        if p == "intensif":
            return {"action": "set_intensif", "enabled": True}
        if p not in PROFILES:
            raise Refused(f"profil inconnu : {p!r} (strict, agressif, profit)")
        return {"action": act, "profile": p}
    if act == "set_intensif":
        en = a.get("enabled")
        if isinstance(en, str):
            en = en.strip().lower() in ("true", "on", "1", "oui", "marche")
        if not isinstance(en, bool):
            raise Refused("enabled doit être true ou false")
        return {"action": act, "enabled": en}
    if act == "set_param":
        p = str(a.get("param", "")).strip().lower()
        spec = config.OVERRIDABLE.get(p)
        if not spec:
            raise Refused(f"paramètre non modifiable : {p!r}")
        _, _, lo, hi = spec
        v = _num(a.get("value"))
        if p in PCT_PARAMS and v > 1:  # « 6 » ou « 6 % » -> 0.06
            v = v / 100
        if not (lo <= v <= hi):
            raise Refused(f"{PARAM_FR[p]} hors bornes : {v:g} (autorisé {lo:g} – {hi:g})")
        if p == "max_open":
            v = int(round(v))
        return {"action": act, "param": p, "value": v}
    if act == "summary":
        h = a.get("hours", 24)
        h = int(_num(h)) if h is not None else 24
        if not 1 <= h <= 168:
            raise Refused("hours doit être entre 1 et 168")
        return {"action": act, "hours": h}
    return {"action": act}

# ---------- traduction français -> action ----------
SYSTEM = """Tu traduis l'ordre d'un trader (desk de trading PAPIER, aucun argent réel) en UNE action JSON.
Réponds UNIQUEMENT avec un objet JSON, sans texte autour. Actions autorisées :
{"action":"set_profile","profile":"strict"|"agressif"|"profit"}
{"action":"set_intensif","enabled":true|false}
{"action":"set_param","param":"liq_min"|"max_open"|"stop_pct"|"trail_pct"|"trail_activate"|"max_frac","value":nombre}
  liq_min = liquidité minimale en dollars (ex. 20000) ; max_open = nombre max de positions ouvertes ;
  stop_pct, trail_pct, trail_activate, max_frac = fractions (6 % = 0.06)
{"action":"reset_params"}
{"action":"pause_desk"}   (arrêter d'ouvrir de nouvelles positions)
{"action":"resume_desk"}
{"action":"summary","hours":nombre}   (résumé des trades récents)
Si l'ordre ne correspond à aucune de ces actions (argent réel, wallet, clé, commande système, autre chose) :
{"action":"refuse","reason":"..."}"""

def ollama_ok():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3) as r:
            tags = json.load(r)
        return True, [m.get("name") for m in tags.get("models", [])]
    except Exception:
        return False, []

def openai_ok():
    if not OPENAI_BASE_URL:
        return False, []
    url = OPENAI_BASE_URL + "/models"
    headers = {}
    if OPENAI_API_KEY:
        headers["Authorization"] = "Bearer " + OPENAI_API_KEY
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.load(r)
        names = []
        for m in data.get("data") or data.get("models") or []:
            if isinstance(m, dict):
                names.append(m.get("id") or m.get("name"))
            elif isinstance(m, str):
                names.append(m)
        return True, [n for n in names if n]
    except Exception:
        return False, []

def _rate_limit_llm():
    with _llm_lock:
        wait = _llm_next[0] - time.time()
        if wait > 0:
            time.sleep(min(wait, 30))
        _llm_next[0] = time.time() + LLM_MIN_INTERVAL_S

def llm(messages, as_json=True, max_tokens=200):
    """Call the configured local model. Temperature 0. Never executes the reply — callers validate it."""
    _rate_limit_llm()
    if _backend() == "openai":
        body = {"model": MODEL, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        if as_json:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if OPENAI_API_KEY:
            headers["Authorization"] = "Bearer " + OPENAI_API_KEY
        req = urllib.request.Request(OPENAI_BASE_URL + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as r:
            data = json.load(r)
        return data["choices"][0]["message"]["content"]
    body = {"model": MODEL, "messages": messages, "stream": False,
            "options": {"temperature": 0, "num_predict": max_tokens}}
    if as_json:
        body["format"] = "json"
    req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as r:
        return json.load(r)["message"]["content"]

def rules(text):
    """Analyseur de secours sans IA (quelques formulations courantes)."""
    t = text.lower()
    m = re.search(r"(\d+)\s*(?:derni\w+\s+)?(?:h\b|heure)", t)
    if re.search(r"r[ée]sum|bilan|rapport|r[ée]cap", t):
        return {"action": "summary", "hours": int(m.group(1)) if m else 24}
    if "intensif" in t:
        off = re.search(r"\b(off|stop|arr[eê]t|coupe|d[ée]sactiv|[ée]tein)", t)
        return {"action": "set_intensif", "enabled": not off}
    num = r"(\d+(?:[.,]\d+)?\s*k?)"
    for pat, p in ((rf"liquidit\w*.*?{num}", "liq_min"), (rf"{num}\s*positions", "max_open"), (rf"positions?.*?{num}", "max_open"),
                   (rf"trailing.*?activ\w*.*?{num}", "trail_activate"), (rf"trailing.*?{num}", "trail_pct"),
                   (rf"stop.*?{num}", "stop_pct"), (rf"taille.*?{num}", "max_frac")):
        mm = re.search(pat, t)
        if mm:
            return {"action": "set_param", "param": p, "value": mm.group(1)}
    if re.search(r"\b(reprend|reprise|relance|resume)", t):
        return {"action": "resume_desk"}
    if re.search(r"\bpause\b|\bstop(pe)?\b|arr[eê]te", t):
        return {"action": "pause_desk"}
    for p in PROFILES:
        if re.search(rf"\b{p}\b", t):
            return {"action": "set_profile", "profile": p}
    if re.search(r"r[ée]initialis|reset|param[eè]tres par d[ée]faut", t):
        return {"action": "reset_params"}
    return None

FORBIDDEN = re.compile(r"wallet|\bach[eè]t|\bvend|\bbuy\b|\bsell\b|portefeuille (r[ée]el|phantom)|phantom|seed|cl[ée] priv|private key|mnemonic|transf[eé]r|envoie|virement|retir|withdraw|"
                       r"argent r[ée]el|r[ée]el(le)?s?\b.*(trade|ordre|achat)|mainnet.*(swap|achat)|\bswap\b|shell|terminal|commande syst|"
                       r"\brm\b|sudo|bash|python|curl|ssh|\bexec|ex[ée]cute (une |la )?commande|supprim|efface|delete|drop table", re.I)

def plausible(a, text):
    """Garde-fou : un petit modèle peut se tromper d'action ; on exige un indice dans le texte."""
    t = text.lower(); act = a.get("action")
    if act == "set_profile": return str(a.get("profile", "")).lower() in t
    if act == "set_intensif": return "intensif" in t
    if act == "set_param": return bool(re.search(r"\d", t))
    if act == "reset_params": return bool(re.search(r"r[ée]initialis|reset|d[ée]faut|origine", t))
    if act == "pause_desk": return bool(re.search(r"pause|stop|arr[eê]t|suspend|g[eè]le", t))
    if act == "resume_desk": return bool(re.search(r"repr|relanc|resume|red[ée]marr|continu", t))
    if act == "summary": return bool(re.search(r"r[ée]sum|bilan|rapport|r[ée]cap|point|comment|perf|r[ée]sultat|synth", t))
    return False

def parse_order(raw):
    """-> (action dict, méthode). JSON structuré, sinon : refus immédiat des sujets interdits, règles déterministes,
    puis petit modèle local (dont la réponse doit rester plausible au regard du texte)."""
    s = raw.strip()
    if s.startswith("{"):
        try:
            return json.loads(s), "json"
        except json.JSONDecodeError:
            raise Refused("JSON invalide")
    if FORBIDDEN.search(s):
        raise Refused("hors liste blanche : achats/ventes manuels, argent réel, wallet, clés, transferts et commandes système sont interdits (desk papier)")
    a = rules(s)
    if a is not None:
        return a, "règles"
    up = ollama_ok()[0] or openai_ok()[0]
    if not up:
        raise Refused("ordre non compris (IA locale indisponible ; utilisez une formulation simple ou du JSON)")
    try:
        out = llm([{"role": "system", "content": SYSTEM}, {"role": "user", "content": s}])
        a = json.loads(out)
    except Exception as e:
        print(f"[{common.now_iso()}] ollama error {e!r}", flush=True)
        raise Refused("IA locale : réponse inexploitable, reformulez")
    if isinstance(a, dict) and a.get("action") == "refuse":
        raise Refused("refusé par l'IA locale : " + str(a.get("reason") or "hors liste blanche")[:200])
    if isinstance(a, dict) and a.get("action") in ACTIONS and not plausible(a, s):
        raise Refused(f"ordre ambigu (l'IA locale proposait « {a.get('action')} »), reformulez plus précisément")
        return a, f"{_backend()}:{MODEL}"

# ---------- exécution ----------
def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

def summary(hours):
    dbp = common.db_path()
    if not os.path.exists(dbp):
        return {"text": "Aucune donnée de trading pour l'instant."}
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True, timeout=10); c.row_factory = sqlite3.Row
    since = time.time() - hours * 3600
    rows = [dict(r) for r in c.execute("""SELECT p.symbol, p.exit_ts, p.exit_reason, p.pnl_pct,
             p.pnl_usd + COALESCE((SELECT SUM(x.pnl_usd) FROM partial_exits x WHERE x.position_id=p.id),0) pnl
             FROM positions p WHERE p.status='closed'""")]
    import datetime
    def ep(ts):
        try: return datetime.datetime.fromisoformat(ts).timestamp()
        except Exception: return 0
    rows = [r for r in rows if ep(r["exit_ts"]) >= since]
    n_open = c.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
    c.close()
    try:
        st = json.load(open(os.path.join(common.data_dir(), "state.json")))
    except Exception:
        st = {}
    fx = float(st.get("eurusd") or 1.08)
    eq_eur = (st.get("equity") or 0) / fx if st.get("equity") else None
    wins = [r for r in rows if (r["pnl"] or 0) > 0]
    pnl = sum(r["pnl"] or 0 for r in rows) / fx
    best = max(rows, key=lambda r: r["pnl"] or 0) if rows else None
    worst = min(rows, key=lambda r: r["pnl"] or 0) if rows else None
    facts = {"heures": hours, "trades_clotures": len(rows), "gagnants": len(wins),
             "taux_reussite_pct": round(len(wins) / len(rows) * 100) if rows else None,
             "pnl_realise_eur": round(pnl, 2), "positions_ouvertes": n_open,
             "portefeuille_eur": round(eq_eur, 2) if eq_eur else None,
             "profil": config.profile_name(), "en_pause": os.path.exists(pause_flag()),
             "meilleur": f"{best['symbol']} {best['pnl']/fx:+.2f} €" if best else None,
             "pire": f"{worst['symbol']} {worst['pnl']/fx:+.2f} €" if worst else None}
    txt = (f"Sur {hours} h : {len(rows)} trade(s) clôturé(s), {len(wins)} gagnant(s)"
           + (f" ({facts['taux_reussite_pct']} %)" if rows else "") + f", PnL réalisé {pnl:+.2f} €. "
           + f"{n_open} position(s) ouverte(s)." + (f" Portefeuille : {eq_eur:.2f} €." if eq_eur else "")
           + (f" Meilleur : {facts['meilleur']}, pire : {facts['pire']}." if rows else "")
           + f" Profil {facts['profil']}" + (" (en pause)." if facts["en_pause"] else "."))
    up = ollama_ok()[0] or openai_ok()[0]
    if up and rows:
        try:
            txt2 = llm([{"role": "system", "content": "Tu écris un bilan de trading PAPIER très court (3 phrases max), en français, en vouvoyant le lecteur. N'invente aucun chiffre : utilise uniquement ces données."},
                        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}], as_json=False, max_tokens=180)
            if txt2.strip():
                return {"text": txt2.strip(), "facts": facts, "template": txt}
        except Exception:
            pass
    return {"text": txt, "facts": facts}

def execute(a):
    act = a["action"]
    if act == "set_profile":
        _write_atomic(config.profile_path(), a["profile"] + "\n")
        return f"Profil du compte de base : {a['profile']} (appliqué au prochain cycle)."
    if act == "set_intensif":
        if a["enabled"]:
            if os.path.exists(intensif_off_flag()): os.remove(intensif_off_flag())
            return "Mode intensif activé (démarrage sous ~10 s)."
        _write_atomic(intensif_off_flag(), common.now_iso() + "\n")
        return "Mode intensif arrêté (sous ~10 s)."
    if act == "set_param":
        ov = dict(config.overrides())
        ov[a["param"]] = a["value"]
        _write_atomic(config.overrides_path(), json.dumps(ov, indent=1))
        v = a["value"]
        shown = f"{v*100:g} %" if a["param"] in PCT_PARAMS else (f"{v:,.0f} $".replace(",", " ") if a["param"] == "liq_min" else f"{v}")
        return f"{PARAM_FR[a['param']].capitalize()} : {shown} (profil {config.profile_name()}, prochain cycle)."
    if act == "reset_params":
        if os.path.exists(config.overrides_path()): os.remove(config.overrides_path())
        return "Paramètres revenus aux valeurs du profil."
    if act == "pause_desk":
        _write_atomic(pause_flag(), common.now_iso() + "\n")
        return "Desk en pause : plus aucune nouvelle entrée, Risk continue de surveiller les positions."
    if act == "resume_desk":
        if os.path.exists(pause_flag()): os.remove(pause_flag())
        return "Desk relancé : les entrées reprennent au prochain cycle."
    if act == "summary":
        s = summary(a["hours"])
        return s["text"]
    raise Refused(f"action non autorisée : {act}")

def process(c, row):
    oid, raw, source, actor = row["id"], row["raw"], row["source"], row["actor"]
    uid = row["user_id"] if "user_id" in row.keys() else None
    if uid:
        webauth.bind_user_id(int(uid))
    elif source == "grokbot":
        webauth.bind_owner()
    method, act = None, None
    try:
        parsed, method = parse_order(raw)
        act = validate(parsed)
        res = execute(act)
        status, outcome = "done", "executed"
    except Refused as e:
        res, status, outcome = str(e), "refused", "refused"
    except Exception as e:
        res, status, outcome = f"erreur interne : {type(e).__name__}", "error", "error"
        traceback.print_exc()
    c.execute("UPDATE orders SET status=?, action=?, result=?, model=?, done_ts=? WHERE id=?",
              (status, json.dumps(act, ensure_ascii=False) if act else None, res, method, common.now_iso(), oid))
    c.commit()
    webauth.audit(c, source, actor, oid, (act or {}).get("action", "?"), act or {"raw": raw[:300]}, outcome,
                  f"[{method or '-'}] {res}")
    print(f"[{common.now_iso()}] order {oid} {status} {act} -> {res[:160]}", flush=True)

def process_pending(limit=20):
    c = webauth.wdb()
    try:
        for row in c.execute("SELECT * FROM orders WHERE status='pending' ORDER BY id LIMIT ?", (limit,)).fetchall():
            c.execute("UPDATE orders SET status='running' WHERE id=? AND status='pending'", (row["id"],)); c.commit()
            process(c, row)
    finally:
        c.close()

def status():
    o_up, o_models = ollama_ok()
    a_up, a_models = openai_ok()
    backend = _backend()
    up = a_up if backend == "openai" else o_up
    models = a_models if backend == "openai" else o_models
    return {"ollama": o_up, "openai": a_up, "backend": backend, "online": up,
            "ollama_url": OLLAMA_URL, "openai_base_url": OPENAI_BASE_URL or None,
            "model": MODEL, "model_present": any((m or "").split(":")[0].startswith(MODEL.split(":")[0]) or (m or "") == MODEL for m in models),
            "models": models, "profile": config.profile_name(), "overrides": config.overrides(),
            "desk_paused": os.path.exists(pause_flag()), "intensif_enabled": not os.path.exists(intensif_off_flag()),
            "actions": list(ACTIONS), "bounds": {k: [v[2], v[3]] for k, v in config.OVERRIDABLE.items()},
            "note_fr": "L'IA locale traduit un ordre en une action de la liste blanche. Les décisions de trading viennent du code des agents, pas du modèle."}

def main():
    print(f"[{common.now_iso()}] ai_local start backend={_backend()} model={MODEL} ollama={OLLAMA_URL} openai={OPENAI_BASE_URL or '-'} PAPER ONLY", flush=True)
    c = webauth.wdb()
    c.execute("UPDATE orders SET status='pending' WHERE status='running'"); c.commit(); c.close()
    while True:
        try:
            process_pending()
        except Exception:
            traceback.print_exc()
        try:
            open(heartbeat_path(), "w").write(f"{time.time():.0f}\n")
        except Exception:
            pass
        time.sleep(1)

if __name__ == "__main__":
    main()
