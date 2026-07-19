#!/bin/bash
set -e

echo "========================================"
echo "Instalador del Servicio CiberMonday"
echo "(Linux - systemd)"
echo "========================================"
echo

# Verificar root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Este script debe ejecutarse como root."
    echo "Usa: sudo bash install_linux.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/cibermonday"
CONFIG_DIR="/etc/cibermonday"
SERVICE_FILE="/etc/systemd/system/cibermonday-client.service"

# [1/7] Verificar Python 3
echo "[1/7] Verificando Python 3..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 no está instalado."
    echo "Instálalo con: sudo apt install python3  (Debian/Ubuntu)"
    echo "             sudo dnf install python3  (Fedora/RHEL)"
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo "  $PYTHON_VERSION encontrado."

# [2/7] Instalar dependencias Python
echo
echo "[2/7] Instalando dependencias Python..."
pip3 install requests 2>/dev/null || python3 -m pip install requests 2>/dev/null || {
    echo "  ADVERTENCIA: No se pudo instalar 'requests' via pip."
    echo "  Intenta: sudo apt install python3-requests  (Debian/Ubuntu)"
}
echo "  Dependencias verificadas."

# [3/7] Copiar archivos
echo
echo "[3/7] Copiando archivos a $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"

cp "$SCRIPT_DIR/client.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/client_base.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/client_linux.py" "$INSTALL_DIR/"
# config_gui es opcional en modo servicio, copiar si existe
[ -f "$SCRIPT_DIR/config_gui.py" ] && cp "$SCRIPT_DIR/config_gui.py" "$INSTALL_DIR/"

chmod 755 "$INSTALL_DIR"/*.py
echo "  Archivos copiados."

# [4/7] Configuración interactiva
echo
echo "[4/7] Configuración del cliente..."
echo "  Ingresa la URL del servidor CiberMonday."
echo
read -p "  URL del servidor [http://localhost:5000]: " SERVER_URL
SERVER_URL=${SERVER_URL:-http://localhost:5000}

read -p "  Intervalo de sincronización en segundos [30]: " SYNC_INTERVAL
SYNC_INTERVAL=${SYNC_INTERVAL:-30}

read -p "  Nombre personalizado para este equipo [$(hostname)]: " CUSTOM_NAME
CUSTOM_NAME=${CUSTOM_NAME:-}

# Extraer IP y puerto de la URL
SERVER_IP=$(echo "$SERVER_URL" | sed -E 's|https?://([^:]+):?.*|\1|')
SERVER_PORT=$(echo "$SERVER_URL" | grep -oP ':\K[0-9]+' || echo "5000")

# Guardar configuración
cat > "$CONFIG_DIR/config.json" << EOJSON
{
  "server_url": "$SERVER_URL",
  "check_interval": 5,
  "sync_interval": $SYNC_INTERVAL,
  "alert_thresholds": [600, 300, 120, 60],
  "max_server_timeouts": 10
$([ -n "$CUSTOM_NAME" ] && echo "  ,\"custom_name\": \"$CUSTOM_NAME\"")
}
EOJSON

# Guardar servidor inicial
cat > "$CONFIG_DIR/servers.json" << EOJSON
[{
  "url": "$SERVER_URL",
  "ip": "$SERVER_IP",
  "port": $SERVER_PORT,
  "last_seen": "$(date -Iseconds)",
  "timeout_count": 0
}]
EOJSON

echo "  Configuración guardada en $CONFIG_DIR/"

# [5/7] Instalar servicio systemd
echo
echo "[5/7] Instalando servicio systemd..."
cp "$SCRIPT_DIR/cibermonday-client.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable cibermonday-client.service
echo "  Servicio instalado y habilitado para inicio automático."

# [6/7] Configurar firewall (ufw si está disponible)
echo
echo "[6/7] Configurando firewall..."
if command -v ufw &> /dev/null; then
    ufw allow 5001/udp comment "CiberMonday Discovery" 2>/dev/null || true
    ufw allow 5002/tcp comment "CiberMonday Diagnostics" 2>/dev/null || true
    echo "  Reglas ufw agregadas (UDP 5001, TCP 5002)."
elif command -v firewall-cmd &> /dev/null; then
    firewall-cmd --permanent --add-port=5001/udp 2>/dev/null || true
    firewall-cmd --permanent --add-port=5002/tcp 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
    echo "  Reglas firewalld agregadas (UDP 5001, TCP 5002)."
else
    echo "  Sin gestor de firewall detectado (ufw/firewalld)."
    echo "  Asegúrate de que los puertos UDP 5001 y TCP 5002 estén abiertos."
fi

# [7/7] Iniciar servicio
echo
echo "[7/7] Iniciando servicio..."
systemctl start cibermonday-client.service

if systemctl is-active --quiet cibermonday-client.service; then
    echo "  Servicio iniciado correctamente."
else
    echo "  ADVERTENCIA: El servicio no se inició. Revisa los logs:"
    echo "    journalctl -u cibermonday-client -f"
fi

echo
echo "========================================"
echo "Instalación completada"
echo "========================================"
echo
echo "Protecciones activas:"
echo "  - Inicio automático con el sistema"
echo "  - Reinicio automático si falla (cada 5 segundos)"
echo "  - Máximo 10 reinicios en 60 segundos"
echo
echo "Comandos de administración:"
echo "  sudo systemctl start cibermonday-client    - Iniciar"
echo "  sudo systemctl stop cibermonday-client     - Detener"
echo "  sudo systemctl restart cibermonday-client  - Reiniciar"
echo "  sudo systemctl status cibermonday-client   - Estado"
echo "  journalctl -u cibermonday-client -f        - Ver logs"
echo
