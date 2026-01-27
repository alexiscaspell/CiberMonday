#!/usr/bin/env python3
"""
Script para escuchar y mostrar los broadcasts UDP del servidor CiberMonday.
Simula lo que hace el cliente cuando escucha broadcasts en el puerto 5001.
"""

import socket
import json
from datetime import datetime

DISCOVERY_PORT = 5001

def listen_for_broadcasts():
    """Escucha broadcasts UDP del servidor"""
    broadcast_count = 0
    sock = None
    
    try:
        # Crear socket UDP para escuchar broadcasts
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('', DISCOVERY_PORT))
        
        print("=" * 60)
        print(f"Escuchando broadcasts UDP en puerto {DISCOVERY_PORT}...")
        print("Presiona Ctrl+C para salir")
        print("=" * 60)
        print()
        
        while True:
            try:
                # Recibir datos (hasta 1024 bytes)
                data, addr = sock.recvfrom(1024)
                
                # Decodificar JSON
                try:
                    server_info = json.loads(data.decode('utf-8'))
                    broadcast_count += 1
                    
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{timestamp}] Broadcast #{broadcast_count} recibido desde {addr[0]}:{addr[1]}")
                    print(f"  URL: {server_info.get('url', 'N/A')}")
                    print(f"  IP: {server_info.get('ip', 'N/A')}")
                    print(f"  Puerto: {server_info.get('port', 'N/A')}")
                    print(f"  Datos completos: {json.dumps(server_info, indent=2)}")
                    print("-" * 60)
                    
                except json.JSONDecodeError as e:
                    print(f"[ERROR] No se pudo decodificar JSON: {e}")
                    print(f"  Datos recibidos: {data}")
                    print("-" * 60)
                    
            except KeyboardInterrupt:
                print("\n\nDeteniendo listener...")
                break
            except Exception as e:
                print(f"[ERROR] Error al recibir datos: {e}")
                import traceback
                traceback.print_exc()
                
    except PermissionError:
        print(f"[ERROR] No se pudo abrir el puerto {DISCOVERY_PORT}.")
        print("         Puede que necesites permisos de administrador o que el puerto esté en uso.")
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(f"[ERROR] El puerto {DISCOVERY_PORT} ya está en uso.")
            print("         Ejecuta: lsof -ti:5001 | xargs kill -9")
        else:
            print(f"[ERROR] Error al crear socket: {e}")
            import traceback
            traceback.print_exc()
    except Exception as e:
        print(f"[ERROR] Error al crear socket: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass
        print(f"\nTotal de broadcasts recibidos: {broadcast_count}")

if __name__ == '__main__':
    listen_for_broadcasts()
