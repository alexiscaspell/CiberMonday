#!/usr/bin/env bash
# Build Expo admin SPA → server/web/static (+ copia para Android host)
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ADMIN_DIR="$ROOT_DIR/server/admin"
WEB_STATIC="$ROOT_DIR/server/web/static"
ANDROID_STATIC="$ROOT_DIR/server/android/app/src/main/python/admin_static"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  CiberMonday — Build Admin (Expo Web)${NC}"
echo -e "${BLUE}================================================${NC}"

if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  echo -e "${RED}Se necesita Node.js / npm.${NC}"
  exit 1
fi

if [ ! -d "$ADMIN_DIR" ]; then
  echo -e "${RED}No existe $ADMIN_DIR${NC}"
  exit 1
fi

cd "$ADMIN_DIR"

if [ ! -d node_modules ]; then
  echo -e "${YELLOW}npm install...${NC}"
  npm ci --prefer-offline || npm install
fi

echo -e "${YELLOW}expo export -p web...${NC}"
npx expo export -p web

if [ ! -f dist/index.html ]; then
  echo -e "${RED}Export falló: falta dist/index.html${NC}"
  exit 1
fi

echo -e "${YELLOW}Copiando a server/web/static...${NC}"
rm -rf "$WEB_STATIC"
mkdir -p "$WEB_STATIC"
cp -a dist/. "$WEB_STATIC/"

echo -e "${YELLOW}Copiando a Android admin_static...${NC}"
rm -rf "$ANDROID_STATIC"
mkdir -p "$ANDROID_STATIC"
cp -a dist/. "$ANDROID_STATIC/"

# No versionar el bundle en git por defecto no aplica; CI lo genera.
# Asegurar que .gitkeep no haga falta: static debe existir post-build.

echo -e "${GREEN}OK: panel en $WEB_STATIC${NC}"
echo -e "${GREEN}OK: Android en $ANDROID_STATIC${NC}"
