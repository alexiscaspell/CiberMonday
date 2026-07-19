#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  CiberMonday Server — Android APK${NC}"
echo -e "${BLUE}================================================${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker no está instalado.${NC}"
    exit 1
fi
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker no está corriendo.${NC}"
    exit 1
fi

if [ ! -f "docker/Dockerfile.android" ] || [ ! -d "server/android" ]; then
    echo -e "${RED}Estructura del proyecto incompleta (docker/Dockerfile.android, server/android).${NC}"
    exit 1
fi
if [ ! -f "server/web/templates/index.html" ]; then
    echo -e "${RED}No se encontró server/web/templates/index.html${NC}"
    exit 1
fi

mkdir -p dist
docker rm -f cibermonday-android-builder 2>/dev/null || true

echo -e "${YELLOW}Construyendo imagen Docker...${NC}"
docker build \
    --platform linux/amd64 \
    -t cibermonday-android-builder \
    -f docker/Dockerfile.android \
    . || {
    echo -e "${RED}Error al construir la imagen Docker${NC}"
    exit 1
}

docker create --name cibermonday-android-builder cibermonday-android-builder
docker cp cibermonday-android-builder:/app/app/build/outputs/apk/debug/app-debug.apk \
    ./dist/CiberMondayServer.apk || {
    echo -e "${RED}Error al extraer el APK${NC}"
    docker rm cibermonday-android-builder 2>/dev/null || true
    exit 1
}
docker rm cibermonday-android-builder >/dev/null

if [ -f "./dist/CiberMondayServer.apk" ]; then
    echo -e "${GREEN}APK: $(pwd)/dist/CiberMondayServer.apk${NC}"
    echo -e "${CYAN}Instalar: adb install dist/CiberMondayServer.apk${NC}"
else
    echo -e "${RED}No se pudo generar el APK${NC}"
    exit 1
fi
