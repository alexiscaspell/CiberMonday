#!/bin/bash
# Actualiza el cliente Linux desde GitHub Releases (alexiscaspell/CiberMonday).
#
# Uso:
#   sudo bash update_linux.sh              # última (incl. prerelease)
#   sudo bash update_linux.sh --stable     # solo release stable
#   sudo bash update_linux.sh --version 0.7.24
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/alexiscaspell/CiberMonday/main/client/linux/update_linux.sh | sudo bash

set -euo pipefail

REPO="alexiscaspell/CiberMonday"
INSTALL_DIR="/opt/cibermonday"
CONFIG_DIR="/etc/cibermonday"
SERVICE_NAME="cibermonday-client.service"
UA="CiberMondayClient-Updater/1.0"

ALLOW_PRERELEASE=1
PIN_VERSION=""

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stable) ALLOW_PRERELEASE=0; shift ;;
        --prerelease|--pre) ALLOW_PRERELEASE=1; shift ;;
        --version|-v)
            PIN_VERSION="${2:-}"
            if [[ -z "$PIN_VERSION" ]]; then
                echo "ERROR: --version requiere un valor (ej: 0.7.24)"
                exit 1
            fi
            PIN_VERSION="${PIN_VERSION#v}"
            shift 2
            ;;
        -h|--help) usage ;;
        *)
            echo "Opción desconocida: $1 (usa --help)"
            exit 1
            ;;
    esac
done

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: ejecutá como root."
    echo "  sudo bash update_linux.sh"
    exit 1
fi

for bin in python3 curl; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "ERROR: hace falta $bin."
        exit 1
    fi
done

echo "========================================"
echo "Actualizar CiberMonday Client (Linux)"
echo "========================================"
echo

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

UPDATER=""
for cand in "$INSTALL_DIR/client_updater.py" "$SCRIPT_DIR/client_updater.py"; do
    if [[ -f "$cand" ]]; then
        UPDATER="$cand"
        break
    fi
done

# Con client_updater y sin pin de versión: camino preferido
if [[ -n "$UPDATER" && -z "$PIN_VERSION" ]]; then
    echo "[*] client_updater: $UPDATER"
    echo "    canal: $([ "$ALLOW_PRERELEASE" = 1 ] && echo prerelease+stable || echo solo stable)"
    export CM_UPDATER_DIR
    CM_UPDATER_DIR="$(dirname "$UPDATER")"
    python3 - "$ALLOW_PRERELEASE" <<'PY'
import os, sys
sys.path.insert(0, os.environ["CM_UPDATER_DIR"])
import client_updater

allow = sys.argv[1] == "1"

def progress(msg: str) -> None:
    print(f"  {msg}", flush=True)

try:
    info = client_updater.run_update(
        allow_prerelease=allow,
        progress_cb=progress,
        install_dir="/opt/cibermonday",
    )
    print(f"\n[OK] Actualizado a {info.get('tag')} (v{info.get('version')})")
except Exception as e:
    print(f"\nERROR: {e}", file=sys.stderr)
    sys.exit(1)
PY
    echo
    echo "Verificá: curl -sS http://127.0.0.1:5002/api/diagnostic | grep client_version"
    exit 0
fi

# Fallback / --version: descargar tarball a mano
echo "[1/3] Buscando release…"
TMP="$(mktemp -d /tmp/cm-update.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

RESOLVED="$(PIN_VERSION="$PIN_VERSION" ALLOW_PRERELEASE="$ALLOW_PRERELEASE" REPO="$REPO" UA="$UA" python3 <<'PY'
import json, os, sys, urllib.request

repo = os.environ["REPO"]
ua = os.environ["UA"]
pin = (os.environ.get("PIN_VERSION") or "").strip()
allow = os.environ.get("ALLOW_PRERELEASE", "1") == "1"

def get(url: str):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": ua, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

if pin:
    tag = pin if pin.startswith("v") else f"v{pin}"
    rel = get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
else:
    rel = None
    for item in get(f"https://api.github.com/repos/{repo}/releases?per_page=30"):
        if item.get("draft"):
            continue
        if not allow and item.get("prerelease"):
            continue
        rel = item
        break
    if rel is None:
        kind = "prerelease o stable" if allow else "stable"
        print(f"No hay release {kind}", file=sys.stderr)
        sys.exit(1)

url = name = None
for a in rel.get("assets") or []:
    n = a.get("name") or ""
    if n.startswith("CiberMondayClient-Linux-") and n.endswith(".tar.gz"):
        url, name = a.get("browser_download_url"), n
        break
if not url:
    print("Release sin tarball Linux", file=sys.stderr)
    sys.exit(1)

print(rel.get("tag_name") or "")
print(name)
print(url)
PY
)"

TAG="$(printf '%s\n' "$RESOLVED" | sed -n '1p')"
ASSET_NAME="$(printf '%s\n' "$RESOLVED" | sed -n '2p')"
ASSET_URL="$(printf '%s\n' "$RESOLVED" | sed -n '3p')"

echo "  Release: $TAG"
echo "  Asset:   $ASSET_NAME"

echo
echo "[2/3] Descargando…"
TARBALL="$TMP/client.tar.gz"
curl -fL -A "$UA" --progress-bar -o "$TARBALL" "$ASSET_URL"

echo
echo "[3/3] Instalando en $INSTALL_DIR (se conserva $CONFIG_DIR)…"
systemctl stop "$SERVICE_NAME" 2>/dev/null || true

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
tar xzf "$TARBALL" -C "$TMP"
SRC="$TMP/cibermonday-linux"
if [[ ! -d "$SRC" ]]; then
    SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | head -1)"
fi
if [[ ! -d "$SRC" ]]; then
    echo "ERROR: contenido del tarball inesperado"
    exit 1
fi

cp -a "$SRC"/. "$INSTALL_DIR"/
chmod 755 "$INSTALL_DIR"/*.py 2>/dev/null || true
chmod 755 "$INSTALL_DIR"/*.sh 2>/dev/null || true

if [[ -f "$INSTALL_DIR/cibermonday-client.service" ]]; then
    cp "$INSTALL_DIR/cibermonday-client.service" "/etc/systemd/system/$SERVICE_NAME"
    systemctl daemon-reload
fi

systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
systemctl start "$SERVICE_NAME"

sleep 1
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo
    echo "[OK] Servicio activo — $TAG"
else
    echo
    echo "WARN: el servicio no arrancó. Revisá: journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi

echo "Diagnóstico: curl -sS http://127.0.0.1:5002/api/diagnostic | grep client_version"
