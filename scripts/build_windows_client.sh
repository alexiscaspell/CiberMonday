#!/bin/bash
# Compila el cliente Windows con PyInstaller (ejecutar desde client/windows o vía Docker).
set -euo pipefail

echo "========================================"
echo "Compilador de CiberMonday Client"
echo "========================================"

# Si estamos en /app (Docker), el código está en client/windows
if [ -d "/app/client/windows" ]; then
    cd /app/client/windows
elif [ -f "client.py" ]; then
    :
elif [ -d "../windows" ] && [ -f "../windows/client.py" ]; then
    cd ../windows
else
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    cd "$SCRIPT_DIR/../client/windows"
fi

if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    PIP_CMD="pip3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
    PIP_CMD="pip"
else
    echo "ERROR: Python no está instalado"
    exit 1
fi

if [[ "${OSTYPE:-}" == "msys" || "${OSTYPE:-}" == "win32" || "${OSTYPE:-}" == "cygwin" ]]; then
    DATA_SEP=";"
else
    DATA_SEP=":"
fi

echo "Usando: $PYTHON_CMD en $(pwd)"
$PIP_CMD uninstall -y typing pathlib 2>/dev/null || true
$PIP_CMD install pyinstaller

$PYTHON_CMD -m PyInstaller --onefile \
    --name "CiberMondayClient" \
    --hidden-import "client_base" \
    --hidden-import "client_windows" \
    --hidden-import "winreg" \
    --hidden-import "win32serviceutil" \
    --hidden-import "win32service" \
    --hidden-import "win32event" \
    --hidden-import "servicemanager" \
    --hidden-import "win32timezone" \
    --hidden-import "protection" \
    --hidden-import "registry_manager" \
    --hidden-import "config_gui" \
    --hidden-import "requests" \
    --hidden-import "ctypes" \
    --hidden-import "ctypes.wintypes" \
    client.py

$PYTHON_CMD -m PyInstaller --onefile \
    --name "CiberMondayService" \
    --add-data "config.py${DATA_SEP}." \
    --hidden-import "winreg" \
    --hidden-import "win32serviceutil" \
    --hidden-import "win32service" \
    --hidden-import "win32event" \
    --hidden-import "servicemanager" \
    --hidden-import "win32timezone" \
    --hidden-import "protection" \
    --hidden-import "firewall_manager" \
    --hidden-import "ctypes" \
    --hidden-import "ctypes.wintypes" \
    service.py

$PYTHON_CMD -m PyInstaller --onefile \
    --name "CiberMondayWatchdog" \
    --hidden-import "winreg" \
    --hidden-import "subprocess" \
    watchdog.py

# Copiar a /app/dist si estamos en Docker
if [ -d "/app/dist" ]; then
    mkdir -p /app/dist
    cp -f dist/*.exe /app/dist/ 2>/dev/null || true
fi

echo "Compilación completada. Salida: $(pwd)/dist"
