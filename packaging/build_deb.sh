#!/usr/bin/env bash
# Construye el paquete .deb de MyFlac. Usa dpkg-deb si está disponible, o tar+ar en su defecto.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('$REPO_ROOT/pyproject.toml', 'rb'))['project']['version'])")-1"
WORK="$REPO_ROOT/packaging/build/deb/myflac"
OUT_DIR="$REPO_ROOT/packaging/dist"

rm -rf "$WORK"
mkdir -p "$WORK/DEBIAN" "$WORK/usr/bin" "$WORK/usr/lib/python3/dist-packages" \
         "$WORK/usr/share/applications" "$WORK/usr/share/metainfo"

cp -r "$REPO_ROOT/myflac" "$WORK/usr/lib/python3/dist-packages/"
find "$WORK/usr/lib/python3/dist-packages/myflac" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

cp "$REPO_ROOT/data/com.maestebanc.MyFlac.desktop" "$WORK/usr/share/applications/"
cp "$REPO_ROOT/data/com.maestebanc.MyFlac.metainfo.xml" "$WORK/usr/share/metainfo/"

for size in 16 22 24 32 48 64 128 256 512; do
  mkdir -p "$WORK/usr/share/icons/hicolor/${size}x${size}/apps"
  cp "$REPO_ROOT/data/icons/hicolor/${size}x${size}/apps/com.maestebanc.MyFlac.png" \
     "$WORK/usr/share/icons/hicolor/${size}x${size}/apps/"
done
mkdir -p "$WORK/usr/share/icons/hicolor/scalable/apps"
cp "$REPO_ROOT/data/icons/hicolor/scalable/apps/com.maestebanc.MyFlac.svg" \
   "$WORK/usr/share/icons/hicolor/scalable/apps/"
mkdir -p "$WORK/usr/share/icons/hicolor/symbolic/apps"
cp "$REPO_ROOT/data/icons/hicolor/symbolic/apps/com.maestebanc.MyFlac-symbolic.svg" \
   "$WORK/usr/share/icons/hicolor/symbolic/apps/"

cat > "$WORK/usr/bin/myflac" <<'LAUNCHER'
#!/usr/bin/python3
import sys
from myflac.app import main
if __name__ == "__main__":
    sys.exit(main())
LAUNCHER

sed "s/@VERSION@/${VERSION}/" "$REPO_ROOT/packaging/deb/control.template" > "$WORK/DEBIAN/control"
cp "$REPO_ROOT/packaging/deb/postinst" "$WORK/DEBIAN/postinst"

find "$WORK" -type d -exec chmod 755 {} \;
find "$WORK" -type f -not -path "*/DEBIAN/postinst" -not -path "*/usr/bin/myflac" -exec chmod 644 {} \;
chmod 755 "$WORK/DEBIAN/postinst" "$WORK/usr/bin/myflac"

mkdir -p "$OUT_DIR"
if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --root-owner-group --build "$WORK" "$OUT_DIR/myflac_${VERSION}_all.deb"
else
    ARCHIVE_DIR="$(mktemp -d)"
    echo "2.0" > "$ARCHIVE_DIR/debian-binary"
    tar --numeric-owner --owner=0 --group=0 -cJf "$ARCHIVE_DIR/control.tar.xz" -C "$WORK/DEBIAN" .
    tar --numeric-owner --owner=0 --group=0 --exclude="./DEBIAN" -cJf "$ARCHIVE_DIR/data.tar.xz" -C "$WORK" .
    ar -rcs "$OUT_DIR/myflac_${VERSION}_all.deb" "$ARCHIVE_DIR/debian-binary" "$ARCHIVE_DIR/control.tar.xz" "$ARCHIVE_DIR/data.tar.xz"
    rm -rf "$ARCHIVE_DIR"
fi
echo "Listo DEB: $OUT_DIR/myflac_${VERSION}_all.deb"
