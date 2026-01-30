"""
Módulo para gestionar el tiempo de sesión en el registro de Windows
Almacena la información de tiempo localmente para que el cliente funcione
sin depender de la conexión continua al servidor.
"""

import winreg
import json
from datetime import datetime, timedelta
import os

# Clave del registro donde se almacena la información
REGISTRY_KEY_PATH = r"SOFTWARE\CiberMonday"
REGISTRY_VALUE_SESSION = "SessionData"
REGISTRY_VALUE_CLIENT_ID = "ClientID"
REGISTRY_VALUE_CONFIG = "Config"
REGISTRY_VALUE_SERVERS = "KnownServers"

def get_registry_key(create=False):
    """Obtiene o crea la clave del registro"""
    try:
        if create:
            return winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY_PATH)
        else:
            return winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY_PATH, 0, winreg.KEY_READ | winreg.KEY_WRITE)
    except FileNotFoundError:
        if create:
            return winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY_PATH)
        return None
    except PermissionError:
        # Intentar con HKEY_CURRENT_USER si no hay permisos de administrador
        try:
            if create:
                return winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH)
            else:
                return winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH, 0, winreg.KEY_READ | winreg.KEY_WRITE)
        except:
            return None

def save_session_to_registry(time_limit_seconds, start_time_iso, end_time_iso):
    """
    Guarda la información de sesión en el registro de Windows
    
    Args:
        time_limit_seconds: Tiempo total en segundos
        start_time_iso: Hora de inicio en formato ISO
        end_time_iso: Hora de fin en formato ISO
    """
    try:
        key = get_registry_key(create=True)
        if key is None:
            return False
        
        session_data = {
            'time_limit_seconds': time_limit_seconds,
            'start_time': start_time_iso,
            'end_time': end_time_iso
        }
        
        # Guardar como JSON en el registro
        json_data = json.dumps(session_data)
        winreg.SetValueEx(key, REGISTRY_VALUE_SESSION, 0, winreg.REG_SZ, json_data)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Error al guardar en registro: {e}")
        return False

def get_session_from_registry():
    """
    Obtiene la información de sesión del registro de Windows
    
    Returns:
        dict con la información de sesión o None si no existe
    """
    try:
        key = get_registry_key(create=False)
        if key is None:
            return None
        
        try:
            json_data, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_SESSION)
            winreg.CloseKey(key)
            
            session_data = json.loads(json_data)
            return session_data
        except FileNotFoundError:
            winreg.CloseKey(key)
            return None
    except Exception as e:
        print(f"Error al leer del registro: {e}")
        return None

def clear_session_from_registry():
    """Elimina la información de sesión del registro"""
    try:
        key = get_registry_key(create=False)
        if key is None:
            return False
        
        try:
            winreg.DeleteValue(key, REGISTRY_VALUE_SESSION)
        except FileNotFoundError:
            pass  # Ya no existe
        
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Error al limpiar registro: {e}")
        return False

def save_client_id_to_registry(client_id):
    """Guarda el ID del cliente en el registro"""
    try:
        key = get_registry_key(create=True)
        if key is None:
            return False
        
        winreg.SetValueEx(key, REGISTRY_VALUE_CLIENT_ID, 0, winreg.REG_SZ, client_id)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Error al guardar Client ID: {e}")
        return False

def get_client_id_from_registry():
    """Obtiene el ID del cliente del registro"""
    try:
        key = get_registry_key(create=False)
        if key is None:
            return None
        
        try:
            client_id, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_CLIENT_ID)
            winreg.CloseKey(key)
            return client_id
        except FileNotFoundError:
            winreg.CloseKey(key)
            return None
    except Exception as e:
        print(f"Error al leer Client ID: {e}")
        return None

def get_remaining_seconds():
    """
    Calcula los segundos restantes basándose en el registro local.
    El end_time en el registro siempre está en hora local del cliente,
    por lo que el cálculo es simple y directo: end_time - ahora.
    
    Returns:
        int: Segundos restantes, o None si no hay sesión activa
    """
    session_data = get_session_from_registry()
    if session_data is None:
        return None
    
    try:
        end_time_str = session_data.get('end_time')
        if not end_time_str:
            return None
        
        # Parsear end_time (siempre está en hora local del cliente)
        end_time = datetime.fromisoformat(end_time_str)
        now = datetime.now()
        
        # Calcular tiempo restante: end_time_local - ahora_local
        # Esto siempre será correcto porque ambos están en la misma zona horaria
        remaining = int((end_time - now).total_seconds())
        
        # Validación básica: el tiempo restante no debería ser negativo (pero lo limitamos a 0)
        # ni debería ser mucho mayor que el time_limit (lo cual indicaría un error)
        time_limit_seconds = session_data.get('time_limit_seconds', 0)
        if time_limit_seconds > 0 and remaining > time_limit_seconds * 2:
            # Si el tiempo restante es más del doble del límite, hay un problema
            print(f"[Advertencia] Tiempo restante ({remaining}s) es mucho mayor que el límite ({time_limit_seconds}s)")
            print(f"  - End time en registro: {end_time_str}")
            print(f"  - Hora actual: {now.isoformat()}")
            # Recalcular basándose en start_time si está disponible
            start_time_str = session_data.get('start_time')
            if start_time_str:
                try:
                    start_time = datetime.fromisoformat(start_time_str)
                    correct_end_time = start_time + timedelta(seconds=time_limit_seconds)
                    remaining_corrected = int((correct_end_time - now).total_seconds())
                    print(f"  - Recalculando: {remaining_corrected}s basado en start_time + time_limit")
                    return max(0, remaining_corrected)
                except:
                    pass
        
        return max(0, remaining)
    except Exception as e:
        print(f"Error al calcular tiempo restante: {e}")
        import traceback
        traceback.print_exc()
        return None

def is_session_expired():
    """Verifica si la sesión ha expirado según el registro local"""
    remaining = get_remaining_seconds()
    if remaining is None:
        return None  # No hay sesión
    return remaining <= 0

def get_session_info():
    """
    Obtiene información completa de la sesión desde el registro
    
    Returns:
        dict con información de sesión o None
    """
    session_data = get_session_from_registry()
    if session_data is None:
        return None
    
    remaining = get_remaining_seconds()
    if remaining is None:
        return None
    
    return {
        'time_limit_seconds': session_data.get('time_limit_seconds', 0),
        'start_time': session_data.get('start_time'),
        'end_time': session_data.get('end_time'),
        'remaining_seconds': remaining,
        'is_expired': remaining <= 0
    }

def save_config_to_registry(config):
    """
    Guarda la configuración del cliente en el registro
    
    Args:
        config: dict con configuración del cliente
            - server_url: URL del servidor
            - check_interval: Intervalo de verificación local
            - sync_interval: Intervalo de sincronización con el servidor
            - alert_thresholds: Lista de segundos para alertas [600, 300, 120, 60]
            - custom_name: Nombre personalizado del cliente (None = usar nombre del equipo)
    
    Returns:
        bool: True si se guardó correctamente
    """
    try:
        key = get_registry_key(create=True)
        if key is None:
            return False
        
        import json
        config_data = {
            'server_url': config.get('server_url', 'http://localhost:5000'),
            'check_interval': config.get('check_interval', 5),
            'sync_interval': config.get('sync_interval', 30),
            'alert_thresholds': config.get('alert_thresholds', [600, 300, 120, 60]),
            'custom_name': config.get('custom_name', None)
        }
        
        json_data = json.dumps(config_data)
        winreg.SetValueEx(key, "Config", 0, winreg.REG_SZ, json_data)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Error al guardar configuración en registro: {e}")
        return False

def get_config_from_registry():
    """
    Obtiene la configuración del cliente desde el registro
    
    Returns:
        dict con configuración o None si no existe
    """
    try:
        key = get_registry_key(create=False)
        if key is None:
            return None
        
        try:
            json_data, _ = winreg.QueryValueEx(key, "Config")
            winreg.CloseKey(key)
            
            import json
            config_data = json.loads(json_data)
            
            # Asegurar que todos los campos existen con valores por defecto
            config_data.setdefault('server_url', 'http://localhost:5000')
            config_data.setdefault('check_interval', 5)
            config_data.setdefault('sync_interval', 30)
            config_data.setdefault('alert_thresholds', [600, 300, 120, 60])
            config_data.setdefault('custom_name', None)
            
            return config_data
        except FileNotFoundError:
            winreg.CloseKey(key)
            return None
    except Exception as e:
        print(f"Error al leer configuración del registro: {e}")
        return None

def save_servers_to_registry(servers_list):
    """Guarda la lista de servidores conocidos en el registro."""
    try:
        key = get_registry_key(create=True)
        if key is None:
            return False
        
        # Asegurar que cada servidor tenga timeout_count (compatibilidad con versiones anteriores)
        for server in servers_list:
            if 'timeout_count' not in server:
                server['timeout_count'] = 0
        
        servers_json = json.dumps(servers_list)
        winreg.SetValueEx(key, REGISTRY_VALUE_SERVERS, 0, winreg.REG_SZ, servers_json)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Error al guardar servidores en registro: {e}")
        return False

def get_servers_from_registry():
    """Obtiene la lista de servidores conocidos del registro y elimina los que tienen 10+ timeouts."""
    try:
        key = get_registry_key(create=False)
        if key is None:
            # Si no hay clave pero el registro está disponible, retornar lista vacía
            # Esto es normal en la primera ejecución
            return []
        
        servers_json, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_SERVERS)
        winreg.CloseKey(key)
        servers_list = json.loads(servers_json)
        
        if not isinstance(servers_list, list):
            return []
        
        # Filtrar servidores con 10+ timeouts y asegurar que todos tengan timeout_count
        MAX_TIMEOUTS = 10
        filtered_servers = []
        removed_servers = []
        
        for server in servers_list:
            # Asegurar compatibilidad con versiones anteriores
            if 'timeout_count' not in server:
                server['timeout_count'] = 0
            
            timeout_count = server.get('timeout_count', 0)
            if timeout_count >= MAX_TIMEOUTS:
                removed_servers.append(server.get('url', 'Unknown'))
            else:
                filtered_servers.append(server)
        
        # Si se eliminaron servidores, guardar la lista filtrada
        if removed_servers:
            print(f"[Servidores] 🗑️  Eliminando {len(removed_servers)} servidor(es) con {MAX_TIMEOUTS}+ timeouts: {', '.join(removed_servers)}")
            save_servers_to_registry(filtered_servers)
        
        return filtered_servers
    except FileNotFoundError:
        # Primera vez que se ejecuta - no hay servidores guardados aún
        # Esto es normal y esperado
        return []
    except json.JSONDecodeError as e:
        # Error al parsear JSON - el valor existe pero está corrupto
        print(f"[Advertencia] Error al parsear servidores del registro (JSON corrupto): {e}")
        print(f"[Advertencia] Se retornará lista vacía. Los servidores conocidos se recuperarán en la próxima sincronización.")
        return []
    except Exception as e:
        # Otros errores - loguear pero retornar lista vacía
        print(f"[Error] Error al leer servidores del registro: {e}")
        print(f"[Error] Se retornará lista vacía. Los servidores conocidos se recuperarán en la próxima sincronización.")
        return []

def increment_server_timeouts(server_urls):
    """
    Incrementa el contador de timeouts para los servidores especificados.
    Si un servidor alcanza 10 timeouts, se elimina de la lista.
    
    Args:
        server_urls: Lista de URLs de servidores que fallaron
    """
    if not server_urls:
        return
    
    try:
        servers_list = get_servers_from_registry()
        updated = False
        
        for server in servers_list:
            server_url = server.get('url')
            if server_url in server_urls:
                timeout_count = server.get('timeout_count', 0)
                server['timeout_count'] = timeout_count + 1
                updated = True
                print(f"[Servidores] ⚠️  Servidor {server_url} - Timeouts: {server['timeout_count']}/10")
        
        if updated:
            save_servers_to_registry(servers_list)
    except Exception as e:
        print(f"[Error] Error al incrementar contadores de timeout: {e}")

def reset_server_timeout_count(server_url):
    """
    Resetea el contador de timeouts para un servidor específico.
    
    Args:
        server_url: URL del servidor que respondió exitosamente
    """
    if not server_url:
        return
    
    try:
        servers_list = get_servers_from_registry()
        updated = False
        
        for server in servers_list:
            if server.get('url') == server_url:
                old_count = server.get('timeout_count', 0)
                if old_count > 0:
                    server['timeout_count'] = 0
                    updated = True
                    print(f"[Servidores] ✅ Servidor {server_url} - Timeouts reseteados (era {old_count})")
                break
        
        if updated:
            save_servers_to_registry(servers_list)
    except Exception as e:
        print(f"[Error] Error al resetear contador de timeout: {e}")
