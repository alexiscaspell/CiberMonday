#!/bin/bash
# CiberMonday - Iniciar Servidor Web (sin Docker)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

echo "========================================"
echo " CiberMonday - Servidor Web"
echo "========================================"

if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "ERROR: Python no encontrado."
    exit 1
fi

echo "Python: $($PYTHON --version)"
echo "[1/2] Instalando dependencias..."
$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet Flask flask-cors requests

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5000}"

echo "[2/2] Iniciando servidor en http://$HOST:$PORT"
HOST=$HOST PORT=$PORT $PYTHON server/web/app.py
