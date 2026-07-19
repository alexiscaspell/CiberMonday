#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  CiberMonday Client — Android APK${NC}"
echo -e "${BLUE}================================================${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker no está instalado.${NC}"
    exit 1
fi
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker no está corriendo.${NC}"
    exit 1
fi

if [ ! -f "docker/Dockerfile.android-client" ] || [ ! -d "client/android" ]; then
    echo -e "${RED}Estructura incompleta (docker/Dockerfile.android-client, client/android).${NC}"
    exit 1
fi

mkdir -p dist
docker rm -f cibermonday-android-client-builder 2>/dev/null || true

echo -e "${YELLOW}Construyendo imagen Docker...${NC}"
docker build \
    --platform linux/amd64 \
    -t cibermonday-android-client-builder \
    -f docker/Dockerfile.android-client \
    . || {
    echo -e "${RED}Error al construir la imagen Docker${NC}"
    exit 1
}

docker create --name cibermonday-android-client-builder cibermonday-android-client-builder
docker cp cibermonday-android-client-builder:/app/app/build/outputs/apk/debug/app-debug.apk \
    ./dist/CiberMondayClient.apk || {
    echo -e "${RED}Error al extraer el APK${NC}"
    docker rm cibermonday-android-client-builder 2>/dev/null || true
    exit 1
}
docker rm cibermonday-android-client-builder >/dev/null

if [ -f "./dist/CiberMondayClient.apk" ]; then
    echo -e "${GREEN}APK: $(pwd)/dist/CiberMondayClient.apk${NC}"
    echo -e "${YELLOW}Instalar: adb install dist/CiberMondayClient.apk${NC}"
else
    echo -e "${RED}No se pudo generar el APK${NC}"
    exit 1
fi
