#!/usr/bin/env bash
# Construye el paquete Flatpak de MyFlac en packaging/dist/
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$REPO_ROOT/packaging/dist"
mkdir -p "$OUT_DIR"
VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('$REPO_ROOT/pyproject.toml', 'rb'))['project']['version'])")"

cd "$REPO_ROOT"
./build-flatpak.sh

cp "$REPO_ROOT/MyFlac.flatpak" "$OUT_DIR/myflac-${VERSION}.flatpak"
echo "Listo Flatpak: $OUT_DIR/myflac-${VERSION}.flatpak"
