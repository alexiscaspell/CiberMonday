#!/bin/bash
# Muestra el log del cliente en vivo (archivo + hint journal).
set -e
LOG=""
for cand in /etc/cibermonday/CiberMondayClient.log \
            "$HOME/.config/cibermonday/CiberMondayClient.log" \
            /opt/cibermonday/CiberMondayClient.log; do
  if [ -f "$cand" ]; then
    LOG="$cand"
    break
  fi
done

echo "========================================"
echo " CiberMonday - Logs del cliente (Linux)"
echo "========================================"
echo
if [ -z "$LOG" ]; then
  echo "No se encontró CiberMondayClient.log"
  echo "También podés ver journal: journalctl -u cibermonday-client -f"
  echo "O diagnostic: curl -sS http://127.0.0.1:5002/api/logs"
  exit 1
fi
echo "Archivo: $LOG"
echo "Ctrl+C para salir."
echo "----------------------------------------"
tail -n 50 -f "$LOG"
