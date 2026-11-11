"""Kairo HTTP server. Stdlib only. Paper trading is the default.

Listens on 127.0.0.1 unless DESK_HOST says otherwise. Do not publish this port;
put Cloudflare Tunnel or ngrok in front, with TRUST_PROXY=1, and only then are
X-Forwarded-* headers read — and only from a loopback peer.
"""
import json, os, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import ai_local, common, connectors, dashdata, live, mailer, oauth_id, paper, security, webauth

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("DESK_PORT", "8787"))
HOST = os.environ.get("DESK_HOST", "127.0.0.1")
TRUST_PROXY = os.environ.get("TRUST_PROXY", "0") == "1"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "auto")
MAX_BODY = 32 * 1024
STATIC_EXT = {
    "html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8", "png": "image/png", "svg": "image/svg+xml",
    "json": "application/json", "ico": "image/x-icon",
    "webmanifest": "application/manifest+json", "txt": "text/plain; charset=utf-8",
}

def manifest():
    return {
        "name": "Kairo", "short_name": "Kairo", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": "#000000", "theme_color": "#000000",
        "orientation": "portrait", "lang": "fr",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }

def _secure_request(handler):
    if COOKIE_SECURE in ("1", "true"):
        return True
    if COOKIE_SECURE in ("0", "false"):
        return False
    return TRUST_PROXY and handler.headers.get("X-Forwarded-Proto", "") == "https"

def client_ip(handler):
    peer = handler.client_address[0]
    if TRUST_PROXY and peer in ("127.0.0.1", "::1"):
        return (handler.headers.get("CF-Connecting-IP")
                or handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or peer)
    return peer

class H(BaseHTTPRequestHandler):
    server_version = "Kairo"
    sys_version = ""

    def log_message(self, fmt, *args):
        return

    def _ip(self):
        return client_ip(self)

    def _cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def _user(self):
        return webauth.session_user(self._cookie(webauth.SESSION_COOKIE))

    def _agent(self):
        h = self.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            return None
        if not webauth.admin_ip_allowed(self._ip()):
            return None
        return webauth.agent_token_info(h[7:].strip())

    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in security.security_headers(self._secure()).items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            vals = v if isinstance(v, list) else [v]
            for vv in vals:
                self.send_header(k, vv)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        return self._send(code, json.dumps(obj, default=str, ensure_ascii=False),
                          "application/json; charset=utf-8", extra)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > MAX_BODY:
            raise ValueError("corps de requête refusé")
        return self.rfile.read(n).decode("utf-8", "replace") if n else ""

    def _data(self):
        raw = self._body()
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype == "application/json":
            return json.loads(raw or "{}")
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def _secure(self):
        return _secure_request(self)

    def _cookie_hdr(self, name, val, max_age, httponly=True):
        parts = [f"{name}={val}", "Path=/", f"Max-Age={max_age}", "SameSite=Lax"]
        if httponly:
            parts.append("HttpOnly")
        if self._secure():
            parts.append("Secure")
        return "; ".join(parts)

    def _session_cookies(self, tok, csrf):
        return [
            self._cookie_hdr(webauth.SESSION_COOKIE, tok, webauth.SESSION_MAX_S, True),
            self._cookie_hdr(webauth.CSRF_COOKIE, csrf, webauth.SESSION_MAX_S, False),
        ]

    def _clear_session(self):
        return [
            self._cookie_hdr(webauth.SESSION_COOKIE, "", 0, True),
            self._cookie_hdr(webauth.CSRF_COOKIE, "", 0, False),
        ]

    def _ensure_csrf_cookie(self):
        if self._cookie(webauth.CSRF_COOKIE):
            return None
        import secrets
        return self._cookie_hdr(webauth.CSRF_COOKIE, secrets.token_urlsafe(24), 3600, False)

    def _csrf_ok(self, user, data):
        presented = self.headers.get("X-CSRF-Token") or (data or {}).get("csrf") or ""
        cookie = self._cookie(webauth.CSRF_COOKIE) or ""
        if user:
            return webauth.csrf_ok(user, presented) and presented == cookie
        return bool(presented) and presented == cookie and len(presented) >= 16

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if TRUST_PROXY and self.client_address[0] in ("127.0.0.1", "::1") and self.headers.get("X-Forwarded-Host"):
            host = self.headers.get("X-Forwarded-Host")
        if not origin:
            return True  # non-browser clients; cookie CSRF still applies for sessions
        return urlparse(origin).netloc == host

    def _bind_ready(self):
        con = common.db()
        try:
            paper.ensure_session(con)
        finally:
            con.close()

    def _bind(self, user):
        webauth.bind_user_id(user["id"])
        self._bind_ready()

    def _rate(self, bucket, limit, window):
        wait = security.LIMITER.hit(f"{bucket}:{self._ip()}", limit, window)
        if wait:
            self._json(429, {"error": "trop de tentatives", "retry_s": wait}, {"Retry-After": str(wait)})
            return True
        return False

    def _static(self, path):
        sd = dashdata.static_dir()
        rel = path.lstrip("/")
        fp = os.path.normpath(os.path.join(sd, rel))
        if not fp.startswith(os.path.abspath(sd) + os.sep) and fp != os.path.abspath(sd):
            return self._send(404, "not found", "text/plain")
        ext = fp.rsplit(".", 1)[-1].lower()
        if not os.path.isfile(fp) or ext not in STATIC_EXT:
            return self._send(404, "not found", "text/plain")
        with open(fp, "rb") as f:
            return self._send(200, f.read(), STATIC_EXT[ext])

    def _html_page(self, name):
        fp = os.path.join(dashdata.static_dir(), name)
        with open(fp, encoding="utf-8") as f:
            html = f.read()
        extra = {}
        c = self._ensure_csrf_cookie()
        if c:
            extra["Set-Cookie"] = c
        return self._send(200, html, "text/html; charset=utf-8", extra)

    # ----- GET -----
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        try:
            qs = {k: v[0] for k, v in parse_qs(u.query).items()}
            if path == "/health":
                return self._send(200, "ok", "text/plain")
            if path == "/manifest.webmanifest":
                return self._send(200, json.dumps(manifest()), "application/manifest+json")
            if path == "/api/auth/providers":
                return self._json(200, webauth.providers())
            if path in ("/login", "/signup"):
                return self._html_page("login.html")
            if path == "/auth/google":
                return self._send(302, "", "text/plain", {"Location": oauth_id.google_start()})
            if path == "/auth/google/callback":
                user = oauth_id.google_finish(qs.get("code", ""), qs.get("state", ""))
                return self._finish_login(user)
            if path == "/auth/apple":
                return self._send(302, "", "text/plain", {"Location": oauth_id.apple_start()})
            if path == "/auth/magic/finish":
                email = webauth.consume_magic(qs.get("token", ""))
                if not email:
                    return self._send(302, "", "text/plain", {"Location": "/login?err=lien"})
                user = webauth.login_or_create_email(email, "magic", email)
                return self._finish_login(user)
            if path.startswith("/auth/"):
                return self._json(404, {"error": "inconnu"})

            user = self._user()
            agent = self._agent()
            if path.startswith("/api/") and not user and not agent:
                return self._json(401, {"error": "non authentifié"})
            if not user and not agent and path not in ("/sw.js", "/logo.svg", "/icon-192.png", "/icon-512.png",
                                                        "/apple-touch-icon.png", "/favicon.ico", "/login.css", "/login.js"):
                if path in ("/", "/index.html"):
                    return self._send(302, "", "text/plain", {"Location": "/login"})
                return self._static(path)

            if agent and not user and path.startswith("/api/owner"):
                if not webauth.admin_ip_allowed(self._ip()):
                    return self._json(403, {"error": "adresse non autorisée"})
                webauth.bind_owner()
                self._bind_ready()
                return self._owner_get(path, qs, agent)
            if user:
                self._bind(user)
            if path in ("/", "/index.html"):
                with open(os.path.join(dashdata.static_dir(), "index.html"), encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/admin":
                if not user or not user["is_owner"]:
                    return self._json(403, {"error": "réservé au propriétaire"})
                return self._html_page("admin.html")
            if path == "/api/me":
                return self._json(200, {k: v for k, v in user.items() if k != "csrf"})
            if path == "/api/all":
                return self._json(200, dashdata.everything())
            if path == "/api/token":
                return self._json(200, dashdata.token(qs.get("mint", "")))
            if path == "/api/ohlcv":
                return self._json(200, dashdata.ohlcv(qs.get("pair", ""), qs.get("tf", "minute"), int(qs.get("agg", 5) or 5), qs.get("mint", "")))
            if path == "/api/activity" and qs.get("all"):
                return self._json(200, dashdata.activity(int(qs.get("limit", 400))))
            if path in dashdata.ROUTES:
                return self._json(200, dashdata.ROUTES[path]())
            if path == "/api/orders":
                if agent and "read" not in agent["scopes"] and not user:
                    return self._json(403, {"error": "scope read requis"})
                return self._json(200, self._orders_view(int(qs.get("limit", 50)), user))
            if path == "/api/ai_status":
                return self._json(200, ai_local.status())
            if path == "/api/settings":
                return self._json(200, self._settings(user))
            if path == "/api/connectors":
                return self._json(200, {"connectors": connectors.list_for(user["id"]), "catalog": connectors.CONNECTORS})
            if path.startswith("/api/owner"):
                if not user or not user["is_owner"]:
                    return self._json(403, {"error": "réservé au propriétaire"})
                return self._owner_get(path, qs, None)
            if path in ("/sw.js", "/logo.svg") or path.startswith("/icon") or path.endswith(".png") or path.endswith(".css") or path.endswith(".js"):
                return self._static(path)
            return self._static(path)
        except Exception as e:
            return self._json(400, {"error": security.safe_error(e)})

    def _finish_login(self, row):
        info = row if isinstance(row, dict) else webauth.public_user(row)
        tok, csrf = webauth.new_session(info["username"], self._ip())
        c = webauth.wdb(); webauth.audit(c, "web", info["username"], None, "login", {}, "ok", ip=self._ip()); c.close()
        return self._send(302, "", "text/plain", {"Location": "/", "Set-Cookie": self._session_cookies(tok, csrf)})

    def _settings(self, user):
        st = {}
        try:
            st = json.load(open(os.path.join(common.data_dir(), "state.json"), encoding="utf-8"))
        except Exception:
            st = {}
        return {"user": {k: v for k, v in user.items() if k != "csrf"},
                "paper": {"bankroll_eur": st.get("bankroll_eur"), "equity_eur": (st.get("equity") or 0) / (st.get("eurusd") or 1) if st.get("equity") else None},
                "live": {"server_enabled": live.master_on(), "account_enabled": user["live_enabled"],
                         "kill_switch": user["kill_switch"] or os.path.exists(live.global_kill_path()),
                         "max_order": user["live_max_order"], "max_daily": user["live_max_daily"],
                         "hard_order": live.hard_order_cap(), "hard_daily": live.hard_daily_cap()},
                "ai": ai_local.status(), "providers": webauth.providers()}

    def _orders_view(self, limit, user):
        c = webauth.wdb()
        try:
            if user and not user.get("is_owner"):
                o = [dict(r) for r in c.execute(
                    """SELECT id, ts, source, actor, raw, status, action, result, model, done_ts, user_id
                       FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?""", (user["id"], limit))]
                a = [dict(r) for r in c.execute(
                    "SELECT * FROM audit WHERE actor=? ORDER BY id DESC LIMIT ?", (user["username"], limit * 2))]
            else:
                o = [dict(r) for r in c.execute(
                    "SELECT id, ts, source, actor, raw, status, action, result, model, done_ts, user_id FROM orders ORDER BY id DESC LIMIT ?",
                    (limit,))]
                a = [dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit * 2,))]
        finally:
            c.close()
        return {"orders": o, "audit": a, "status": ai_local.status()}

    def _owner_get(self, path, qs, agent):
        if agent is not None and "read" not in agent["scopes"]:
            return self._json(403, {"error": "scope read requis"})
        if path in ("/api/owner/state", "/api/owner"):
            return self._json(200, {"summary": dashdata.summary(), "ai": ai_local.status(),
                                    "tokens": webauth.list_agent_tokens(), "allowlist": bool(os.environ.get("KAIRO_ADMIN_ALLOWLIST"))})
        if path == "/api/owner/audit":
            c = webauth.wdb()
            rows = [dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (int(qs.get("limit", 100)),))]
            c.close()
            return self._json(200, {"audit": rows})
        if path == "/api/owner/tokens":
            return self._json(200, {"tokens": webauth.list_agent_tokens()})
        return self._json(404, {"error": "inconnu"})

    # ----- POST -----
    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        try:
            if path == "/auth/apple/callback":
                data = self._data()
                user = oauth_id.apple_finish(data.get("code", ""), data.get("state", ""), data.get("id_token"), data.get("user"))
                return self._finish_login(user)
            if self._rate("post", 180, 60):
                return
            data = self._data()
            if path in ("/login", "/signup", "/auth/magic", "/auth/siws/nonce", "/auth/siws/verify", "/login/totp"):
                if not self._origin_ok() or not self._csrf_ok(None, data):
                    # login page sets the csrf cookie; require it
                    if not self._cookie(webauth.CSRF_COOKIE):
                        return self._json(403, {"error": "ouvrez la page de connexion d'abord"})
                    if not self._csrf_ok(None, data):
                        return self._json(403, {"error": "csrf"})
                return self._auth_post(path, data)
            agent = self._agent()
            user = None if (agent and path.startswith("/api/owner")) or (agent and path == "/api/orders") else self._user()
            if path == "/api/orders" and agent:
                user = None
            if not user and not agent:
                return self._json(401, {"error": "non authentifié"})
            if user and (not self._origin_ok() or not self._csrf_ok(user, data)):
                return self._json(403, {"error": "csrf"})
            if user:
                self._bind(user)
            if path == "/logout":
                webauth.end_session(self._cookie(webauth.SESSION_COOKIE))
                return self._send(302, "", "text/plain", {"Location": "/login", "Set-Cookie": self._clear_session()})
            if path == "/api/orders":
                return self._post_order(user, agent, data, u)
            if path == "/api/paper/capital":
                return self._paper_capital(user, data)
            if path == "/api/paper/reset":
                return self._paper_reset(user, data)
            if path == "/api/connectors":
                pub = connectors.upsert(user["id"], data.get("kind"), data)
                c = webauth.wdb(); webauth.audit(c, "web", user["username"], None, "connector_link", {"kind": data.get("kind")}, "ok", ip=self._ip()); c.close()
                return self._json(200, {"ok": True, "public": pub})
            if path == "/api/connectors/delete":
                connectors.delete(user["id"], data.get("kind"))
                return self._json(200, {"ok": True})
            if path == "/api/live/opt-in":
                return self._live_opt(user, data)
            if path == "/api/live/preview":
                row = webauth.user_by_id(user["id"])
                out = live.preview(row, data.get("kind"), data.get("symbol"), data.get("side"), data.get("usd"))
                return self._json(200, out)
            if path == "/api/live/execute":
                row = webauth.user_by_id(user["id"])
                out = live.execute(row, data.get("confirm_token"), data.get("phrase"))
                c = webauth.wdb(); webauth.audit(c, "web", user["username"], None, "live_order", out.get("order"), "executed",
                                                 json.dumps({"usd": (out.get("order") or {}).get("usd")}), ip=self._ip()); c.close()
                return self._json(200, {"ok": True})
            if path == "/api/kill-switch":
                live.set_kill_user(user["id"], bool(data.get("on", True)))
                if user["is_owner"] and data.get("global"):
                    live.set_global_kill(bool(data.get("on", True)))
                return self._json(200, {"ok": True})
            if path == "/api/account/totp/setup":
                secret = webauth.totp_begin(user["id"])
                label = urllib_quote(user["username"])
                uri = f"otpauth://totp/Kairo:{label}?secret={secret}&issuer=Kairo&digits=6&period=30"
                return self._json(200, {"secret": secret, "otpauth": uri})
            if path == "/api/account/totp/enable":
                webauth.totp_enable(user["id"], data.get("code"))
                return self._json(200, {"ok": True})
            if path == "/api/account/totp/disable":
                webauth.totp_disable(user["id"], data.get("code"))
                return self._json(200, {"ok": True})
            if path.startswith("/api/owner"):
                if agent:
                    if not webauth.admin_ip_allowed(self._ip()):
                        return self._json(403, {"error": "adresse non autorisée"})
                    webauth.bind_owner()
                    return self._owner_post(path, data, agent, "grokbot")
                if not user or not user["is_owner"]:
                    return self._json(403, {"error": "réservé au propriétaire"})
                return self._owner_post(path, data, {"scopes": list(webauth.SCOPES), "name": user["username"]}, user["username"])
            return self._json(404, {"error": "inconnu"})
        except Exception as e:
            return self._json(400, {"error": security.safe_error(e)})

    def _auth_post(self, path, data):
        ip = self._ip()
        if path == "/signup":
            if self._rate("signup", 5, 3600):
                return
            email = webauth._valid_email(data.get("email", ""))
            raw_name = data.get("username") or email.split("@")[0]
            username = "".join(ch for ch in raw_name if ch.isalnum() or ch in "._-")[:32] or "user"
            if len(username) < 2:
                username = (username + "kx")[:32]
            n = 1
            base = username
            while webauth.find_user(username):
                n += 1
                username = f"{base[:28]}{n}"
            uid = webauth.create_user(username, data.get("password"), role=None, email=email)
            row = webauth.user_by_id(uid)
            tok, csrf = webauth.new_session(row["username"], ip)
            return self._json(200, {"ok": True, "username": row["username"], "role": row["role"]},
                              {"Set-Cookie": self._session_cookies(tok, csrf)})
        if path == "/login":
            if self._rate("login", 20, 60):
                return
            user, pw = (data.get("username") or "").strip()[:64], data.get("password") or ""
            wait = webauth.login_blocked(ip, user)
            if wait:
                return self._json(429, {"error": "trop de tentatives", "retry_s": wait}, {"Retry-After": str(wait)})
            if user and pw and webauth.check_password(user, pw):
                row = webauth.find_user(user)
                if row["totp_enabled"] and not data.get("code"):
                    pending = webauth.new_totp_pending(row["id"])
                    return self._json(200, {"totp_required": True, "pending": pending})
                if row["totp_enabled"] and not webauth.totp_check_user(row, data.get("code")):
                    webauth.login_failed(ip, user)
                    return self._json(401, {"error": "code 2FA incorrect"})
                webauth.login_ok(ip, user)
                tok, csrf = webauth.new_session(row["username"], ip)
                return self._json(200, {"ok": True, "username": row["username"], "role": row["role"]},
                                  {"Set-Cookie": self._session_cookies(tok, csrf)})
            webauth.login_failed(ip, user)
            c = webauth.wdb(); webauth.audit(c, "web", user or "?", None, "login", {}, "failed", ip=ip); c.close()
            return self._json(401, {"error": "identifiant ou mot de passe incorrect"})
        if path == "/login/totp":
            row = webauth.consume_totp_pending(data.get("pending"), data.get("code"))
            if not row:
                return self._json(401, {"error": "code 2FA incorrect"})
            tok, csrf = webauth.new_session(row["username"], ip)
            return self._json(200, {"ok": True}, {"Set-Cookie": self._session_cookies(tok, csrf)})
        if path == "/auth/magic":
            if not webauth.providers()["magic"] and not os.environ.get("KAIRO_MAIL_SINK"):
                return self._json(503, {"error": "envoi d'e-mail non configuré (SMTP_HOST)"})
            if self._rate("magic", 5, 3600):
                return
            email = webauth._valid_email(data.get("email", ""))
            tok = webauth.create_magic(email)
            link = webauth.public_base() + "/auth/magic/finish?token=" + tok
            mailer.send(email, "Lien de connexion Kairo", f"Ouvrez ce lien pour vous connecter (15 min, un seul usage) :\n{link}\n")
            return self._json(200, {"ok": True, "message": "Si l'adresse est valide, un lien a été envoyé."})
        if path == "/auth/siws/nonce":
            return self._json(200, _siws_nonce(data.get("address", ""), self.headers.get("Host") or "localhost"))
        if path == "/auth/siws/verify":
            row = _siws_verify(data)
            tok, csrf = webauth.new_session(row["username"], ip)
            return self._json(200, {"ok": True, "username": row["username"]}, {"Set-Cookie": self._session_cookies(tok, csrf)})
        return self._json(404, {"error": "inconnu"})

    def _post_order(self, user, agent, data, u):
        if agent:
            if "orders" not in agent["scopes"]:
                return self._json(403, {"error": "scope orders requis"})
            webauth.bind_owner()
            owner = _owner_row()
            actor, source, uid = "grokbot", "grokbot", owner["id"] if owner else None
        else:
            if not user["can_order"]:
                return self._json(403, {"error": "compte en lecture seule"})
            if self._rate("orders:" + user["username"], 30, 60):
                return
            actor, source, uid = user["username"], "web", user["id"]
        order = data.get("order", data)
        order = order if isinstance(order, str) else json.dumps(order, ensure_ascii=False)
        oid = ai_local.enqueue(order, source, actor, uid)
        wait = float(parse_qs(u.query).get("wait", ["0"])[0] or 0)
        t_end = time.time() + min(wait, 60)
        row = None
        while True:
            c = webauth.wdb()
            row = dict(c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())
            c.close()
            if row["status"] not in ("pending", "running") or time.time() >= t_end:
                break
            ai_local.process_pending(5)
            time.sleep(0.2)
        code = {"done": 200, "refused": 422, "error": 500}.get(row["status"], 202)
        return self._json(code, {k: row[k] for k in row if k != "user_id"})

    def _paper_capital(self, user, data):
        if not user["can_order"]:
            return self._json(403, {"error": "lecture seule"})
        eur = paper.clamp_eur(data.get("eur"))
        con = common.db()
        try:
            paper.ensure_session(con)
            out = paper.set_capital(con, eur)
        finally:
            con.close()
        c = webauth.wdb()
        c.execute("UPDATE users SET paper_eur=? WHERE id=?", (eur, user["id"]))
        webauth.audit(c, "web", user["username"], None, "paper_capital", {"eur": eur}, "ok", ip=self._ip())
        c.close()
        return self._json(200, out)

    def _paper_reset(self, user, data):
        if not user["can_order"]:
            return self._json(403, {"error": "lecture seule"})
        if data.get("confirm") != "RESET":
            return self._json(400, {"error": "envoyez confirm=RESET pour effacer le compte papier"})
        eur = paper.clamp_eur(data.get("eur") or user.get("paper_eur") or 1000)
        con = common.db()
        try:
            paper.ensure_session(con)
            out = paper.reset(con, eur)
        finally:
            con.close()
        c = webauth.wdb(); webauth.audit(c, "web", user["username"], None, "paper_reset", {"eur": eur}, "ok", ip=self._ip()); c.close()
        return self._json(200, out)

    def _live_opt(self, user, data):
        if not user["can_order"]:
            return self._json(403, {"error": "lecture seule"})
        enabled = bool(data.get("enabled"))
        if enabled and data.get("confirm") != "LIVE":
            return self._json(400, {"error": "envoyez confirm=LIVE pour activer les ordres réels"})
        if enabled and not live.master_on():
            return self._json(403, {"error": "le serveur a le trading réel coupé (KAIRO_LIVE_ENABLED=0)"})
        live.opt_in(user["id"], enabled)
        c = webauth.wdb(); webauth.audit(c, "web", user["username"], None, "live_opt_in", {"enabled": enabled}, "ok", ip=self._ip()); c.close()
        return self._json(200, {"ok": True, "live_enabled": enabled, "server_enabled": live.master_on()})

    def _owner_post(self, path, data, token, actor):
        scopes = token["scopes"]
        ip = self._ip()
        if path == "/api/owner/token":
            if "ui" not in scopes and actor != "grokbot" and "admin" not in scopes:
                # the owner session has every scope; a token needs no extra scope to mint if it is the owner UI
                pass
            if isinstance(token.get("id"), int) and "ui" not in scopes:
                return self._json(403, {"error": "scope ui requis pour créer un jeton"})
            raw = webauth.create_agent_token(data.get("name") or "assistant", data.get("scopes") or ["read", "params", "orders", "ui"])
            c = webauth.wdb(); webauth.audit(c, "owner", actor, None, "token_create", {"scopes": data.get("scopes")}, "ok", ip=ip); c.close()
            return self._json(200, {"token": raw, "once": True})
        if path == "/api/owner/token/revoke":
            webauth.revoke_agent_token(data["id"])
            c = webauth.wdb(); webauth.audit(c, "owner", actor, None, "token_revoke", {"id": data.get("id")}, "ok", ip=ip); c.close()
            return self._json(200, {"ok": True})
        if path == "/api/owner/token/rotate":
            raw = webauth.rotate_agent_token(data["id"], data.get("scopes"))
            c = webauth.wdb(); webauth.audit(c, "owner", actor, None, "token_rotate", {"id": data.get("id")}, "ok", ip=ip); c.close()
            return self._json(200, {"token": raw, "once": True})
        if path == "/api/owner/orders":
            if "orders" not in scopes:
                return self._json(403, {"error": "scope orders requis"})
            owner = _owner_row()
            order = data.get("order", data)
            order = order if isinstance(order, str) else json.dumps(order, ensure_ascii=False)
            oid = ai_local.enqueue(order, "grokbot", actor, owner["id"] if owner else None)
            ai_local.process_pending(5)
            c = webauth.wdb(); row = dict(c.execute("SELECT id, status, result, action FROM orders WHERE id=?", (oid,)).fetchone()); c.close()
            return self._json(200 if row["status"] == "done" else 422, row)
        if path == "/api/owner/ui":
            if "ui" not in scopes:
                return self._json(403, {"error": "scope ui requis"})
            code, res = _update_ui()
            c = webauth.wdb(); webauth.audit(c, "grokbot", actor, None, "update_ui", {}, "executed" if res.get("ok") else "error", json.dumps(res)[:1500], ip=ip); c.close()
            return self._json(code, res)
        return self._json(404, {"error": "inconnu"})

def urllib_quote(s):
    from urllib.parse import quote
    return quote(s)

def _owner_row():
    c = webauth.wdb()
    r = c.execute("SELECT * FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone()
    c.close()
    return r

def _siws_nonce(address, host):
    address = connectors._sol_address(address)
    host = (host or "localhost").split(":")[0]
    issued = common.now_iso()
    nonce = __import__("secrets").token_urlsafe(16)
    message = (
        f"{host} wants you to sign in with your Solana account:\n"
        f"{address}\n\n"
        f"Connexion à Kairo. Aucune transaction n'est autorisée.\n\n"
        f"URI: {webauth.public_base()}\n"
        f"Version: 1\n"
        f"Chain ID: mainnet\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued}\n"
    )
    webauth.new_siws(message, address)
    return {"message": message, "nonce": nonce}

def _siws_verify(data):
    import base58
    import nacl.signing
    message = data.get("message") or ""
    address = data.get("address") or ""
    sig = data.get("signature") or ""
    stored = webauth.consume_siws(message)
    if not stored or stored != address:
        raise ValueError("message de connexion invalide ou expiré")
    if address not in message:
        raise ValueError("adresse absente du message")
    try:
        raw_sig = base58.b58decode(sig) if isinstance(sig, str) and not sig.startswith("[") else bytes(sig if isinstance(sig, list) else json.loads(sig))
    except Exception:
        raw_sig = base58.b58decode(sig)
    nacl.signing.VerifyKey(base58.b58decode(address)).verify(message.encode("utf-8"), raw_sig)
    return webauth.login_or_create_email(f"{address[:8].lower()}@wallet.kairo", "siws", address)

def _update_ui():
    import shutil, subprocess
    ui = os.environ.get("MEMEDESK_UI_DIR", "")
    if not ui or not os.path.isdir(os.path.join(ui, ".git")):
        return 400, {"ok": False, "error": "MEMEDESK_UI_DIR n'est pas un checkout git"}
    git = shutil.which("git")
    if not git:
        return 500, {"ok": False, "error": "git introuvable"}
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"), "GIT_TERMINAL_PROMPT": "0"}
    def run(*a):
        return subprocess.run([git, "-c", "core.hooksPath=/dev/null", "-C", ui, *a], capture_output=True, text=True, timeout=90, env=env)
    before = run("rev-parse", "HEAD").stdout.strip()
    r = run("pull", "--ff-only", "--no-rebase", "--quiet")
    after = run("rev-parse", "HEAD").stdout.strip()
    if r.returncode != 0:
        return 500, {"ok": False, "error": "git pull a échoué", "commit": before[:12]}
    changed = run("diff", "--name-only", before, after).stdout.split() if before != after else []
    return 200, {"ok": True, "from": before[:12], "to": after[:12], "served": [f for f in changed if f.startswith("static/")]}

def main():
    if webauth.user_count() == 0:
        print("Kairo : aucun compte. Le premier compte créé sur /signup devient propriétaire.", flush=True)
    webauth.ensure_agent_token()
    print(f"Kairo on http://{HOST}:{PORT} (paper by default)", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()

if __name__ == "__main__":
    main()
