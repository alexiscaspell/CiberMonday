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

def save_session_to_registry(time_limit_seconds, start_time_iso, end_time_iso, time_disabled=False):
    """
    Guarda la información de sesión en el registro de Windows
    
    Args:
        time_limit_seconds: Tiempo total en segundos
        start_time_iso: Hora de inicio en formato ISO
        end_time_iso: Hora de fin en formato ISO
        time_disabled: Flag que indica si el bloqueo de tiempo está deshabilitado
    """
    try:
        key = get_registry_key(create=True)
        if key is None:
            return False
        
        session_data = {
            'time_limit_seconds': time_limit_seconds,
            'start_time': start_time_iso,
            'end_time': end_time_iso,
            'time_disabled': time_disabled
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
    
    # Verificar si el tiempo está deshabilitado
    # Si el time_limit es muy grande (>= 999999999), asumimos que el tiempo está deshabilitado
    time_limit = session_data.get('time_limit_seconds', 0)
    time_disabled = time_limit >= 999999999 or session_data.get('time_disabled', False)
    
    # Si el tiempo está deshabilitado, nunca considerar expirado
    is_expired = False if time_disabled else (remaining <= 0)
    
    return {
        'time_limit_seconds': time_limit,
        'start_time': session_data.get('start_time'),
        'end_time': session_data.get('end_time'),
        'remaining_seconds': remaining,
        'is_expired': is_expired,
        'time_disabled': time_disabled
    }

def save_config_to_registry(config):
    """
    Guarda la configuración del cliente en el registro
    
    Args:
        config: dict con configuración completa del cliente
    
    Returns:
        bool: True si se guardó correctamente
    """
    try:
        key = get_registry_key(create=True)
        if key is None:
            return False
        
        import json
        # Guardar todos los campos de configuración con valores por defecto
        config_data = {
            'server_url': config.get('server_url', 'http://localhost:5000'),
            'check_interval': config.get('check_interval', 5),
            'sync_interval': config.get('sync_interval', 30),
            'local_check_interval': config.get('local_check_interval', 1),
            'expired_sync_interval': config.get('expired_sync_interval', 2),
            'lock_delay': config.get('lock_delay', 2),
            'warning_thresholds': config.get('warning_thresholds', [10, 5, 2, 1])
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
            return config_data
        except FileNotFoundError:
            winreg.CloseKey(key)
            return None
    except Exception as e:
        print(f"Error al leer configuración del registro: {e}")
        return None
