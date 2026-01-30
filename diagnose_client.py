#!/usr/bin/env python3
"""
Script de diagnóstico para verificar la conectividad del cliente con servidores
"""

import socket
import json
import time
import sys
import requests
import os

def get_local_ip():
    """Obtiene la IP local"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        print(f"Error al obtener IP local: {e}")
        return None

def test_server_connectivity(server_ip, port=5000):
    """Prueba la conectividad HTTP con el servidor"""
    print(f"\n{'='*60}")
    print(f"1. Probando conectividad HTTP con {server_ip}:{port}")
    print(f"{'='*60}")
    
    try:
        url = f"http://{server_ip}:{port}/api/health"
        print(f"   Intentando conectar a: {url}")
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Servidor responde correctamente")
            print(f"   Estado: {data.get('status')}")
            print(f"   Clientes activos: {data.get('active_clients', 0)}")
            print(f"   Total clientes: {data.get('total_clients', 0)}")
            return True
        else:
            print(f"   ⚠️  Servidor respondió con código: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"   ❌ No se pudo conectar al servidor")
        return False
    except requests.exceptions.Timeout:
        print(f"   ❌ Timeout al conectar")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_broadcast_listening(duration=15):
    """Escucha broadcasts UDP durante un tiempo determinado"""
    print(f"\n{'='*60}")
    print(f"2. Escuchando broadcasts UDP en puerto 5001 ({duration} segundos)")
    print(f"{'='*60}")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('', 5001))
        sock.settimeout(1.0)
        
        print(f"   ✅ Socket UDP creado y vinculado al puerto 5001")
        print(f"   Escuchando broadcasts desde la red local...")
        
        start_time = time.time()
        broadcasts_received = []
        
        while time.time() - start_time < duration:
            try:
                data, addr = sock.recvfrom(1024)
                try:
                    server_info = json.loads(data.decode('utf-8'))
                    server_url = server_info.get('url', '')
                    server_ip = server_info.get('ip', addr[0])
                    elapsed = int(time.time() - start_time)
                    broadcasts_received.append({
                        'url': server_url,
                        'ip': server_ip,
                        'from': addr[0],
                        'time': elapsed
                    })
                    print(f"   ✅ Broadcast recibido desde {addr[0]} (t={elapsed}s)")
                    print(f"      URL: {server_url}")
                    print(f"      IP: {server_ip}")
                except json.JSONDecodeError:
                    print(f"   ⚠️  Datos recibidos pero no es JSON válido desde {addr[0]}")
            except socket.timeout:
                continue
        
        sock.close()
        
        if broadcasts_received:
            print(f"\n   📊 Resumen: Se recibieron {len(broadcasts_received)} broadcast(s)")
            unique_servers = {}
            for b in broadcasts_received:
                if b['url'] not in unique_servers:
                    unique_servers[b['url']] = b
            print(f"   Servidores únicos detectados: {len(unique_servers)}")
            for url, info in unique_servers.items():
                print(f"     - {url} (desde {info['from']})")
            return True, unique_servers
        else:
            print(f"\n   ❌ No se recibió ningún broadcast")
            print(f"   Posibles causas:")
            print(f"     - El servidor no está enviando broadcasts")
            print(f"     - El servidor tiene clientes conectados (broadcasts pausados)")
            print(f"     - Firewall bloqueando UDP")
            print(f"     - Problemas de red")
            return False, {}
            
    except Exception as e:
        print(f"   ❌ Error al escuchar broadcasts: {e}")
        import traceback
        traceback.print_exc()
        return False, {}

def check_registry_servers():
    """Verifica los servidores guardados en el registro del cliente"""
    print(f"\n{'='*60}")
    print(f"3. Verificando servidores conocidos en el registro")
    print(f"{'='*60}")
    
    try:
        # Intentar importar el módulo de registro
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'client'))
        from registry_manager import get_servers_from_registry
        
        known_servers = get_servers_from_registry()
        
        if known_servers:
            print(f"   ✅ Se encontraron {len(known_servers)} servidor(es) conocido(s):")
            for server in known_servers:
                url = server.get('url', 'N/A')
                ip = server.get('ip', 'N/A')
                port = server.get('port', 'N/A')
                last_seen = server.get('last_seen', 'N/A')
                print(f"     - {url}")
                print(f"       IP: {ip}, Puerto: {port}")
                print(f"       Última vez visto: {last_seen}")
            return known_servers
        else:
            print(f"   ⚠️  No hay servidores conocidos en el registro")
            return []
    except ImportError:
        print(f"   ⚠️  No se pudo importar registry_manager (probablemente no es Windows)")
        return []
    except Exception as e:
        print(f"   ❌ Error al leer registro: {e}")
        import traceback
        traceback.print_exc()
        return []

def test_server_health(server_url):
    """Prueba el health check de un servidor"""
    try:
        response = requests.get(f"{server_url}/api/health", timeout=3)
        return response.status_code == 200
    except:
        return False

def main():
    print("="*60)
    print("DIAGNÓSTICO DE CLIENTE CiberMonday")
    print("="*60)
    
    # Obtener IP local
    local_ip = get_local_ip()
    if local_ip:
        print(f"\nIP local del cliente: {local_ip}")
    else:
        print("\n⚠️  No se pudo detectar la IP local")
    
    # IP del servidor a probar
    server_ip = "192.168.0.3"
    if len(sys.argv) > 1:
        server_ip = sys.argv[1]
    
    print(f"\nServidor a diagnosticar: {server_ip}:5000")
    
    # 1. Probar conectividad HTTP
    http_ok = test_server_connectivity(server_ip)
    
    # 2. Escuchar broadcasts
    broadcast_ok, discovered_servers = test_broadcast_listening(duration=15)
    
    # 3. Verificar registro
    registry_servers = check_registry_servers()
    
    # 4. Verificar si los servidores descubiertos están en el registro
    if discovered_servers and registry_servers:
        print(f"\n{'='*60}")
        print(f"4. Comparando servidores descubiertos vs registro")
        print(f"{'='*60}")
        
        registry_urls = {s.get('url') for s in registry_servers}
        discovered_urls = set(discovered_servers.keys())
        
        missing_in_registry = discovered_urls - registry_urls
        if missing_in_registry:
            print(f"   ⚠️  Servidores descubiertos pero NO en registro:")
            for url in missing_in_registry:
                print(f"     - {url}")
        else:
            print(f"   ✅ Todos los servidores descubiertos están en el registro")
    
    # 5. Probar health check de servidores conocidos
    if registry_servers:
        print(f"\n{'='*60}")
        print(f"5. Probando health check de servidores conocidos")
        print(f"{'='*60}")
        
        for server in registry_servers:
            url = server.get('url')
            if url:
                print(f"   Probando {url}...", end=" ")
                if test_server_health(url):
                    print("✅ Disponible")
                else:
                    print("❌ No disponible")
    
    # Resumen final
    print(f"\n{'='*60}")
    print("RESUMEN DEL DIAGNÓSTICO")
    print(f"{'='*60}")
    print(f"Conectividad HTTP con {server_ip}: {'✅ OK' if http_ok else '❌ FALLO'}")
    print(f"Broadcasts UDP recibidos: {'✅ OK' if broadcast_ok else '❌ FALLO'}")
    print(f"Servidores en registro: {len(registry_servers)}")
    
    if http_ok and broadcast_ok and len(registry_servers) > 0:
        print(f"\n✅ Todo parece estar funcionando correctamente")
        print(f"   El cliente debería poder sincronizarse con el servidor")
    elif http_ok and not broadcast_ok:
        print(f"\n💡 RECOMENDACIONES:")
        print(f"   - El servidor responde HTTP pero no se reciben broadcasts")
        print(f"   - Verifica si el servidor tiene clientes conectados (pausa broadcasts)")
        print(f"   - Verifica el firewall del cliente (puerto UDP 5001)")
    elif not http_ok:
        print(f"\n💡 RECOMENDACIONES:")
        print(f"   - Verifica que el servidor esté ejecutándose")
        print(f"   - Verifica conectividad de red (ping {server_ip})")
        print(f"   - Verifica firewall del servidor (puerto TCP 5000)")

if __name__ == "__main__":
    main()
