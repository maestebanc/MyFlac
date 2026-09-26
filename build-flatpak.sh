#!/usr/bin/env bash
# Script de construcción y empaquetado Flatpak para MyFlac (com.maestebanc.MyFlac)
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="com.maestebanc.MyFlac"
MANIFEST="$DIR/$APP_ID.yaml"
BUILD_DIR="$DIR/build-dir"
REPO_DIR="$DIR/repo"
BUNDLE_FILE="$DIR/MyFlac.flatpak"

echo "========================================================"
echo " Invocando compilación Flatpak para $APP_ID"
echo "========================================================"

# 1. Validar archivos de metadatos
echo "[1/4] Validando AppStream metainfo y lanzador desktop..."
if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli validate --no-net "$DIR/data/$APP_ID.metainfo.xml"
fi
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DIR/data/$APP_ID.desktop"
fi

# 2. Compilar mediante flatpak-builder
echo "[2/4] Compilando e instalando con flatpak-builder..."
flatpak-builder \
    --force-clean \
    --user \
    --install \
    --install-deps-from=flathub \
    --repo="$REPO_DIR" \
    "$BUILD_DIR" \
    "$MANIFEST"

# 3. Exportar bundle .flatpak portable
echo "[3/4] Generando bundle Flatpak portable: $BUNDLE_FILE..."
flatpak build-bundle "$REPO_DIR" "$BUNDLE_FILE" "$APP_ID"

echo "[4/4] ¡Compilación finalizada con éxito!"
echo "Para ejecutar la versión Flatpak instalada:"
echo "    flatpak run $APP_ID"
echo ""
echo "Bundle exportado en:"
echo "    $BUNDLE_FILE"
echo "========================================================"
