"""Console script for pipx / pip. The trading code stays in the kairo package directory
and is executed as scripts (flat imports), the same way the desktop bundle runs it.
"""
import os, sys
from pathlib import Path

def app_dir():
    here = Path(__file__).resolve().parent
    bundled = here / "kairo"
    if (bundled / "launcher.py").is_file():
        return bundled
    raise SystemExit("Dossier kairo introuvable à côté de kairo_launch.py")

def main():
    app = app_dir()
    os.environ.setdefault("KAIRO_NO_BROWSER", "0")
    os.execv(sys.executable, [sys.executable, str(app / "launcher.py"), *sys.argv[1:]])

if __name__ == "__main__":
    main()
