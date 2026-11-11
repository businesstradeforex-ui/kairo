"""Desktop entry point.

Creates the data directory and the encryption key, looks for a local AI server,
opens the browser, then runs the same supervisor as `run.py all`.

Live trading stays off unless KAIRO_LIVE_ENABLED is already set to 1.
Set KAIRO_NO_BROWSER=1 in Docker or tests.
"""
import os, sys, threading, time, webbrowser

def prepare():
    import ai_probe, crypto
    data = ai_probe.default_data_dir()
    os.environ["MEMEDESK_DATA"] = data
    os.environ.setdefault("KAIRO_LIVE_ENABLED", "0")
    os.environ.setdefault("KAIRO_ENV", "production")
    os.environ.setdefault("DESK_HOST", "127.0.0.1")
    os.environ.setdefault("DESK_PORT", "8787")
    os.environ.setdefault("KAIRO_MULTIUSER", "1")
    os.makedirs(data, exist_ok=True)
    try:
        os.chmod(data, 0o700)
    except OSError:
        pass
    crypto.ensure_key()
    report = ai_probe.probe()
    ai_probe.save_report(data, report)
    if report["matches"]:
        ai_probe.apply_match(report["matches"][0])
        print(f"Kairo : IA locale détectée ({report['matches'][0]['name']}).", flush=True)
    else:
        print("Kairo : aucune IA locale détectée. Le desk papier démarre quand même.", flush=True)
        print("  Ollama :        http://127.0.0.1:11434", flush=True)
        print("  LM Studio :     http://127.0.0.1:1234/v1", flush=True)
        print("  llama.cpp :     http://127.0.0.1:8080/v1", flush=True)
        print("  Guide :         http://127.0.0.1:%s/setup" % os.environ["DESK_PORT"], flush=True)
    return data, report

def _open_when_ready(url):
    if os.environ.get("KAIRO_NO_BROWSER") == "1":
        return
    port = os.environ.get("DESK_PORT", "8787")
    health = f"http://127.0.0.1:{port}/health"

    def run():
        import urllib.request
        for _ in range(60):
            try:
                urllib.request.urlopen(health, timeout=1).read()
                webbrowser.open(url)
                return
            except Exception:
                time.sleep(0.5)
    threading.Thread(target=run, daemon=True).start()

def main(argv=None):
    _data, report = prepare()
    desktop_on = os.environ.get("KAIRO_DESKTOP") == "1" and os.environ.get("KAIRO_NO_BROWSER") != "1"
    if desktop_on:
        try:
            import desktop
        except ImportError as exc:
            print(f"Kairo : module desktop absent ({exc}).", flush=True)
        else:
            return desktop.main(report)
    port = os.environ.get("DESK_PORT", "8787")
    url = f"http://127.0.0.1:{port}/" + ("login" if report["ok"] else "setup")
    _open_when_ready(url)
    import run
    return run.main(list(argv if argv is not None else sys.argv[1:]) or ["all"])

if __name__ == "__main__":
    sys.exit(main() or 0)
