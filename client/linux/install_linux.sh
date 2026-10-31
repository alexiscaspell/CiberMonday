#!/bin/bash
# Instala el cliente Linux (systemd).
#
# Uso:
#   sudo bash install_linux.sh
#   sudo bash install_linux.sh --user niño
#
# En el menú interactivo podés elegir el usuario objetivo (default: quien
# invocó sudo, o el usuario actual). El servicio sigue corriendo como root;
# target_user se usa para bloqueo/notificaciones y CA en el perfil del niño.

set -e

TARGET_USER_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --user|-u)
            TARGET_USER_ARG="${2:-}"
            if [[ -z "$TARGET_USER_ARG" ]]; then
                echo "ERROR: --user requiere un nombre de usuario"
                exit 1
            fi
            shift 2
            ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Opción desconocida: $1 (usa --help)"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "Instalador del Servicio CiberMonday"
echo "(Linux - systemd)"
echo "========================================"
echo

# Verificar root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Este script debe ejecutarse como root."
    echo "Usa: sudo bash install_linux.sh [--user USUARIO]"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/cibermonday"
CONFIG_DIR="/etc/cibermonday"
SERVICE_FILE="/etc/systemd/system/cibermonday-client.service"

# Default: quien corrió sudo (no root), si no logname
_default_target_user() {
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        echo "$SUDO_USER"
        return
    fi
    local lg
    lg="$(logname 2>/dev/null || true)"
    if [[ -n "$lg" && "$lg" != "root" ]]; then
        echo "$lg"
        return
    fi
    echo ""
}

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
_install_py_mod() {
    # $1=import_name $2=apt_pkg $3=pip_name
    local imp="$1" apt_pkg="$2" pip_name="$3"
    if python3 -c "import $imp" 2>/dev/null; then
        echo "  '$imp' ya disponible."
        return 0
    fi
    if command -v apt-get >/dev/null 2>&1; then
        echo "  Instalando $apt_pkg via apt..."
        apt-get install -y "$apt_pkg" || true
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y "$apt_pkg" || true
    elif command -v yum >/dev/null 2>&1; then
        yum install -y "$apt_pkg" || true
    elif command -v pacman >/dev/null 2>&1; then
        pacman -Sy --noconfirm "python-${pip_name}" || true
    fi
    if ! python3 -c "import $imp" 2>/dev/null; then
        python3 -m pip install --break-system-packages "$pip_name" 2>/dev/null \
            || pip3 install --break-system-packages "$pip_name" 2>/dev/null \
            || python3 -m pip install "$pip_name" 2>/dev/null \
            || pip3 install "$pip_name" 2>/dev/null || true
    fi
    if ! python3 -c "import $imp" 2>/dev/null; then
        echo "ERROR: No se pudo instalar el módulo Python '$imp' ($apt_pkg / pip $pip_name)."
        exit 1
    fi
    echo "  '$imp' instalado."
}
_install_py_mod requests python3-requests requests
_install_py_mod cryptography python3-cryptography cryptography
echo "  Dependencias verificadas."

# [3/7] Copiar archivos
echo
echo "[3/7] Copiando archivos a $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"

cp "$SCRIPT_DIR/client.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/client_base.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/client_linux.py" "$INSTALL_DIR/"
# Allowlist / corte de internet (nft/iptables) — obligatorio para el timer
for f in network_policy.py domain_match.py dns_learner.py allowlist_discover.py hostname_proxy.py mitm_tls.py client_log.py; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" "$INSTALL_DIR/"
    else
        echo "  ERROR: falta $f (corte de internet / DNS learning / MITM / logs no funcionará)."
        exit 1
    fi
done
# config_gui / updater opcionales en modo servicio
[ -f "$SCRIPT_DIR/config_gui.py" ] && cp "$SCRIPT_DIR/config_gui.py" "$INSTALL_DIR/"
[ -f "$SCRIPT_DIR/client_updater.py" ] && cp "$SCRIPT_DIR/client_updater.py" "$INSTALL_DIR/"
[ -f "$SCRIPT_DIR/update_linux.sh" ] && cp "$SCRIPT_DIR/update_linux.sh" "$INSTALL_DIR/" && chmod 755 "$INSTALL_DIR/update_linux.sh"

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

DEFAULT_TARGET="$(_default_target_user)"
if [[ -n "$TARGET_USER_ARG" ]]; then
    TARGET_USER="$TARGET_USER_ARG"
    echo "  Usuario objetivo (CLI): $TARGET_USER"
else
    if [[ -n "$DEFAULT_TARGET" ]]; then
        read -p "  Usuario a controlar (perfil/bloqueo/notifs) [$DEFAULT_TARGET]: " TARGET_USER
        TARGET_USER=${TARGET_USER:-$DEFAULT_TARGET}
    else
        read -p "  Usuario a controlar (perfil/bloqueo/notifs): " TARGET_USER
    fi
fi

if [[ -z "$TARGET_USER" ]]; then
    echo "ERROR: tenés que indicar un usuario objetivo."
    exit 1
fi
if ! id "$TARGET_USER" &>/dev/null; then
    echo "ERROR: el usuario '$TARGET_USER' no existe en este sistema."
    exit 1
fi
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
if [[ -z "$TARGET_HOME" || ! -d "$TARGET_HOME" ]]; then
    echo "ERROR: no se encontró el home de '$TARGET_USER'."
    exit 1
fi
echo "  → target_user=$TARGET_USER  home=$TARGET_HOME"

DEFAULT_NAME="${TARGET_USER}"
read -p "  Nombre personalizado en el panel [$DEFAULT_NAME]: " CUSTOM_NAME
CUSTOM_NAME=${CUSTOM_NAME:-$DEFAULT_NAME}

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
  "max_server_timeouts": 10,
  "target_user": "$TARGET_USER",
  "custom_name": "$CUSTOM_NAME"
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

# CA MITM en el NSS de Firefox del usuario objetivo (si hay certutil + perfil)
echo
echo "  Instalando CA MITM en el perfil de '$TARGET_USER' (si aplica)..."
CA_DIR="$CONFIG_DIR/mitm_ca"
mkdir -p "$CA_DIR"
CA_CERT=""
if CA_CERT="$(
    cd "$INSTALL_DIR" && python3 -c "
import mitm_tls
mitm_tls.set_ca_dir('$CA_DIR')
print(mitm_tls.ensure_ca()[0])
" 2>/dev/null
)"; then
    if command -v certutil >/dev/null 2>&1; then
        shopt -s nullglob
        _nss_ok=0
        for db in "$TARGET_HOME"/.mozilla/firefox/*.default \
                  "$TARGET_HOME"/.mozilla/firefox/*.default-release \
                  "$TARGET_HOME"/.mozilla/firefox/*.default-*; do
            [[ -d "$db" ]] || continue
            if sudo -u "$TARGET_USER" certutil -d "sql:$db" -A -t "C,," \
                -n "CiberMonday Local MITM CA" -i "$CA_CERT" 2>/dev/null; then
                echo "    CA agregada a Firefox: $db"
                _nss_ok=1
            fi
        done
        shopt -u nullglob
        if [[ "$_nss_ok" -eq 0 ]]; then
            echo "    (sin perfil Firefox NSS o certutil falló — OK si usan Chromium/sistema)"
        fi
    else
        echo "    certutil no instalado (apt install libnss3-tools) — CA solo en sistema"
    fi
    # Trust de sistema (Chromium / curl)
    if [[ -f "$INSTALL_DIR/mitm_tls.py" ]]; then
        (cd "$INSTALL_DIR" && python3 -c "
import mitm_tls
mitm_tls.set_ca_dir('$CA_DIR')
mitm_tls.ensure_ca()
mitm_tls.install_ca_trust()
" 2>/dev/null) && echo "    CA en trust store del sistema" || true
    fi
else
    echo "    No se pudo generar CA aún (se creará al iniciar el servicio)."
fi

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
echo "Usuario objetivo: $TARGET_USER"
echo "Nombre en panel:  $CUSTOM_NAME"
echo
echo "Protecciones activas:"
echo "  - Inicio automático con el sistema"
echo "  - Reinicio automático si falla (cada 5 segundos)"
echo "  - Máximo 10 reinicios en 60 segundos"
echo "  - Bloqueo/notificaciones orientados a $TARGET_USER"
echo
echo "Comandos de administración:"
echo "  sudo systemctl start cibermonday-client    - Iniciar"
echo "  sudo systemctl stop cibermonday-client     - Detener"
echo "  sudo systemctl restart cibermonday-client  - Reiniciar"
echo "  sudo systemctl status cibermonday-client   - Estado"
echo "  journalctl -u cibermonday-client -f        - Ver logs (journal)"
echo "  tail -f /etc/cibermonday/CiberMondayClient.log - Log archivo"
echo "  curl -s localhost:5002/api/logs | jq       - Últimas líneas vía diagnostic"
echo
