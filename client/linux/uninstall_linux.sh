#!/bin/bash
set -e

echo "========================================"
echo "Desinstalador del Servicio CiberMonday"
echo "(Linux - systemd)"
echo "========================================"
echo

# Verificar root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Este script debe ejecutarse como root."
    echo "Usa: sudo bash uninstall_linux.sh"
    exit 1
fi

echo "ATENCION: Esto desinstalará completamente el servicio CiberMonday."
echo "El cliente dejará de ejecutarse y el equipo ya no será controlado."
echo
read -p "Escribí SI para confirmar la desinstalación: " CONFIRM
if [ "$CONFIRM" != "SI" ]; then
    echo "Desinstalación cancelada."
    exit 0
fi

INSTALL_DIR="/opt/cibermonday"
CONFIG_DIR="/etc/cibermonday"
SERVICE_FILE="/etc/systemd/system/cibermonday-client.service"

# [1/4] Detener y deshabilitar servicio
echo
echo "[1/4] Deteniendo servicio..."
systemctl stop cibermonday-client.service 2>/dev/null || true
systemctl disable cibermonday-client.service 2>/dev/null || true
echo "  Servicio detenido y deshabilitado."

# [2/4] Eliminar archivos de servicio
echo
echo "[2/4] Eliminando servicio systemd..."
rm -f "$SERVICE_FILE"
systemctl daemon-reload
echo "  Archivo de servicio eliminado."

# [3/4] Eliminar reglas de firewall
echo
echo "[3/4] Eliminando reglas de firewall..."
# Política de corte CiberMonday (nft/iptables)
if command -v nft &> /dev/null; then
    nft delete table inet cibermonday 2>/dev/null || true
    echo "  Tabla nft cibermonday eliminada (si existía)."
fi
if command -v iptables &> /dev/null; then
    iptables -D OUTPUT -j CIBERMONDAY 2>/dev/null || true
    iptables -F CIBERMONDAY 2>/dev/null || true
    iptables -X CIBERMONDAY 2>/dev/null || true
fi
if command -v ufw &> /dev/null; then
    ufw delete allow 5001/udp 2>/dev/null || true
    ufw delete allow 5002/tcp 2>/dev/null || true
    echo "  Reglas ufw eliminadas."
elif command -v firewall-cmd &> /dev/null; then
    firewall-cmd --permanent --remove-port=5001/udp 2>/dev/null || true
    firewall-cmd --permanent --remove-port=5002/tcp 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
    echo "  Reglas firewalld eliminadas."
else
    echo "  Sin gestor de firewall detectado."
fi

# [4/5] Quitar CA MITM del trust store
echo
echo "[4/5] Eliminando CA MITM del sistema..."
rm -f /usr/local/share/ca-certificates/cibermonday-mitm-ca.crt
if command -v update-ca-certificates >/dev/null 2>&1; then
    update-ca-certificates --fresh >/dev/null 2>&1 || true
fi
if [ -f "$INSTALL_DIR/mitm_tls.py" ]; then
    python3 -c "import sys; sys.path.insert(0, '$INSTALL_DIR'); import mitm_tls; mitm_tls.uninstall_ca_trust()" 2>/dev/null || true
fi
echo "  CA MITM eliminada (si existía)."

# [5/5] Eliminar archivos
echo
echo "[5/5] Eliminando archivos..."
read -p "  ¿Eliminar archivos del cliente en $INSTALL_DIR? (s/N): " DEL_FILES
if [ "$DEL_FILES" = "s" ] || [ "$DEL_FILES" = "S" ]; then
    rm -rf "$INSTALL_DIR"
    echo "  Archivos del cliente eliminados."
else
    echo "  Archivos del cliente conservados en $INSTALL_DIR."
fi

read -p "  ¿Eliminar configuración en $CONFIG_DIR? (s/N): " DEL_CONFIG
if [ "$DEL_CONFIG" = "s" ] || [ "$DEL_CONFIG" = "S" ]; then
    rm -rf "$CONFIG_DIR"
    echo "  Configuración eliminada."
else
    echo "  Configuración conservada en $CONFIG_DIR."
fi

echo
echo "========================================"
echo "Servicio desinstalado exitosamente"
echo "========================================"
echo
echo "El servicio CiberMonday ha sido removido."
echo "El equipo ya no será controlado por CiberMonday."
echo
