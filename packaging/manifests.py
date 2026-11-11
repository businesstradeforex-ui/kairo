"""Write Homebrew, Scoop and winget manifests from the files in dist/."""
import argparse, hashlib
from pathlib import Path

def sha256(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def find(dist: Path, suffix):
    matches = sorted(dist.glob(f"Kairo-*{suffix}"))
    if not matches:
        raise SystemExit(f"manquant : *{suffix}")
    return matches[-1]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True)
    p.add_argument("--dist", required=True)
    args = p.parse_args()
    dist = Path(args.dist)
    ver = args.version
    base = f"https://github.com/businesstradeforex-ui/kairo/releases/download/v{ver}"
    arm = find(dist, "macos-arm64.dmg")
    intel = find(dist, "macos-intel.dmg")
    win = find(dist, "windows-x64.zip")
    (dist / "kairo.rb").write_text(f"""cask "kairo" do
  version "{ver}"
  name "Kairo"
  desc "Solana memecoin paper desk. Live trading off by default."
  homepage "https://github.com/businesstradeforex-ui/kairo"

  on_arm do
    sha256 "{sha256(arm)}"
    url "{base}/{arm.name}"
  end
  on_intel do
    sha256 "{sha256(intel)}"
    url "{base}/{intel.name}"
  end

  app "Kairo.app"
  caveats <<~EOS
    Unsigned build. First launch: right-click Kairo and choose Open (Gatekeeper).
    Paper trading only until you opt in. Plug in Ollama or another local server.
  EOS
end
""", encoding="utf-8")
    (dist / "kairo.json").write_text(
        "{\n"
        f'  "version": "{ver}",\n'
        f'  "description": "Solana memecoin paper desk. Live trading off by default.",\n'
        f'  "homepage": "https://github.com/businesstradeforex-ui/kairo",\n'
        '  "license": "MIT",\n'
        f'  "url": "{base}/{win.name}",\n'
        f'  "hash": "{sha256(win)}",\n'
        '  "bin": "Kairo.cmd",\n'
        '  "shortcuts": [["Kairo.cmd", "Kairo"]]\n'
        "}\n",
        encoding="utf-8",
    )
    winget = dist / "winget"
    winget.mkdir(exist_ok=True)
    (winget / "Kairo.installer.yaml").write_text(f"""# Submit this to microsoft/winget-pkgs as a new package.
# PackageIdentifier: Kairo.Kairo
PackageIdentifier: Kairo.Kairo
PackageVersion: {ver}
Installers:
  - Architecture: x64
    InstallerType: zip
    InstallerUrl: {base}/{win.name}
    InstallerSha256: {sha256(win)}
    NestedInstallerType: portable
    NestedInstallerFiles:
      - RelativeFilePath: Kairo.cmd
        PortableCommandAlias: kairo
ManifestType: installer
ManifestVersion: 1.6.0
""", encoding="utf-8")
    print("manifests ok")

if __name__ == "__main__":
    main()
