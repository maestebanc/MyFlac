#!/usr/bin/env bash
# Lanza MyFlac localmente asegurando integración completa de iconos en GNOME Shell / Wayland.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -x "$DIR/.venv/bin/python" ]; then
    PYTHON="$DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "Error: No se encontró Python en el sistema." >&2
    exit 1
fi

# Sincronizar iconos y lanzador desktop solo si han cambiado para arranque instantáneo
STAMP="$HOME/.local/share/myflac/.desktop_installed"
if [ ! -f "$STAMP" ] || [ "$DIR/data/com.maestebanc.MyFlac.desktop" -nt "$STAMP" ]; then
    mkdir -p "$HOME/.local/share/icons/hicolor" "$HOME/.local/share/applications" "$HOME/.local/share/myflac"
    if [ -d "$DIR/data/icons/hicolor" ]; then
        cp -ru "$DIR/data/icons/hicolor/"* "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true
    fi
    if [ -f "$DIR/data/com.maestebanc.MyFlac.desktop" ]; then
        sed "s|Exec=myflac|Exec=$DIR/run.sh %F|" "$DIR/data/com.maestebanc.MyFlac.desktop" > "$HOME/.local/share/applications/com.maestebanc.MyFlac.desktop"
    fi
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    command -v gtk4-update-icon-cache >/dev/null 2>&1 && gtk4-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    touch "$STAMP"
fi

export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m myflac "$@"
