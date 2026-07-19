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

# [4/4] Eliminar archivos
echo
echo "[4/4] Eliminando archivos..."
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
