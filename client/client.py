"""
Cliente CiberMonday - Control de tiempo de uso en Windows
Este script debe ejecutarse en la PC del cliente y se conecta al servidor
para recibir el tiempo asignado y bloquear la PC cuando expire.
"""

import requests
import time
import sys
import os
from datetime import datetime, timedelta
import ctypes
from ctypes import wintypes
import threading

# Importar protecciones
try:
    from protection import apply_protections
    PROTECTION_AVAILABLE = True
except ImportError:
    PROTECTION_AVAILABLE = False

# Importar gestor de registro
try:
    from registry_manager import (
        save_session_to_registry,
        get_session_from_registry,
        clear_session_from_registry,
        get_remaining_seconds,
        is_session_expired,
        get_session_info,
        save_client_id_to_registry,
        get_client_id_from_registry
    )
    REGISTRY_AVAILABLE = True
except ImportError:
    REGISTRY_AVAILABLE = False

# Manejar rutas cuando se ejecuta como .exe (PyInstaller)
def get_base_path():
    """Obtiene la ruta base del ejecutable o script"""
    if getattr(sys, 'frozen', False):
        # Ejecutándose como .exe compilado
        return os.path.dirname(sys.executable)
    else:
        # Ejecutándose como script
        return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()

# Importar configuración
try:
    # Intentar importar desde el directorio del ejecutable
    config_path = os.path.join(BASE_PATH, 'config.py')
    if os.path.exists(config_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("config", config_path)
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        SERVER_URL = getattr(config, 'SERVER_URL', 'http://localhost:5000')
        CHECK_INTERVAL = getattr(config, 'CHECK_INTERVAL', 5)
        CLIENT_ID_FILE = getattr(config, 'CLIENT_ID_FILE', 'client_id.txt')
    else:
        # Si no existe config.py, usar valores por defecto
        SERVER_URL = "http://localhost:5000"
        CHECK_INTERVAL = 5
        CLIENT_ID_FILE = os.path.join(BASE_PATH, "client_id.txt")
except ImportError:
    # Fallback: valores por defecto
    SERVER_URL = "http://localhost:5000"
    CHECK_INTERVAL = 5
    CLIENT_ID_FILE = os.path.join(BASE_PATH, "client_id.txt")

# Windows API para bloquear la pantalla
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Constantes de Windows API
WTS_CURRENT_SERVER_HANDLE = 0
WTS_SESSION_LOCK = 0x00000007
WTS_SESSION_UNLOCK = 0x00000008

def lock_workstation():
    """
    Bloquea la estación de trabajo de Windows usando la API nativa.
    
    Utiliza LockWorkStation() que es equivalente a presionar Windows+L.
    Si el usuario desbloquea la pantalla, el cliente volverá a bloquearla
    automáticamente cada 2 segundos mientras la sesión esté expirada.
    """
    try:
        result = user32.LockWorkStation()
        if result:
            return True
        else:
            # Si LockWorkStation falla, intentar método alternativo
            return lock_workstation_alternative()
    except Exception as e:
        print(f"Error al bloquear la PC: {e}")
        return lock_workstation_alternative()

def lock_workstation_alternative():
    """
    Método alternativo de bloqueo usando mensajes del sistema.
    Se usa como respaldo si LockWorkStation() falla.
    """
    try:
        # Enviar comando de bloqueo usando mensajes del sistema
        HWND_BROADCAST = 0xFFFF
        WM_SYSCOMMAND = 0x0112
        SC_MONITORPOWER = 0xF170
        
        # Bloquear la pantalla
        user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)
        return True
    except Exception as e:
        print(f"Error en método alternativo: {e}")
        return False


def get_client_id():
    """Obtiene el ID del cliente desde registro, archivo o lo genera si no existe"""
    # Intentar obtener del registro primero
    if REGISTRY_AVAILABLE:
        client_id = get_client_id_from_registry()
        if client_id:
            return client_id
    
    # Si no está en registro, intentar desde archivo
    client_id_file_path = os.path.join(BASE_PATH, os.path.basename(CLIENT_ID_FILE))
    if os.path.exists(client_id_file_path):
        with open(client_id_file_path, 'r') as f:
            client_id = f.read().strip()
            if client_id:
                # Guardar en registro para futuras veces
                if REGISTRY_AVAILABLE:
                    save_client_id_to_registry(client_id)
                return client_id
    
    # Si no existe, registrar nuevo cliente
    return register_new_client()

def register_new_client():
    """Registra un nuevo cliente en el servidor"""
    try:
        import socket
        client_name = socket.gethostname()
        
        response = requests.post(
            f"{SERVER_URL}/api/register",
            json={'name': client_name},
            timeout=10
        )
        
        if response.status_code == 201:
            data = response.json()
            client_id = data['client_id']
            
            # Guardar el ID del cliente
            client_id_file_path = os.path.join(BASE_PATH, os.path.basename(CLIENT_ID_FILE))
            with open(client_id_file_path, 'w') as f:
                f.write(client_id)
            
            # También guardar en registro
            if REGISTRY_AVAILABLE:
                save_client_id_to_registry(client_id)
            
            print(f"Cliente registrado exitosamente. ID: {client_id}")
            return client_id
        else:
            print(f"Error al registrar cliente: {response.status_code}")
            print(response.text)
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión al servidor: {e}")
        print("Asegúrate de que el servidor esté ejecutándose.")
        return None

def check_server_status(client_id):
    """Verifica el estado del cliente en el servidor"""
    try:
        response = requests.get(
            f"{SERVER_URL}/api/client/{client_id}/status",
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get('client', {})
        else:
            print(f"Error al obtener estado: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión: {e}")
        return None

def format_time(seconds):
    """Formatea segundos a formato legible"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def sync_with_server(client_id):
    """
    Sincroniza con el servidor y actualiza el registro local.
    Se ejecuta periódicamente para mantener la información actualizada.
    """
    try:
        client_data = check_server_status(client_id)
        if client_data is None:
            return False
        
        session = client_data.get('session')
        
        if session is None:
            # No hay sesión activa en el servidor, limpiar registro local
            if REGISTRY_AVAILABLE:
                clear_session_from_registry()
            return False
        
        # Actualizar registro local con información del servidor
        if REGISTRY_AVAILABLE:
            save_session_to_registry(
                session['time_limit_seconds'],
                session['start_time'],
                session['end_time']
            )
        return True
    except Exception as e:
        print(f"Error al sincronizar con servidor: {e}")
        return False

def monitor_time(client_id):
    """
    Monitorea el tiempo restante leyendo del registro local.
    Sincroniza con el servidor periódicamente pero funciona principalmente del registro.
    """
    print("=" * 50)
    print("Cliente CiberMonday iniciado")
    print("=" * 50)
    print(f"ID del cliente: {client_id}")
    print(f"Servidor: {SERVER_URL}")
    if REGISTRY_AVAILABLE:
        print("Modo: Registro local (funciona sin conexión continua)")
    else:
        print("Modo: Consulta directa al servidor")
    print("Esperando asignación de tiempo...")
    print("=" * 50)
    
    last_remaining = None
    last_sync_time = 0
    SYNC_INTERVAL = 30  # Sincronizar con servidor cada 30 segundos
    LOCAL_CHECK_INTERVAL = 1  # Verificar registro local cada segundo
    
    while True:
        try:
            current_time = time.time()
            
            # Sincronizar con servidor periódicamente
            if current_time - last_sync_time >= SYNC_INTERVAL:
                sync_with_server(client_id)
                last_sync_time = current_time
            
            # Leer del registro local (o del servidor si no hay registro)
            if REGISTRY_AVAILABLE:
                session_info = get_session_info()
                if session_info is None:
                    # No hay sesión en registro, intentar sincronizar inmediatamente
                    if current_time - last_sync_time >= 5:  # Esperar al menos 5 segundos
                        sync_with_server(client_id)
                        last_sync_time = current_time
                        session_info = get_session_info()
                    
                    if session_info is None:
                        if last_remaining is not None:
                            print("\rEsperando asignación de tiempo...", end='', flush=True)
                        time.sleep(LOCAL_CHECK_INTERVAL)
                        continue
                
                remaining_seconds = session_info['remaining_seconds']
                is_expired = session_info['is_expired']
            else:
                # Fallback: consultar servidor directamente
                client_data = check_server_status(client_id)
                if client_data is None:
                    print("No se pudo conectar al servidor. Reintentando...")
                    time.sleep(CHECK_INTERVAL)
                    continue
                
                session = client_data.get('session')
                if session is None:
                    if last_remaining is not None:
                        print("\rEsperando asignación de tiempo...", end='', flush=True)
                    time.sleep(CHECK_INTERVAL)
                    continue
                
                remaining_seconds = session.get('remaining_seconds', 0)
                is_expired = session.get('is_expired', False)
            
            # Verificar si expiró
            if is_expired or remaining_seconds <= 0:
                # Bloquear continuamente mientras la sesión esté expirada
                if last_remaining is None or last_remaining > 0:
                    print("\n" + "=" * 50)
                    print("¡TIEMPO AGOTADO!")
                    print("La PC se bloqueará continuamente hasta que se asigne nuevo tiempo.")
                    print("=" * 50)
                
                # Bloquear la estación de trabajo
                lock_workstation()
                
                # Verificar periódicamente si se asignó nuevo tiempo
                time.sleep(2)
                continue
            
            # Mostrar tiempo restante
            if last_remaining != remaining_seconds:
                remaining_str = format_time(remaining_seconds)
                print(f"\rTiempo restante: {remaining_str}", end='', flush=True)
                last_remaining = remaining_seconds
            
            time.sleep(LOCAL_CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n\nCliente detenido por el usuario.")
            break
        except Exception as e:
            print(f"\nError inesperado: {e}")
            time.sleep(LOCAL_CHECK_INTERVAL)

def main():
    """Función principal"""
    # Verificar que estamos en Windows
    if sys.platform != 'win32':
        print("ERROR: Este cliente solo funciona en Windows.")
        sys.exit(1)
    
    # Aplicar protecciones si están disponibles
    if PROTECTION_AVAILABLE:
        try:
            protections = apply_protections()
            if protections:
                print("Protecciones aplicadas:", ", ".join(protections))
        except Exception as e:
            print(f"Advertencia: No se pudieron aplicar todas las protecciones: {e}")
    
    # Verificar permisos de administrador (recomendado)
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        if not is_admin:
            print("ADVERTENCIA: No se ejecuta como administrador.")
            print("El bloqueo y las protecciones pueden no funcionar correctamente.")
            print("Presiona Enter para continuar o Ctrl+C para salir...")
            input()
    except:
        pass
    
    # Obtener o registrar cliente
    client_id = get_client_id()
    
    if client_id is None:
        print("No se pudo registrar el cliente. Saliendo...")
        sys.exit(1)
    
    # Iniciar monitoreo
    try:
        monitor_time(client_id)
    except Exception as e:
        print(f"Error fatal: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
