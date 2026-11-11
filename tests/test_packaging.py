"""Launcher helpers and the first-run page. No network, no bundled CPython."""
import importlib.util, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["MEMEDESK_DATA"] = tempfile.mkdtemp(prefix="kairo-pack-")
os.environ["KAIRO_ENV"] = "test"
os.environ["KAIRO_SECRET_KEY"] = "packaging-test-key"
os.environ["KAIRO_FX"] = "1.08"
sys.path.insert(0, str(ROOT / "kairo"))

import ai_probe  # noqa: E402
import localsetup  # noqa: E402
import model_advice  # noqa: E402
import desktop_prefs  # noqa: E402

_spec = importlib.util.spec_from_file_location("kairo_build", ROOT / "packaging" / "build.py")
_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build)
ignore_copy = _build.ignore_copy


class ProbeTests(unittest.TestCase):
    def test_data_dir_respects_env_and_os(self):
        self.assertTrue(ai_probe.default_data_dir().endswith(os.environ["MEMEDESK_DATA"]) or
                        os.path.abspath(ai_probe.default_data_dir()) == os.path.abspath(os.environ["MEMEDESK_DATA"]))
        mac = ai_probe.default_data_dir("Darwin", "/Users/a", {})
        self.assertEqual(mac, "/Users/a/Library/Application Support/Kairo")
        local = r"C:\Users\a\AppData\Local"
        win = ai_probe.default_data_dir("Windows", r"C:\Users\a", {"LOCALAPPDATA": local})
        self.assertEqual(win, os.path.join(local, "Kairo"))
        linux = ai_probe.default_data_dir("Linux", "/home/a", {})
        self.assertEqual(linux, "/home/a/.local/share/kairo")

    def test_probe_and_apply_do_not_override(self):
        def fetch(url, timeout):
            if "11434" in url:
                return 200, b"{}"
            raise OSError("down")
        report = ai_probe.probe(fetch=fetch)
        self.assertTrue(report["ok"])
        self.assertEqual(report["matches"][0]["id"], "ollama")
        env = {"OLLAMA_URL": "http://10.0.0.2:11434", "KAIRO_LLM_BACKEND": "ollama"}
        ai_probe.apply_match(report["matches"][0], env)
        self.assertEqual(env["OLLAMA_URL"], "http://10.0.0.2:11434")
        page = ai_probe.setup_page(report)
        self.assertIn("Ollama", page)
        self.assertIn("éteint", page)
        self.assertNotIn("BEGIN PRIVATE", page)

    def test_bundle_skips_secrets(self):
        skipped = ignore_copy("/tmp", ["server.py", "secret.key", "agent_token.txt", ".env", "desk.db", "ok.py"])
        self.assertIn("secret.key", skipped)
        self.assertIn(".env", skipped)
        self.assertIn("desk.db", skipped)
        self.assertNotIn("server.py", skipped)

    def test_advice_for_16gb_with_little_disk(self):
        advice = model_advice.recommend(16, 12, ["qwen2.5:3b", "qwen2.5:32b"])
        self.assertEqual(advice["recommended"], "qwen3:4b")
        self.assertEqual(advice["action"], "download")
        states = {m["id"]: m["state"] for m in advice["models"]}
        self.assertEqual(states["qwen2.5:32b"], "ram")
        self.assertEqual(states["gemma4:12b"], "disk")
        self.assertEqual(states["qwen2.5:3b"], "installed")
        roomy = model_advice.recommend(16, 20, ["qwen2.5:3b"])
        self.assertEqual(roomy["recommended"], "gemma4:12b")
        self.assertFalse(localsetup.safe_name("qwen;rm"))
        self.assertTrue(localsetup.safe_name("qwen3:4b"))

    def test_prefs_and_login_agent(self):
        folder = tempfile.mkdtemp()
        saved = desktop_prefs.save(folder, {"background": False, "notifications": False})
        self.assertFalse(desktop_prefs.load(folder)["background"])
        self.assertFalse(saved["launch_at_login"])
        home = tempfile.mkdtemp()
        dest = desktop_prefs.set_launch_agent(home, "/Applications/Kairo.app", True)
        text = open(dest, encoding="utf-8").read()
        self.assertIn("/Applications/Kairo.app", text)
        self.assertIn("io.kairo.desktop", text)
        desktop_prefs.set_launch_agent(home, "/Applications/Kairo.app", False)
        self.assertFalse(os.path.exists(dest))
        self.assertIn("BONK", desktop_prefs.trade_text("BONK", -1.08, 1.08, "stop"))

    def test_live_default_in_launchers(self):
        text = (ROOT / "packaging" / "build.py").read_text(encoding="utf-8")
        self.assertIn('KAIRO_LIVE_ENABLED:-0', text)
        self.assertIn("if not defined KAIRO_LIVE_ENABLED", text)


if __name__ == "__main__":
    unittest.main()
