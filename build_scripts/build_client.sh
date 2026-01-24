#!/bin/bash
# Script para compilar el cliente CiberMonday como .exe
# Funciona en Windows (nativo) o Linux (con wine)

set -e

echo "========================================"
echo "Compilador de CiberMonday Client"
echo "========================================"
echo ""

cd client

# Detectar Python (python3 en macOS/Linux, python en Windows)
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

# Detectar separador para --add-data (; en Windows, : en Unix)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
    DATA_SEP=";"
    IS_WINDOWS=true
else
    DATA_SEP=":"
    IS_WINDOWS=false
fi

echo "Usando: $PYTHON_CMD"
echo "Sistema: $OSTYPE"
echo ""

# Advertencia sobre compilación de Windows desde macOS/Linux
if [ "$IS_WINDOWS" = false ]; then
    echo "ADVERTENCIA: Estás compilando ejecutables de Windows desde macOS/Linux"
    echo "Esto puede no funcionar correctamente sin wine o una máquina Windows."
    echo "Para producción, se recomienda usar GitHub Actions o compilar en Windows."
    echo ""
fi

echo "Instalando PyInstaller..."
# Remover paquetes incompatibles con PyInstaller si existen
$PIP_CMD uninstall -y typing pathlib 2>/dev/null || true
$PIP_CMD install pyinstaller

echo ""
echo "Compilando cliente..."
echo ""

# Compilar el cliente principal
$PYTHON_CMD -m PyInstaller --onefile \
    --name "CiberMondayClient" \
    --add-data "config.py${DATA_SEP}." \
    --hidden-import "winreg" \
    --hidden-import "win32serviceutil" \
    --hidden-import "win32service" \
    --hidden-import "win32event" \
    --hidden-import "servicemanager" \
    --hidden-import "protection" \
    --hidden-import "registry_manager" \
    --hidden-import "requests" \
    --hidden-import "ctypes" \
    --hidden-import "ctypes.wintypes" \
    client.py

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: La compilación del cliente falló"
    exit 1
fi

echo ""
echo "Compilando servicio..."
echo ""

# Compilar el servicio
$PYTHON_CMD -m PyInstaller --onefile \
    --name "CiberMondayService" \
    --add-data "config.py${DATA_SEP}." \
    --hidden-import "winreg" \
    --hidden-import "win32serviceutil" \
    --hidden-import "win32service" \
    --hidden-import "win32event" \
    --hidden-import "servicemanager" \
    --hidden-import "protection" \
    --hidden-import "registry_manager" \
    --hidden-import "requests" \
    --hidden-import "ctypes" \
    --hidden-import "ctypes.wintypes" \
    service.py

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: La compilación del servicio falló"
    exit 1
fi

echo ""
echo "Compilando watchdog..."
echo ""

# Compilar el watchdog
$PYTHON_CMD -m PyInstaller --onefile \
    --name "CiberMondayWatchdog" \
    --hidden-import "winreg" \
    --hidden-import "subprocess" \
    watchdog.py

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: La compilación del watchdog falló"
    exit 1
fi

echo ""
echo "========================================"
echo "Compilación completada!"
echo "========================================"
echo ""
echo "Los ejecutables están en la carpeta 'dist':"
echo "  - CiberMondayClient.exe"
echo "  - CiberMondayService.exe"
echo "  - CiberMondayWatchdog.exe"
echo ""
