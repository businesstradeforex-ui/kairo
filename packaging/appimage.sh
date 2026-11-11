#!/bin/sh
# Usage: packaging/appimage.sh <stage-dir> <output.AppImage> <appimagetool>
set -eu
STAGE=$1
OUT=$2
TOOL=$3
HERE=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
WORKDIR=$(mktemp -d)
APPDIR="$WORKDIR/Kairo.AppDir"
mkdir -p "$APPDIR/opt/kairo" "$APPDIR/usr/share/applications"
cp -a "$STAGE"/. "$APPDIR/opt/kairo/"
cp "$HERE/kairo/static/icon-512.png" "$APPDIR/kairo.png"
cat > "$APPDIR/kairo.desktop" <<'EOF'
[Desktop Entry]
Name=Kairo
Comment=Desk memecoins Solana (papier)
Exec=kairo
Icon=kairo
Type=Application
Categories=Finance;
Terminal=false
EOF
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
export KAIRO_LIVE_ENABLED="${KAIRO_LIVE_ENABLED:-0}"
exec "$HERE/opt/kairo/bin/kairo" "$@"
EOF
chmod +x "$APPDIR/AppRun" "$APPDIR/opt/kairo/bin/kairo"
export APPIMAGE_EXTRACT_AND_RUN=1
ARCH=$(uname -m)
export ARCH
"$TOOL" "$APPDIR" "$OUT"
chmod +x "$OUT"
rm -rf "$WORKDIR"
echo "AppImage $OUT"
