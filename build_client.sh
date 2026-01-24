#!/bin/bash
# Script principal para compilar el cliente usando Docker
# NOTA: Compilar .exe de Windows desde Linux requiere wine y es complejo
# RECOMENDADO: Usar GitHub Actions para compilación automática (ver BUILD.md)

set -e

echo "========================================"
echo "Compilador CiberMonday Client (.exe)"
echo "========================================"
echo ""
echo "NOTA: Para compilar .exe de Windows, se recomienda:"
echo "  1. Usar GitHub Actions (automático en cada push)"
echo "  2. Compilar directamente en Windows con build_exe.bat"
echo ""
echo "Este script Docker está principalmente para desarrollo."
echo ""

# Verificar si Docker está instalado
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker no está instalado"
    echo "Por favor instala Docker desde https://www.docker.com/"
    echo ""
    echo "Alternativa: Usa GitHub Actions para compilación automática"
    exit 1
fi

# Verificar si Docker está corriendo
if ! docker info &> /dev/null; then
    echo "ERROR: Docker no está corriendo"
    echo "Por favor inicia Docker Desktop o el daemon de Docker"
    exit 1
fi

echo "Construyendo imagen Docker..."
docker build -f Dockerfile.client -t cibermonday-client-builder .

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Falló la construcción de la imagen Docker"
    exit 1
fi

echo ""
echo "IMPORTANTE: Compilar .exe de Windows desde Linux requiere wine."
echo "Para producción, usa GitHub Actions o compila en Windows directamente."
echo ""
echo "¿Continuar de todos modos? (s/n)"
read -r response
if [[ ! "$response" =~ ^[Ss]$ ]]; then
    echo "Compilación cancelada."
    exit 0
fi

echo ""
echo "Compilando ejecutables..."
echo ""

# Crear directorio de salida si no existe
mkdir -p dist

# Ejecutar la compilación en el contenedor
docker run --rm \
    -v "$(pwd)/dist:/app/dist" \
    -v "$(pwd)/client:/app/client" \
    -v "$(pwd)/requirements.txt:/app/requirements.txt" \
    cibermonday-client-builder \
    bash -c "cd /app && bash build_client.sh"

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Falló la compilación"
    echo ""
    echo "Sugerencia: Usa GitHub Actions para compilación automática en Windows"
    echo "O compila directamente en Windows con: client/build_exe.bat"
    exit 1
fi

echo ""
echo "========================================"
echo "¡Compilación completada!"
echo "========================================"
echo ""
echo "Los ejecutables deberían estar en la carpeta 'dist/':"
ls -lh dist/*.exe 2>/dev/null || echo "  (Nota: Los .exe pueden no funcionar correctamente desde Linux)"
echo ""
echo "Para producción, descarga los ejecutables desde GitHub Releases"
echo "(se generan automáticamente con GitHub Actions)"
echo ""
