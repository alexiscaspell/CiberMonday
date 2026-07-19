#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================"
echo "Iniciando CiberMonday Server"
echo "========================================"

if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker no está instalado"
    exit 1
fi
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose no está instalado"
    exit 1
fi
if ! docker info &> /dev/null; then
    echo "ERROR: Docker no está corriendo"
    exit 1
fi

if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

COMPOSE_FILE="docker/docker-compose.yml"

echo "Modo: Producción"
$COMPOSE_CMD -f "$COMPOSE_FILE" up -d --build

echo ""
echo "Servidor en http://localhost:5000"
echo "Logs: $COMPOSE_CMD -f $COMPOSE_FILE logs -f"
echo "Stop: $COMPOSE_CMD -f $COMPOSE_FILE stop"
