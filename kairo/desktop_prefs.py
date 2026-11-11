"""Preferences for the desktop shell. No GUI imports."""
import json, os

DEFAULTS = {
    "background": True,
    "launch_at_login": False,
    "notifications": True,
    "onboarding_done": False,
    "x": None,
    "y": None,
    "w": 460,
    "h": 900,
}

def path(data_dir):
    return os.path.join(data_dir, "desktop.json")

def load(data_dir):
    prefs = dict(DEFAULTS)
    try:
        with open(path(data_dir), encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            prefs.update({k: raw[k] for k in DEFAULTS if k in raw})
    except Exception:
        pass
    return prefs

def save(data_dir, prefs):
    os.makedirs(data_dir, exist_ok=True)
    clean = dict(DEFAULTS)
    clean.update({k: prefs.get(k, DEFAULTS[k]) for k in DEFAULTS})
    dest = path(data_dir)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=1)
    os.replace(tmp, dest)
    return clean

def launch_agent_xml(app_path):
    app_path = str(app_path).replace("&", "&amp;").replace("<", "&lt;")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.kairo.desktop</string>
  <key>RunAtLoad</key><true/>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>{app_path}</string>
  </array>
</dict></plist>
"""

def apply_login(enabled, app_path=None, home=None):
    """Write or remove the per-user LaunchAgent. launchctl only on macOS."""
    import sys
    home = home or os.path.expanduser("~")
    app_path = app_path or os.environ.get("KAIRO_APP_PATH") or ""
    dest = set_launch_agent(home, app_path, bool(enabled) and bool(app_path))
    if sys.platform != "darwin":
        return dest
    import subprocess
    try:
        uid = str(os.getuid())
    except AttributeError:
        return dest
    domain = f"gui/{uid}"
    subprocess.run(["launchctl", "bootout", f"{domain}/io.kairo.desktop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if enabled and app_path and os.path.exists(dest):
        subprocess.run(["launchctl", "bootstrap", domain, dest], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dest

def set_launch_agent(home, app_path, enabled):
    folder = os.path.join(home, "Library", "LaunchAgents")
    dest = os.path.join(folder, "io.kairo.desktop.plist")
    if not enabled:
        try:
            os.remove(dest)
        except OSError:
            pass
        return dest
    os.makedirs(folder, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(launch_agent_xml(app_path))
    return dest

def trade_text(symbol, pnl_usd, fx, reason):
    eur = (pnl_usd or 0) / (fx or 1.08)
    sign = "+" if eur >= 0 else "−"
    why = reason or "clôturé"
    return f"{symbol} {why} · {sign}{abs(eur):.2f} €"
