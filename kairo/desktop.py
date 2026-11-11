"""Native window around the local desk.

macOS uses pywebview (WKWebView) plus an AppKit status item. Windows uses the
same window when pywebview is installed (WebView2). Linux falls back to the
browser unless pywebview and a GUI toolkit are present. The desk processes
are the existing supervisor; Quit stops them.
"""
import json, os, sqlite3, sys, threading, time, urllib.request

import desktop_prefs

_window = None
_status_item = None

def _base():
    port = os.environ.get("DESK_PORT", "8787")
    return f"http://127.0.0.1:{port}"

def _prefs():
    import common
    return desktop_prefs.load(common.BASE)

def _save(prefs):
    import common
    return desktop_prefs.save(common.BASE, prefs)

def _wait_health():
    url = _base() + "/health"
    for _ in range(80):
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return True
        except Exception:
            time.sleep(0.25)
    return False

def _start_supervisor():
    import run
    threading.Thread(target=lambda: run.main(["all"]), name="kairo-supervisor", daemon=True).start()

def _equity_label():
    import common
    paused = os.path.exists(os.path.join(common.BASE, "paused.flag"))
    equity = "—"
    try:
        with open(os.path.join(common.BASE, "state.json"), encoding="utf-8") as f:
            st = json.load(f)
        fx = float(st.get("eurusd") or 1.08) or 1.08
        eq = st.get("equity")
        if eq is not None:
            equity = f"{eq / fx:,.0f} €".replace(",", " ")
    except Exception:
        pass
    state = "pause" if paused else "actif"
    return state, equity

def _toggle_pause():
    import common
    flag = os.path.join(common.BASE, "paused.flag")
    if os.path.exists(flag):
        try:
            os.remove(flag)
        except OSError:
            pass
        return False
    with open(flag, "w", encoding="utf-8") as f:
        f.write("desktop\n")
    return True

def _notify(text):
    if not _prefs().get("notifications", True):
        return
    if sys.platform != "darwin":
        return
    import subprocess
    safe = text.replace("\\", " ").replace('"', "'")[:180]
    subprocess.Popen(["osascript", "-e", f'display notification "{safe}" with title "Kairo"'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _watch_trades():
    import common
    seen = set()
    db = os.path.join(common.BASE, "desk.db")
    primed = False
    while True:
        time.sleep(8)
        if not os.path.exists(db):
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            rows = list(con.execute("SELECT id, symbol, pnl_usd, exit_reason FROM positions WHERE status='closed' ORDER BY id DESC LIMIT 20"))
            con.close()
        except Exception:
            continue
        if not primed:
            seen = {r[0] for r in rows}
            primed = True
            continue
        fx = 1.08
        try:
            with open(os.path.join(common.BASE, "state.json"), encoding="utf-8") as f:
                fx = float(json.load(f).get("eurusd") or 1.08)
        except Exception:
            pass
        for row in reversed(rows):
            if row[0] in seen:
                continue
            seen.add(row[0])
            _notify(desktop_prefs.trade_text(row[1], row[2], fx, row[3]))

def _apply_login(enabled):
    home = os.path.expanduser("~")
    app = os.environ.get("KAIRO_APP_PATH") or ""
    if not app:
        return
    dest = desktop_prefs.set_launch_agent(home, app, enabled)
    if sys.platform != "darwin":
        return
    import subprocess
    uid = str(os.getuid())
    domain = f"gui/{uid}"
    label = "io.kairo.desktop"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if enabled and os.path.exists(dest):
        subprocess.run(["launchctl", "bootstrap", domain, dest], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _install_status_item(window):
    try:
        from AppKit import NSStatusBar, NSMenu, NSMenuItem, NSVariableStatusItemLength, NSApplication, NSObject
    except Exception:
        return
    global _status_item
    bar = NSStatusBar.systemStatusBar()
    item = bar.statusItemWithLength_(NSVariableStatusItemLength)
    button = item.button()
    if button is not None:
        button.setTitle_("K")
    menu = NSMenu.alloc().init()

    def refresh(_=None):
        state, equity = _equity_label()
        title = f"Kairo · {state} · {equity}"
        if button is not None:
            button.setToolTip_(title)
        pause_item.setTitle_("Reprendre" if state == "pause" else "Pause")

    def open_window(_):
        window.show()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def pause(_):
        _toggle_pause()
        refresh()

    def quit_app(_):
        _quit(window)

    open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Ouvrir Kairo", "openKairo:", "")
    pause_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Pause", "pauseKairo:", "")
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quitter Kairo", "quitKairo:", "q")
    # Targetless selectors fail. Use a tiny delegate via setTarget_ of a Python object.
    class Handler(NSObject):
        def openKairo_(self, _sender):
            open_window(None)
        def pauseKairo_(self, _sender):
            pause(None)
        def quitKairo_(self, _sender):
            quit_app(None)
    handler = Handler.alloc().init()
    for it in (open_item, pause_item, quit_item):
        it.setTarget_(handler)
    open_item.setAction_(b"openKairo:")
    pause_item.setAction_(b"pauseKairo:")
    quit_item.setAction_(b"quitKairo:")
    menu.addItem_(open_item)
    menu.addItem_(pause_item)
    menu.addItem_(quit_item)
    item.setMenu_(menu)
    _status_item = (item, handler)
    refresh()

    def loop():
        try:
            from PyObjCTools import AppHelper
        except Exception:
            return
        while True:
            time.sleep(5)
            try:
                AppHelper.callAfter(refresh)
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True).start()

def _quit(window):
    try:
        import run
        run.shutdown()
    except Exception:
        pass
    try:
        window.destroy()
    except Exception:
        pass
    os._exit(0)

def _remember(window):
    prefs = _prefs()
    try:
        prefs["x"] = int(window.x)
        prefs["y"] = int(window.y)
        prefs["w"] = int(window.width)
        prefs["h"] = int(window.height)
        _save(prefs)
    except Exception:
        pass

def main(report=None):
    os.environ.setdefault("KAIRO_LIVE_ENABLED", "0")
    _start_supervisor()
    if not _wait_health():
        print("Kairo : le serveur local n'a pas répondu.", flush=True)
    threading.Thread(target=_watch_trades, daemon=True).start()
    try:
        import webview
    except Exception as exc:
        print(f"Kairo : fenêtre native indisponible ({exc}). Ouverture du navigateur.", flush=True)
        import webbrowser
        prefs = _prefs()
        url = _base() + ("/onboarding" if not prefs.get("onboarding_done") else "/login")
        webbrowser.open(url)
        import run
        return run.main(["all"]) if False else _block_until_stop()
    prefs = _prefs()
    start = "/onboarding" if not prefs.get("onboarding_done") else "/login"
    kwargs = dict(title="Kairo", url=_base() + start, width=int(prefs.get("w") or 460),
                  height=int(prefs.get("h") or 900), min_size=(390, 640),
                  background_color="#000000", text_select=True)
    if prefs.get("x") is not None and prefs.get("y") is not None:
        kwargs["x"] = int(prefs["x"])
        kwargs["y"] = int(prefs["y"])
    window = webview.create_window(**kwargs)

    def on_closing():
        _remember(window)
        if _prefs().get("background", True):
            try:
                window.hide()
            except Exception:
                pass
            return False
        try:
            import run
            run.shutdown()
        except Exception:
            pass
        return True

    def on_shown():
        _install_status_item(window)

    window.events.closing += on_closing
    window.events.shown += on_shown

    def about():
        window.create_confirmation_dialog("À propos de Kairo",
            "Kairo 1.2.0\nDesk memecoins Solana.\nPaper trading par défaut. Le trading réel est éteint.")

    def preferences():
        window.show()
        window.load_url(_base() + "/app-settings")

    def quit_menu():
        _quit(window)

    menu = []
    try:
        menu = [webview.menu.Menu("Kairo", [
            webview.menu.MenuAction("À propos de Kairo", about),
            webview.menu.MenuAction("Préférences…", preferences),
            webview.menu.MenuSeparator(),
            webview.menu.MenuAction("Quitter Kairo", quit_menu),
        ])]
    except Exception:
        menu = []
    webview.start(menu=menu or None)
    try:
        import run
        run.shutdown()
    except Exception:
        pass
    return 0

def _block_until_stop():
    import run
    while not run._stop.is_set():
        time.sleep(0.5)
    return 0
