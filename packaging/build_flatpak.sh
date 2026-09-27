#!/usr/bin/env bash
# Construye el paquete Flatpak de MyFlac en packaging/dist/
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$REPO_ROOT/packaging/dist"
mkdir -p "$OUT_DIR"

cd "$REPO_ROOT"
./build-flatpak.sh

cp "$REPO_ROOT/MyFlac.flatpak" "$OUT_DIR/myflac-0.1.0.flatpak"
echo "Listo Flatpak: $OUT_DIR/myflac-0.1.0.flatpak"
