#!/bin/bash
# ========================================
# CiberMonday - Iniciar Servidor Web
# ========================================
# Este script instala las dependencias y levanta el servidor Flask.
# Usa Ctrl+C para detenerlo.

set -e

# Ir al directorio raíz del proyecto (un nivel arriba de server/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

echo "========================================"
echo " CiberMonday - Servidor Web"
echo "========================================"
echo ""

# Verificar Python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "ERROR: Python no encontrado. Instalá Python 3 primero."
    exit 1
fi

echo "Python: $($PYTHON --version)"
echo ""

# Instalar dependencias
echo "[1/2] Instalando dependencias..."
$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet Flask flask-cors requests
echo "       Dependencias instaladas."
echo ""

# Configuración
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5000}"

echo "[2/2] Iniciando servidor..."
echo "       URL: http://$HOST:$PORT"
echo "       Broadcast UDP: puerto 5001"
echo ""
echo "       Presiona Ctrl+C para detener."
echo "========================================"
echo ""

# Ejecutar el servidor
cd "$PROJECT_DIR"
HOST=$HOST PORT=$PORT $PYTHON server/app.py
