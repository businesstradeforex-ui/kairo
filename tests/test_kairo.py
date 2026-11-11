"""Kairo tests. Trading parameters are pinned to the original desk. No network required."""
import json, os, pathlib, sys, tempfile, threading, unittest
from http.client import HTTPConnection

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ["MEMEDESK_DATA"] = tempfile.mkdtemp(prefix="kairo-test-")
os.environ["KAIRO_ENV"] = "test"
os.environ["KAIRO_SECRET_KEY"] = "test-secret-kairo-not-a-real-key"
os.environ["KAIRO_FX"] = "1.08"
os.environ["KAIRO_LIVE_ENABLED"] = "0"
os.environ["KAIRO_MULTIUSER"] = "1"
os.environ["KAIRO_MAIL_SINK"] = os.path.join(os.environ["MEMEDESK_DATA"], "mailsink.txt")
sys.path.insert(0, str(ROOT / "kairo"))

import ai_local, analyst, config, connectors, crypto, executor, learn, security, server, webauth  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


def http(port, method, path, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=8)
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    conn.request(method, path, data, hdrs)
    res = conn.getresponse()
    raw = res.read()
    cookies = {}
    for c in res.headers.get_all("Set-Cookie") or []:
        k, _, v = c.split(";", 1)[0].partition("=")
        cookies[k] = v
    try:
        parsed = json.loads(raw.decode() or "null")
    except Exception:
        parsed = raw
    try:
        return res.status, parsed, cookies, res
    finally:
        conn.close()


class EngineTests(unittest.TestCase):
    def test_profiles_pinned(self):
        p = config.PROFILES["profit"]
        self.assertEqual(p["analyst"]["pass_score"], 60)
        self.assertEqual(p["analyst"]["signal_min_score"], 55)
        self.assertEqual(p["filter"]["liq_min"], 30_000)
        self.assertEqual(p["filter"]["vol1h_kill"], 10_000)
        self.assertEqual(p["filter"]["liq_mcap_min"], 0.10)
        self.assertEqual(p["filter"]["chase_h1_max"], 40.0)
        self.assertEqual(p["filter"]["young_dex_min_age_h"], 3.0)
        self.assertEqual(p["executor"]["max_frac"], 0.08)
        self.assertEqual(p["executor"]["max_open"], 6)
        self.assertEqual(p["executor"]["max_slip"], 0.015)
        self.assertEqual(p["risk"]["stop_pct"], 0.06)
        self.assertEqual(p["risk"]["trail_pct"], 0.06)
        self.assertEqual(p["risk"]["trail_activate"], 0.12)
        self.assertEqual(p["risk"]["partial_tp_frac"], 0.50)
        self.assertEqual(p["cycle_s"], 30)
        a = config.PROFILES["agressif"]
        self.assertEqual(a["analyst"]["pass_score"], 45)
        self.assertEqual(a["analyst"]["signal_min_score"], 28)
        self.assertEqual(a["filter"]["liq_min"], 15_000)
        self.assertEqual(a["scout"]["age_min_h"], 5 / 60)
        self.assertEqual(a["executor"]["max_open"], 10)
        s = config.PROFILES["strict"]
        self.assertEqual(s["analyst"]["pass_score"], 70)
        self.assertFalse(s["analyst"]["signals_enabled"])
        self.assertEqual(s["filter"]["liq_min"], 40_000)
        self.assertTrue(s["filter"]["fail_closed"])

    def test_momentum_and_slippage_and_size_cap(self):
        m = analyst.momentum({"chg": {"m5": 0, "h1": 10, "h6": 0}})
        self.assertAlmostEqual(m, 0.6 * analyst.lin(10, -20, 40) + 0.25 * analyst.lin(0, -5, 5) + 0.15 * analyst.lin(0, -30, 100))
        self.assertAlmostEqual(executor.slippage(100, 10_000), min(100 / 5000 + executor.FEE, 0.25))
        frac = executor.size_frac({"score": 100, "triggers": ["score"]}, {"min_frac": 0.03, "max_frac": 0.5})
        self.assertLessEqual(frac, 0.08)
        self.assertGreaterEqual(frac, 0.03)

    def test_learn_disable_and_half(self):
        trades = [{"setup": "vwap_pullback", "token": "BONK", "ts": "2026-11-11T10:00:00+01:00", "pnl": -1, "cost": 10, "combo": False} for _ in range(20)]
        st = learn.compute(trades)
        self.assertEqual(st["setup:vwap_pullback"]["status"], "disabled")
        self.assertEqual(learn.size_mult(st, "vwap_pullback", "BONK", trades[0]["ts"])[0], 0.0)
        soft = learn.compute(trades[:10])
        self.assertEqual(soft["token:BONK"]["status"], "downweight")
        self.assertEqual(learn.size_mult(soft, "vwap_pullback", "BONK", trades[0]["ts"])[0], 0.5)

    def test_orders_whitelist(self):
        act, how = ai_local.parse_order('{"action":"set_profile","profile":"profit"}')
        self.assertEqual(how, "json")
        self.assertEqual(ai_local.validate(act)["profile"], "profit")
        with self.assertRaises(ai_local.Refused):
            ai_local.validate({"action": "buy", "symbol": "BONK"})
        with self.assertRaises(ai_local.Refused):
            ai_local.parse_order("achète avec ma clé privée et retire les fonds")
        self.assertEqual(ai_local.rules("pause le desk")["action"], "pause_desk")
        with self.assertRaises(ai_local.Refused):
            ai_local.validate({"action": "set_param", "param": "liq_min", "value": 10})
        ok = ai_local.validate({"action": "set_param", "param": "liq_min", "value": 20000})
        self.assertEqual(ok["value"], 20000)
        with self.assertRaises(ai_local.Refused):
            ai_local.validate({"action": "set_param", "param": "max_frac", "value": 0.5})

    def test_crypto_roundtrip_and_no_private_key(self):
        blob = crypto.encrypt("super-secret")
        self.assertNotIn(b"super-secret", blob)
        self.assertEqual(crypto.decrypt(blob), "super-secret")
        with self.assertRaises(ValueError):
            connectors.upsert(1, "phantom", {"address": "x", "private_key": "nope"})
        with self.assertRaises(ValueError):
            connectors.upsert(1, "phantom", {"seed_phrase": "alpha beta gamma delta"})


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        security.LIMITER.reset()
        c = webauth.wdb()
        c.execute("DELETE FROM auth_fails")
        c.commit()
        c.close()

    def _csrf(self):
        status, _, cookies, _ = http(self.port, "GET", "/login")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", _.getheader("Content-Security-Policy"))
        return cookies["kairo_csrf"], cookies

    def _signup(self, email, username, password="correct horse battery"):
        csrf, _ = self._csrf()
        status, body, cookies, _ = http(self.port, "POST", "/signup",
                                        {"email": email, "username": username, "password": password, "csrf": csrf},
                                        {"X-CSRF-Token": csrf, "Cookie": f"kairo_csrf={csrf}"})
        self.assertEqual(status, 200, body)
        return cookies

    def test_signup_login_csrf_headers_isolation_and_paper(self):
        _, _, _, res = http(self.port, "GET", "/health")
        self.assertIn("frame-ancestors 'none'", res.getheader("Content-Security-Policy"))
        self.assertEqual(res.getheader("X-Frame-Options"), "DENY")
        status, body, _, _ = http(self.port, "POST", "/signup", {"email": "a@b.co", "username": "a", "password": "correct horse battery"})
        self.assertEqual(status, 403)
        c1 = self._signup("one@kairo.test", "alice")
        self.assertIn("kairo_session", c1)
        status, me, _, _ = http(self.port, "GET", "/api/me", headers={"Cookie": f"kairo_session={c1['kairo_session']}"})
        self.assertEqual(status, 200)
        self.assertIn(me["role"], ("owner", "user"))
        self.assertTrue(me["can_order"])
        c2 = self._signup("two@kairo.test", "bruno")
        _, me2, _, _ = http(self.port, "GET", "/api/me", headers={"Cookie": f"kairo_session={c2['kairo_session']}"})
        self.assertEqual(me2["role"], "user")
        self.assertNotEqual(me["id"], me2["id"])
        d1 = webauth.trading_dir_for(webauth.user_by_id(me["id"]))
        d2 = webauth.trading_dir_for(webauth.user_by_id(me2["id"]))
        self.assertNotEqual(d1, d2)
        # paper reset needs the word RESET, and stays inside that account
        status, body, _, _ = http(self.port, "POST", "/api/paper/reset", {"eur": 1000},
                                 {"Cookie": f"kairo_session={c1['kairo_session']}; kairo_csrf={c1['kairo_csrf']}", "X-CSRF-Token": c1["kairo_csrf"]})
        self.assertEqual(status, 400, body)
        status, body, _, _ = http(self.port, "POST", "/api/paper/reset", {"confirm": "RESET", "eur": 2500},
                                 {"Cookie": f"kairo_session={c1['kairo_session']}; kairo_csrf={c1['kairo_csrf']}", "X-CSRF-Token": c1["kairo_csrf"]})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["bankroll_eur"], 2500)
        import common
        common.bind_data_dir(d2)
        con = common.db()
        try:
            self.assertEqual(common.kv_get(con, "bankroll_eur"), 1000)
            self.assertNotEqual(common.kv_get(con, "bankroll_eur"), 2500)
        finally:
            con.close()
            common.clear_data_dir()

    def test_login_lockout_and_injection(self):
        self._signup("lock@kairo.test", "lockuser", "correct horse battery")
        csrf, _ = self._csrf()
        for _i in range(5):
            status, _, _, _ = http(self.port, "POST", "/login",
                                  {"username": "lockuser", "password": "wrong-password-xx", "csrf": csrf},
                                  {"X-CSRF-Token": csrf, "Cookie": f"kairo_csrf={csrf}"})
            self.assertIn(status, (401, 429))
        status, body, _, _ = http(self.port, "POST", "/login",
                                 {"username": "lockuser", "password": "correct horse battery", "csrf": csrf},
                                 {"X-CSRF-Token": csrf, "Cookie": f"kairo_csrf={csrf}"})
        self.assertEqual(status, 429, body)
        status, body, _, _ = http(self.port, "POST", "/login",
                                 {"username": "' OR 1=1 --", "password": "x", "csrf": csrf},
                                 {"X-CSRF-Token": csrf, "Cookie": f"kairo_csrf={csrf}"})
        self.assertIn(status, (401, 429))
        self.assertNotIn("sqlite", json.dumps(body).lower())

    def test_live_off_connectors_and_owner_token(self):
        cookies = self._signup("own@kairo.test", "ownerx")
        hdr = {"Cookie": f"kairo_session={cookies['kairo_session']}; kairo_csrf={cookies['kairo_csrf']}",
               "X-CSRF-Token": cookies["kairo_csrf"]}
        status, body, _, _ = http(self.port, "POST", "/api/live/opt-in", {"enabled": True, "confirm": "LIVE"}, hdr)
        self.assertEqual(status, 403, body)
        status, body, _, _ = http(self.port, "POST", "/api/connectors", {"kind": "phantom", "private_key": "abc"}, hdr)
        self.assertEqual(status, 400, body)
        status, body, _, _ = http(self.port, "POST", "/api/connectors", {"kind": "kraken", "api_key": "krakenkey1", "api_secret": "krakensecret"}, hdr)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["public"]["key_last4"], "key1")
        self.assertNotIn("krakensecret", json.dumps(body))
        status, body, _, _ = http(self.port, "POST", "/api/owner/token", {"name": "bot", "scopes": ["read", "orders"]}, hdr)
        self.assertEqual(status, 200, body)
        token = body["token"]
        status, body, _, _ = http(self.port, "GET", "/api/owner/state", headers={"Authorization": "Bearer " + token})
        self.assertEqual(status, 200, body)
        status, body, _, _ = http(self.port, "POST", "/api/orders?wait=5",
                                 {"action": "pause_desk"},
                                 {"Authorization": "Bearer " + token})
        self.assertIn(status, (200, 202), body)
        # a normal user cannot open the owner page API
        other = self._signup("guest@kairo.test", "guestx")
        status, _, _, _ = http(self.port, "GET", "/api/owner/state",
                              headers={"Cookie": f"kairo_session={other['kairo_session']}"})
        self.assertEqual(status, 403)

    def test_totp_and_magic(self):
        cookies = self._signup("otp@kairo.test", "otpuser")
        hdr = {"Cookie": f"kairo_session={cookies['kairo_session']}; kairo_csrf={cookies['kairo_csrf']}",
               "X-CSRF-Token": cookies["kairo_csrf"]}
        status, body, _, _ = http(self.port, "POST", "/api/account/totp/setup", {}, hdr)
        self.assertEqual(status, 200, body)
        import base64, hashlib, hmac, struct, time as _t
        secret = base64.b32decode(body["secret"] + "=" * (-len(body["secret"]) % 8))
        counter = int(_t.time()) // 30
        digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
        off = digest[-1] & 0x0F
        code = f"{(struct.unpack('>I', digest[off:off+4])[0] & 0x7FFFFFFF) % 1000000:06d}"
        status, body, _, _ = http(self.port, "POST", "/api/account/totp/enable", {"code": code}, hdr)
        self.assertEqual(status, 200, body)
        csrf, _ = self._csrf()
        status, body, _, _ = http(self.port, "POST", "/login",
                                 {"username": "otpuser", "password": "correct horse battery", "csrf": csrf},
                                 {"X-CSRF-Token": csrf, "Cookie": f"kairo_csrf={csrf}"})
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("totp_required"))
        csrf, _ = self._csrf()
        status, _, _, _ = http(self.port, "POST", "/auth/magic", {"email": "magic@kairo.test", "csrf": csrf},
                              {"X-CSRF-Token": csrf, "Cookie": f"kairo_csrf={csrf}"})
        self.assertEqual(status, 200)
        sink = open(os.environ["KAIRO_MAIL_SINK"], encoding="utf-8").read()
        self.assertIn("magic@kairo.test", sink)
        self.assertIn("/auth/magic/finish?token=", sink)


if __name__ == "__main__":
    unittest.main()
