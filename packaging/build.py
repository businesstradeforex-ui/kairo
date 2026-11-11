"""Build a self-contained Kairo folder: CPython + dependencies + the app.

PyInstaller is a poor fit here. The desk is four processes started from .py files
(server, desk, intensif, local AI). A standalone CPython (python-build-standalone)
keeps that layout and still needs nothing else installed.

Usage:
  python3 packaging/build.py --target linux-x64 --version 1.0.0
"""
import argparse, hashlib, os, platform, shutil, stat, subprocess, sys, tarfile, tempfile, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kairo"
REQ = ROOT / "requirements.txt"
RELEASE = os.environ.get("KAIRO_PYTHON_RELEASE", "20261003")
CPYTHON = os.environ.get("KAIRO_CPYTHON", "3.12.15")

TARGETS = {
    "linux-x64": "x86_64-unknown-linux-gnu",
    "linux-arm64": "aarch64-unknown-linux-gnu",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-intel": "x86_64-apple-darwin",
    "windows-x64": "x86_64-pc-windows-msvc",
}

SKIP_NAMES = {"__pycache__", ".pyc", "desk.db", "web.db", "secret.key", "agent_token.txt", ".env"}

def asset_name(triple):
    return f"cpython-{CPYTHON}+{RELEASE}-{triple}-install_only.tar.gz"

def download(url, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    print(f"download {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "kairo-release"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest

def ignore_copy(_dir, names):
    return [n for n in names if n in SKIP_NAMES or n.endswith(".pyc") or n.endswith(".db")]

def copy_app(dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(APP, dest, ignore=ignore_copy)
    for p in dest.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)

def python_bin(prefix: Path):
    for rel in ("bin/python3", "bin/python", "python.exe", "python3.exe"):
        p = prefix / rel
        if p.exists():
            return p
    raise SystemExit(f"python introuvable dans {prefix}")

def pip_install(py: Path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONNOUSERSITE="1", PIP_USER="0")
    subprocess.check_call([str(py), "-s", "-m", "pip", "install", "--upgrade", "pip"], env=env)
    subprocess.check_call([str(py), "-s", "-m", "pip", "install", "--no-cache-dir", "-r", str(REQ)], env=env)

README = """Kairo {version} — paper trading
================================

Memecoins are extremely risky. This build starts in PAPER mode.
Live trading stays off (KAIRO_LIVE_ENABLED defaults to 0).

Launch
------
macOS:   open Kairo.app   (first time: right-click > Open, because the app is unsigned)
Windows: double-click Kairo.cmd
Linux:   ./bin/kairo

Data (not in this folder): the first launch creates your data directory and a secret key.
  macOS:   ~/Library/Application Support/Kairo
  Windows: %LOCALAPPDATA%\\Kairo
  Linux:   ~/.local/share/kairo

Local AI (optional)
-------------------
The desk runs without a model. To let the local AI translate orders, start one of:
  Ollama      http://127.0.0.1:11434     ollama pull qwen3:4b
  LM Studio   http://127.0.0.1:1234/v1
  llama.cpp   http://127.0.0.1:8080/v1
Then reload http://127.0.0.1:8787/setup

No tokens, API keys or databases are inside this archive.
"""

def write_readme(dest: Path, version):
    (dest / "README.txt").write_text(README.format(version=version), encoding="utf-8")

UNIX_LAUNCH = """#!/bin/sh
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
export KAIRO_LIVE_ENABLED="${KAIRO_LIVE_ENABLED:-0}"
export KAIRO_ENV="${KAIRO_ENV:-production}"
export DESK_HOST="${DESK_HOST:-127.0.0.1}"
export DESK_PORT="${DESK_PORT:-8787}"
export KAIRO_MULTIUSER="${KAIRO_MULTIUSER:-1}"
PY="$ROOT/python/bin/python3"
[ -x "$PY" ] || PY="$ROOT/python/bin/python"
exec "$PY" "$ROOT/app/launcher.py" "$@"
"""

MAC_LAUNCH = """#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../Resources" && pwd)"
export KAIRO_LIVE_ENABLED="${KAIRO_LIVE_ENABLED:-0}"
export KAIRO_ENV="${KAIRO_ENV:-production}"
export DESK_HOST="${DESK_HOST:-127.0.0.1}"
export DESK_PORT="${DESK_PORT:-8787}"
export KAIRO_MULTIUSER="${KAIRO_MULTIUSER:-1}"
PY="$ROOT/python/bin/python3"
[ -x "$PY" ] || PY="$ROOT/python/bin/python"
exec "$PY" "$ROOT/app/launcher.py" "$@"
"""

WIN_LAUNCH = """@echo off
setlocal
set "ROOT=%~dp0"
if not defined KAIRO_LIVE_ENABLED set "KAIRO_LIVE_ENABLED=0"
if not defined KAIRO_ENV set "KAIRO_ENV=production"
if not defined DESK_HOST set "DESK_HOST=127.0.0.1"
if not defined DESK_PORT set "DESK_PORT=8787"
if not defined KAIRO_MULTIUSER set "KAIRO_MULTIUSER=1"
"%ROOT%python\\python.exe" "%ROOT%app\\launcher.py" %*
"""

def mark_exec(path: Path):
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

def info_plist(version):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Kairo</string>
  <key>CFBundleDisplayName</key><string>Kairo</string>
  <key>CFBundleIdentifier</key><string>io.kairo.desktop</string>
  <key>CFBundleVersion</key><string>{version}</string>
  <key>CFBundleShortVersionString</key><string>{version}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>kairo</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
"""

def assemble(target, version, tarball: Path, out_dir: Path):
    work = Path(tempfile.mkdtemp(prefix="kairo-bundle-"))
    print(f"extract {tarball} -> {work}", flush=True)
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(work, filter="data")
    prefix = work / "python"
    if not prefix.exists():
        raise SystemExit("archive sans dossier python/")
    stage = work / "stage"
    if target.startswith("macos"):
        app = stage / "Kairo.app" / "Contents"
        (app / "MacOS").mkdir(parents=True)
        res = app / "Resources"
        shutil.move(str(prefix), str(res / "python"))
        copy_app(res / "app")
        (app / "Info.plist").write_text(info_plist(version), encoding="utf-8")
        launch = app / "MacOS" / "kairo"
        launch.write_text(MAC_LAUNCH, encoding="utf-8")
        mark_exec(launch)
        write_readme(stage, version)
        py = python_bin(res / "python")
    elif target.startswith("windows"):
        stage.mkdir(parents=True)
        shutil.move(str(prefix), str(stage / "python"))
        copy_app(stage / "app")
        (stage / "Kairo.cmd").write_text(WIN_LAUNCH, encoding="utf-8")
        write_readme(stage, version)
        py = python_bin(stage / "python")
    else:
        stage.mkdir(parents=True)
        shutil.move(str(prefix), str(stage / "python"))
        copy_app(stage / "app")
        (stage / "bin").mkdir()
        launch = stage / "bin" / "kairo"
        launch.write_text(UNIX_LAUNCH, encoding="utf-8")
        mark_exec(launch)
        desktop = stage / "share" / "applications"
        desktop.mkdir(parents=True)
        (desktop / "kairo.desktop").write_text(
            "[Desktop Entry]\nName=Kairo\nComment=Desk memecoins Solana (papier)\n"
            "Exec=kairo\nTerminal=false\nType=Application\nCategories=Finance;\n",
            encoding="utf-8",
        )
        write_readme(stage, version)
        py = python_bin(stage / "python")
    # Only install wheels when the bundled interpreter can run here.
    if _can_run(py):
        pip_install(py)
    else:
        print(f"skip pip on this host (interpreter {py} is for another OS)", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"Kairo-{version}-{target}"
    if final.exists():
        shutil.rmtree(final)
    shutil.move(str(stage), str(final))
    shutil.rmtree(work, ignore_errors=True)
    return final

def _can_run(py: Path):
    if platform.system() == "Windows":
        return py.name.lower().startswith("python")
    if py.suffix == ".exe":
        return False
    try:
        subprocess.check_call([str(py), "-c", "import sys"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def make_tar(folder: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(folder, arcname=folder.name)
    return dest

def make_zip(folder: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    shutil.make_archive(str(dest.with_suffix("")), "zip", folder.parent, folder.name)
    return dest

def make_deb(folder: Path, version, arch, dest: Path):
    """arch is amd64 or arm64. The payload is /opt/kairo."""
    deb_arch = {"linux-x64": "amd64", "linux-arm64": "arm64"}[arch]
    tree = Path(tempfile.mkdtemp(prefix="kairo-deb-"))
    opt = tree / "opt" / "kairo"
    shutil.copytree(folder, opt)
    bin_dir = tree / "usr" / "bin"
    bin_dir.mkdir(parents=True)
    link = bin_dir / "kairo"
    link.write_text("#!/bin/sh\nexec /opt/kairo/bin/kairo \"$@\"\n", encoding="utf-8")
    mark_exec(link)
    debian = tree / "DEBIAN"
    debian.mkdir()
    (debian / "control").write_text(
        f"Package: kairo\nVersion: {version}\nArchitecture: {deb_arch}\nMaintainer: Kairo contributors\n"
        "Description: Solana memecoin paper desk\n"
        " Bundled CPython. Paper trading by default. Live trading off.\n",
        encoding="utf-8",
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["dpkg-deb", "--root-owner-group", "--build", str(tree), str(dest)])
    shutil.rmtree(tree, ignore_errors=True)
    return dest

def sha256(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--target", required=True, choices=sorted(TARGETS))
    p.add_argument("--version", required=True)
    p.add_argument("--out", default=str(ROOT / "dist"))
    p.add_argument("--formats", default="tar", help="comma list: tar,zip,deb")
    p.add_argument("--tarball", default="", help="existing python tarball (skip download)")
    args = p.parse_args(argv)
    triple = TARGETS[args.target]
    out = Path(args.out)
    if args.tarball:
        ball = Path(args.tarball)
    else:
        name = asset_name(triple)
        url = f"https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE}/{name}"
        ball = download(url, ROOT / "packaging" / "cache" / name)
    folder = assemble(args.target, args.version, ball, out / "tree")
    built = []
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    for fmt in formats:
        if fmt == "tar":
            built.append(make_tar(folder, out / f"Kairo-{args.version}-{args.target}.tar.gz"))
        elif fmt == "zip":
            built.append(make_zip(folder, out / f"Kairo-{args.version}-{args.target}.zip"))
        elif fmt == "deb":
            if not args.target.startswith("linux"):
                raise SystemExit("deb is linux only")
            built.append(make_deb(folder, args.version, args.target, out / f"Kairo-{args.version}-{args.target}.deb"))
        else:
            raise SystemExit(f"format inconnu {fmt}")
    for path in built:
        print(f"{sha256(path)}  {path.name}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
