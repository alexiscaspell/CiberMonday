#!/bin/bash
# Script para iniciar el servidor con Docker Compose

echo "========================================"
echo "Iniciando CiberMonday Server"
echo "========================================"
echo ""

# Verificar si Docker está instalado
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker no está instalado"
    echo "Por favor instala Docker desde https://www.docker.com/"
    exit 1
fi

# Verificar si Docker Compose está instalado
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose no está instalado"
    echo "Por favor instala Docker Compose"
    exit 1
fi

# Verificar si Docker está corriendo
if ! docker info &> /dev/null; then
    echo "ERROR: Docker no está corriendo"
    echo "Por favor inicia Docker Desktop o el daemon de Docker"
    exit 1
fi

# Usar docker compose (nuevo) o docker-compose (viejo)
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Verificar si se quiere modo desarrollo
if [ "$1" == "dev" ]; then
    echo "Modo: Desarrollo (con hot-reload)"
    $COMPOSE_CMD -f docker-compose.dev.yml up --build
else
    echo "Modo: Producción"
    $COMPOSE_CMD up -d --build
    
    echo ""
    echo "========================================"
    echo "Servidor iniciado!"
    echo "========================================"
    echo ""
    echo "El servidor está corriendo en: http://localhost:5000"
    echo ""
    echo "Comandos útiles:"
    echo "  docker compose logs -f          # Ver logs"
    echo "  docker compose stop              # Detener servidor"
    echo "  docker compose restart           # Reiniciar servidor"
    echo "  docker compose down              # Detener y eliminar contenedor"
    echo ""
fi
