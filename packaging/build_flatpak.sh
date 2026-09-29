#!/usr/bin/env bash
# Construye el Flatpak de MyFlac en packaging/dist/:
#   - myflac-<versión>.flatpak      bundle descargable, enlazado al repositorio para recibir actualizaciones
#   - myflac-flatpak-repo.tar.gz    repositorio Flatpak firmado que se publica en GitHub Pages (…/MyFlac/repo)
#
# La firma usa una clave GPG dedicada (por defecto en ~/.local/share/myflac-signing). Sin ella solo se
# genera el bundle, como antes. Variables: MYFLAC_GPG_HOME y MYFLAC_GPG_KEY.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$REPO_ROOT/packaging/dist"
PUBLIC_REPO="$REPO_ROOT/packaging/build/flatpak-repo"
APP_ID="com.maestebanc.MyFlac"
BRANCH="master"
REPO_URL="https://maestebanc.github.io/MyFlac/repo/"
RUNTIME_REPO="https://dl.flathub.org/repo/flathub.flatpakrepo"
GPG_HOME="${MYFLAC_GPG_HOME:-$HOME/.local/share/myflac-signing}"
VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('$REPO_ROOT/pyproject.toml', 'rb'))['project']['version'])")"

mkdir -p "$OUT_DIR"
cd "$REPO_ROOT"
./build-flatpak.sh

GPG_KEY="${MYFLAC_GPG_KEY:-}"
if [ -z "$GPG_KEY" ] && [ -d "$GPG_HOME" ]; then
    GPG_KEY="$(GNUPGHOME="$GPG_HOME" gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^fpr/ {print $10; exit}')"
fi

if [ -z "$GPG_KEY" ]; then
    echo "AVISO: sin clave GPG en $GPG_HOME: solo se genera el bundle, sin repositorio publicable."
    cp "$REPO_ROOT/MyFlac.flatpak" "$OUT_DIR/myflac-${VERSION}.flatpak"
    echo "Listo Flatpak: $OUT_DIR/myflac-${VERSION}.flatpak"
    exit 0
fi

SIGN=(--gpg-sign="$GPG_KEY" --gpg-homedir="$GPG_HOME")
PUBKEY="$REPO_ROOT/packaging/build/myflac-repo.gpg"
mkdir -p "$(dirname "$PUBKEY")"
GNUPGHOME="$GPG_HOME" gpg --export "$GPG_KEY" > "$PUBKEY"

# Repositorio público nuevo en cada versión: un único commit firmado de la app (sin símbolos de
# depuración) y el resumen firmado con los metadatos de AppStream para GNOME Software / Discover
echo "==> Exportando repositorio Flatpak firmado..."
rm -rf "$PUBLIC_REPO"
flatpak build-export "${SIGN[@]}" "$PUBLIC_REPO" "$REPO_ROOT/build-dir" "$BRANCH"
flatpak build-update-repo "${SIGN[@]}" \
    --title="MyFlac" \
    --comment="Bit-perfect Hi-Res audio player for GNOME" \
    --homepage="https://maestebanc.github.io/MyFlac/" \
    --icon="https://maestebanc.github.io/MyFlac/assets/icon-512.png" \
    --default-branch="$BRANCH" \
    "$PUBLIC_REPO"

# Bundle enlazado al repositorio: quien lo instale recibirá las siguientes versiones
flatpak build-bundle "${SIGN[@]}" \
    --repo-url="$REPO_URL" \
    --runtime-repo="$RUNTIME_REPO" \
    --gpg-keys="$PUBKEY" \
    "$PUBLIC_REPO" "$OUT_DIR/myflac-${VERSION}.flatpak" "$APP_ID" "$BRANCH"

tar -C "$PUBLIC_REPO" -czf "$OUT_DIR/myflac-flatpak-repo.tar.gz" .
echo "Listo Flatpak: $OUT_DIR/myflac-${VERSION}.flatpak"
echo "Listo repositorio: $OUT_DIR/myflac-flatpak-repo.tar.gz"
