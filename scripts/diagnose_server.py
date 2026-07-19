#!/usr/bin/env python3
"""
Script de diagnóstico para verificar la conectividad del servidor
"""

import socket
import json
import time
import sys
import requests

def get_local_ip():
    """Obtiene la IP local del servidor"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        print(f"Error al obtener IP local: {e}")
        return None

def get_broadcast_address(ip_address):
    """Calcula la dirección de broadcast"""
    try:
        parts = ip_address.split('.')
        if len(parts) == 4:
            # Asumir máscara /24 (255.255.255.0)
            return f"{parts[0]}.{parts[1]}.{parts[2]}.255"
    except:
        pass
    return "255.255.255.255"

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
        print(f"   Posibles causas:")
        print(f"     - El servidor no está ejecutándose")
        print(f"     - Firewall bloqueando el puerto {port}")
        print(f"     - IP incorrecta")
        return False
    except requests.exceptions.Timeout:
        print(f"   ❌ Timeout al conectar")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_broadcast_listening(duration=10):
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
        print(f"   Escuchando broadcasts...")
        
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
            return True
        else:
            print(f"\n   ❌ No se recibió ningún broadcast")
            print(f"   Posibles causas:")
            print(f"     - El servidor no está enviando broadcasts")
            print(f"     - El servidor tiene clientes conectados (broadcasts pausados)")
            print(f"     - Firewall bloqueando UDP")
            print(f"     - Servidor en otra red/subred")
            return False
            
    except Exception as e:
        print(f"   ❌ Error al escuchar broadcasts: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_server_info(server_ip, port=5000):
    """Obtiene información del servidor"""
    print(f"\n{'='*60}")
    print(f"3. Obteniendo información del servidor")
    print(f"{'='*60}")
    
    try:
        url = f"http://{server_ip}:{port}/api/server-info"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"   ✅ Información del servidor:")
                print(f"      IP reportada: {data.get('ip')}")
                print(f"      Puerto: {data.get('port')}")
                print(f"      URL: {data.get('url')}")
                print(f"      Intervalo de broadcast: {data.get('broadcast_interval', 'N/A')} segundo(s)")
                
                # Verificar si la IP reportada coincide
                if data.get('ip') != server_ip:
                    print(f"   ⚠️  ADVERTENCIA: La IP reportada ({data.get('ip')}) no coincide con la IP probada ({server_ip})")
                
                return data
        else:
            print(f"   ⚠️  Error al obtener información: código {response.status_code}")
            return None
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None

def main():
    print("="*60)
    print("DIAGNÓSTICO DE SERVIDOR CiberMonday")
    print("="*60)
    
    # Obtener IP local
    local_ip = get_local_ip()
    if local_ip:
        print(f"\nIP local detectada: {local_ip}")
        broadcast_addr = get_broadcast_address(local_ip)
        print(f"Dirección de broadcast calculada: {broadcast_addr}")
    else:
        print("\n⚠️  No se pudo detectar la IP local")
    
    # IP del servidor a probar
    server_ip = "192.168.0.3"
    if len(sys.argv) > 1:
        server_ip = sys.argv[1]
    
    print(f"\nServidor a diagnosticar: {server_ip}:5000")
    
    # 1. Probar conectividad HTTP
    http_ok = test_server_connectivity(server_ip)
    
    # 2. Obtener información del servidor
    server_info = None
    if http_ok:
        server_info = check_server_info(server_ip)
    
    # 3. Escuchar broadcasts
    broadcast_ok = test_broadcast_listening(duration=15)
    
    # Resumen final
    print(f"\n{'='*60}")
    print("RESUMEN DEL DIAGNÓSTICO")
    print(f"{'='*60}")
    print(f"Conectividad HTTP: {'✅ OK' if http_ok else '❌ FALLO'}")
    print(f"Broadcasts UDP: {'✅ OK' if broadcast_ok else '❌ FALLO'}")
    
    if http_ok and not broadcast_ok:
        print(f"\n💡 RECOMENDACIONES:")
        print(f"   - El servidor está funcionando pero no envía broadcasts")
        print(f"   - Verifica si el servidor tiene clientes conectados (los broadcasts se pausan)")
        print(f"   - Verifica los logs del servidor para ver si hay errores de broadcast")
        print(f"   - Verifica la configuración del intervalo de broadcast")
    elif not http_ok:
        print(f"\n💡 RECOMENDACIONES:")
        print(f"   - Verifica que el servidor esté ejecutándose")
        print(f"   - Verifica que el puerto 5000 no esté bloqueado por firewall")
        print(f"   - Verifica que la IP {server_ip} sea correcta")
        print(f"   - Intenta hacer ping a {server_ip} para verificar conectividad de red")

if __name__ == "__main__":
    main()
