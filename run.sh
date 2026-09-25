#!/usr/bin/env bash
# Lanza MyFlac localmente usando el entorno virtual del proyecto o Python del sistema.
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

export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m myflac "$@"
