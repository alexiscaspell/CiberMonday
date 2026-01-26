#!/bin/bash

# Colores para mensajes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${PURPLE}================================================${NC}"
echo -e "${BLUE}     🖥️  CiberMonday Server - Android App${NC}"
echo -e "${PURPLE}================================================${NC}"
echo -e "${YELLOW}📱 Iniciando construcción del APK...${NC}"
echo ""

# Verificar si Docker está instalado
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Error: Docker no está instalado.${NC}"
    echo -e "${YELLOW}Por favor, instala Docker primero: https://docs.docker.com/get-docker/${NC}"
    exit 1
fi

# Verificar que Docker esté corriendo
if ! docker info &> /dev/null; then
    echo -e "${RED}❌ Error: Docker no está corriendo.${NC}"
    echo -e "${YELLOW}Por favor, inicia Docker Desktop o el servicio de Docker.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker está instalado y corriendo${NC}"

# Verificar que existan los archivos necesarios
if [ ! -f "Dockerfile.android" ]; then
    echo -e "${RED}❌ Error: No se encontró Dockerfile.android${NC}"
    echo -e "${YELLOW}Asegúrate de ejecutar este script desde la raíz del proyecto CiberMonday${NC}"
    exit 1
fi

if [ ! -d "android" ]; then
    echo -e "${RED}❌ Error: No se encontró el directorio android/${NC}"
    exit 1
fi

if [ ! -f "server/templates/index.html" ]; then
    echo -e "${RED}❌ Error: No se encontró server/templates/index.html${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Archivos del proyecto verificados${NC}"
echo ""

# Crear directorio de salida si no existe
mkdir -p dist

# Limpiar contenedor anterior si existe
echo -e "${YELLOW}🧹 Limpiando builds anteriores...${NC}"
docker rm -f cibermonday-android-builder 2>/dev/null || true

# Construir la imagen Docker
echo ""
echo -e "${YELLOW}🏗️  Construyendo imagen Docker (esto puede tardar varios minutos la primera vez)...${NC}"
echo -e "${CYAN}   - Descargando Android SDK...${NC}"
echo -e "${CYAN}   - Instalando dependencias de Python (Chaquopy)...${NC}"
echo -e "${CYAN}   - Compilando Flask y dependencias...${NC}"
echo ""

docker build \
    --platform linux/amd64 \
    -t cibermonday-android-builder \
    -f Dockerfile.android \
    . || {
    echo -e "${RED}❌ Error al construir la imagen Docker${NC}"
    exit 1
}

echo ""
echo -e "${GREEN}✓ Imagen Docker construida exitosamente${NC}"

# Crear un contenedor temporal
echo -e "${YELLOW}📦 Creando contenedor temporal...${NC}"
docker create --name cibermonday-android-builder cibermonday-android-builder || {
    echo -e "${RED}❌ Error al crear el contenedor temporal${NC}"
    exit 1
}

# Extraer el APK
echo -e "${YELLOW}📲 Extrayendo el APK...${NC}"
docker cp cibermonday-android-builder:/app/app/build/outputs/apk/debug/app-debug.apk ./dist/CiberMondayServer.apk || {
    echo -e "${RED}❌ Error al extraer el APK${NC}"
    echo -e "${YELLOW}Intentando ver los logs del build...${NC}"
    docker logs cibermonday-android-builder 2>&1 | tail -50
    docker rm cibermonday-android-builder 2>/dev/null
    exit 1
}

# Limpiar el contenedor temporal
echo -e "${YELLOW}🧹 Limpiando contenedor temporal...${NC}"
docker rm cibermonday-android-builder || {
    echo -e "${RED}⚠️  Advertencia: No se pudo limpiar el contenedor temporal${NC}"
}

# Verificar si el APK se generó correctamente
if [ -f "./dist/CiberMondayServer.apk" ]; then
    APK_SIZE=$(du -h ./dist/CiberMondayServer.apk | cut -f1)
    echo ""
    echo -e "${GREEN}================================================${NC}"
    echo -e "${GREEN}🎉 ¡APK generado exitosamente! 🎉${NC}"
    echo -e "${GREEN}================================================${NC}"
    echo ""
    echo -e "${BLUE}📱 Archivo: ${NC}$(pwd)/dist/CiberMondayServer.apk"
    echo -e "${BLUE}📦 Tamaño: ${NC}${APK_SIZE}"
    echo ""
    echo -e "${CYAN}Para instalar en tu dispositivo Android:${NC}"
    echo -e "${YELLOW}  1. Conecta tu dispositivo por USB${NC}"
    echo -e "${YELLOW}  2. Habilita 'Depuración USB' en opciones de desarrollador${NC}"
    echo -e "${YELLOW}  3. Ejecuta: adb install dist/CiberMondayServer.apk${NC}"
    echo ""
    echo -e "${CYAN}O transfiere el APK a tu dispositivo y ábrelo para instalar.${NC}"
    echo ""
else
    echo -e "${RED}❌ Error: No se pudo generar el APK${NC}"
    exit 1
fi
