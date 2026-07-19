#!/bin/bash
# Compilar cliente Windows (.exe) v?a Docker / wine (dev). Prefer? GitHub Actions o build en Windows.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================"
echo "Compilador CiberMonday Client (.exe)"
echo "========================================"
echo ""
echo "Recomendado: GitHub Actions o client/windows/build_exe.bat en Windows."
echo ""

if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker no est? instalado"
    exit 1
fi
if ! docker info &> /dev/null; then
    echo "ERROR: Docker no est? corriendo"
    exit 1
fi

echo "Construyendo imagen Docker..."
docker build -f docker/Dockerfile.client -t cibermonday-client-builder .

echo ""
echo "?Continuar de todos modos? (s/n)"
read -r response
if [[ ! "$response" =~ ^[Ss]$ ]]; then
    echo "Compilaci?n cancelada."
    exit 0
fi

mkdir -p dist
docker run --rm \
    -v "$(pwd)/dist:/app/dist" \
    -v "$(pwd)/client/windows:/app/client/windows" \
    -v "$(pwd)/requirements.txt:/app/requirements.txt" \
    cibermonday-client-builder \
    bash -c "cd /app && bash build_windows_client.sh"

echo ""
echo "Ejecutables en dist/ (pueden no funcionar si se compil? desde Linux sin wine)."
ls -lh dist/*.exe 2>/dev/null || true
