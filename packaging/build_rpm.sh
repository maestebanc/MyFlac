#!/usr/bin/env bash
# Construye el paquete .rpm de MyFlac. Requiere rpmbuild (paquete "rpm-build" o "rpm-tools").
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOPDIR="$REPO_ROOT/packaging/build/rpmbuild"
OUT_DIR="$REPO_ROOT/packaging/dist"

mkdir -p "$TOPDIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS,BUILDROOT}

MYFLAC_SRCDIR="$REPO_ROOT" rpmbuild --define "_topdir $TOPDIR" -bb "$REPO_ROOT/packaging/rpm/myflac.spec"

VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('$REPO_ROOT/pyproject.toml', 'rb'))['project']['version'])")"

mkdir -p "$OUT_DIR"
cp "$TOPDIR"/RPMS/noarch/myflac-*.rpm "$OUT_DIR/"
for rpm in "$OUT_DIR"/myflac-${VERSION}-1.*.noarch.rpm; do
    if [ -f "$rpm" ]; then
        cp "$rpm" "$OUT_DIR/myflac-${VERSION}-1.noarch.rpm"
        break
    fi
done
echo "Listo RPM: $(ls "$OUT_DIR"/myflac-${VERSION}-1*.rpm)"
