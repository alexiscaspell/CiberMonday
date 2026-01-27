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
import socket
import json

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
        get_client_id_from_registry,
        save_config_to_registry,
        get_config_from_registry
    )
    REGISTRY_AVAILABLE = True
    # Importar funciones nuevas de servidores (opcional, no crítico)
    try:
        from registry_manager import (
            save_servers_to_registry,
            get_servers_from_registry
        )
    except ImportError:
        # Si no están disponibles, definir funciones dummy
        def save_servers_to_registry(servers_list):
            return False
        def get_servers_from_registry():
            return []
except ImportError:
    REGISTRY_AVAILABLE = False
    # Funciones dummy si no hay registro disponible
    def save_servers_to_registry(servers_list):
        return False
    def get_servers_from_registry():
        return []

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

# Importar configuración desde registro o GUI
# Verificar si estamos ejecutándonos como servicio (sin GUI disponible)
# La forma más simple: verificar el nombre del ejecutable/script
IS_SERVICE = False
try:
    # Obtener el nombre del ejecutable/script que se está ejecutando
    if getattr(sys, 'frozen', False):
        # Ejecutándose como .exe compilado
        # sys.executable puede ser el ejecutable temporal de PyInstaller
        # Usar sys.argv[0] que contiene el nombre real del ejecutable
        if len(sys.argv) > 0:
            script_name = os.path.basename(sys.argv[0]).lower()
        else:
            script_name = os.path.basename(sys.executable).lower()
    else:
        # Ejecutándose como script Python
        script_name = os.path.basename(sys.argv[0]).lower() if len(sys.argv) > 0 else ''
    
    # Solo es servicio si es específicamente el ejecutable del servicio
    # NO es servicio si es el cliente (CiberMondayClient.exe o client.py)
    if 'cibermondayservice' in script_name or script_name == 'service.exe' or script_name == 'service.py':
        # Es el servicio, no mostrar GUI
        IS_SERVICE = True
    elif 'cibermondayclient' in script_name or script_name == 'client.exe' or script_name == 'client.py':
        # Es el cliente, SÍ mostrar GUI
        IS_SERVICE = False
    else:
        # Por defecto, asumir que NO es servicio (podemos mostrar GUI)
        IS_SERVICE = False
except:
    # Si hay algún error, asumir que no es servicio (podemos mostrar GUI)
    IS_SERVICE = False

try:
    from registry_manager import get_config_from_registry
    
    # Intentar obtener configuración del registro
    config_data = get_config_from_registry()
    
    if not config_data or not config_data.get('server_url'):
        # No hay configuración - siempre mostrar GUI si no es servicio
        if IS_SERVICE:
            # Si es servicio, usar valores por defecto y loguear error
            print("ERROR: No hay configuración guardada.")
            print("Ejecuta CiberMondayClient.exe manualmente primero para configurar.")
            SERVER_URL = "http://localhost:5000"
            CHECK_INTERVAL = 5
            SYNC_INTERVAL_CONFIG = 30
        else:
            # Si no es servicio, mostrar GUI
            try:
                from config_gui import show_config_window
                print("No se encontró configuración. Abriendo ventana de configuración...")
                config_data = show_config_window()
                
                if not config_data:
                    print("Configuración cancelada. Saliendo...")
                    sys.exit(1)
                
                SERVER_URL = config_data.get('server_url', 'http://localhost:5000')
                CHECK_INTERVAL = config_data.get('check_interval', 5)
                SYNC_INTERVAL_CONFIG = config_data.get('sync_interval', 30)
            except Exception as e:
                import traceback
                print(f"Error al mostrar GUI de configuración: {e}")
                traceback.print_exc()
                print("Usando valores por defecto: http://localhost:5000")
                SERVER_URL = "http://localhost:5000"
                CHECK_INTERVAL = 5
                SYNC_INTERVAL_CONFIG = 30
    else:
        # Configuración encontrada en registro
        # Siempre mostrar GUI para permitir modificar (excepto si es servicio)
        if not IS_SERVICE:
            try:
                from config_gui import show_config_window
                # Mostrar ventana con valores actuales para permitir modificar
                updated_config = show_config_window()
                
                if updated_config:
                    # Usar configuración actualizada
                    config_data = updated_config
                    SERVER_URL = config_data.get('server_url', 'http://localhost:5000')
                    CHECK_INTERVAL = config_data.get('check_interval', 5)
                    SYNC_INTERVAL_CONFIG = config_data.get('sync_interval', 30)
                else:
                    # Usuario canceló pero hay configuración previa, usar esa
                    SERVER_URL = config_data.get('server_url', 'http://localhost:5000')
                    CHECK_INTERVAL = config_data.get('check_interval', 5)
                    SYNC_INTERVAL_CONFIG = config_data.get('sync_interval', 30)
            except Exception as e:
                # Si falla la GUI, usar configuración del registro
                print(f"Advertencia: No se pudo mostrar GUI de configuración: {e}")
                SERVER_URL = config_data.get('server_url', 'http://localhost:5000')
                CHECK_INTERVAL = config_data.get('check_interval', 5)
                SYNC_INTERVAL_CONFIG = config_data.get('sync_interval', 30)
        else:
            # Es servicio, usar configuración del registro directamente
            SERVER_URL = config_data.get('server_url', 'http://localhost:5000')
            CHECK_INTERVAL = config_data.get('check_interval', 5)
            SYNC_INTERVAL_CONFIG = config_data.get('sync_interval', 30)
    
    CLIENT_ID_FILE = os.path.join(BASE_PATH, "client_id.txt")
    
except ImportError:
    # Fallback si no hay módulos disponibles
    SERVER_URL = "http://localhost:5000"
    CHECK_INTERVAL = 5
    SYNC_INTERVAL_CONFIG = 30
    CLIENT_ID_FILE = os.path.join(BASE_PATH, "client_id.txt")

# Windows API para bloquear la pantalla
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Constantes de Windows API
WTS_CURRENT_SERVER_HANDLE = 0
WTS_SESSION_LOCK = 0x00000007
WTS_SESSION_UNLOCK = 0x00000008

# ==================== SISTEMA DE ALERTAS DE TIEMPO ====================
# Umbrales de alerta en segundos (10min, 5min, 2min, 1min)
# Se cargan desde la configuración del registro o se usan valores por defecto
def get_alert_thresholds():
    """Obtiene los umbrales de alerta desde la configuración"""
    if REGISTRY_AVAILABLE:
        try:
            config = get_config_from_registry()
            if config and 'alert_thresholds' in config:
                thresholds = config['alert_thresholds']
                if isinstance(thresholds, list) and len(thresholds) > 0:
                    return sorted(thresholds, reverse=True)
        except:
            pass
    return [600, 300, 120, 60]  # Valores por defecto: 10min, 5min, 2min, 1min

ALERT_THRESHOLDS = get_alert_thresholds()

# Diccionario para rastrear qué alertas ya se mostraron
# Se resetea cuando se asigna nuevo tiempo
alerts_shown = {threshold: False for threshold in ALERT_THRESHOLDS}
last_known_remaining = None  # Para detectar cambios drásticos de tiempo

def update_alert_thresholds(new_thresholds):
    """Actualiza los umbrales de alerta dinámicamente"""
    global ALERT_THRESHOLDS, alerts_shown
    
    if isinstance(new_thresholds, list) and len(new_thresholds) > 0:
        new_thresholds = sorted(new_thresholds, reverse=True)
        if new_thresholds != ALERT_THRESHOLDS:
            print(f"[Config] Umbrales de alerta actualizados: {ALERT_THRESHOLDS} -> {new_thresholds}")
            ALERT_THRESHOLDS = new_thresholds
            # Reinicializar el diccionario de alertas mostradas
            alerts_shown = {threshold: False for threshold in ALERT_THRESHOLDS}

def reset_alerts_for_new_session(remaining_seconds):
    """
    Resetea las alertas cuando se detecta una nueva sesión o cambio de tiempo.
    Solo marca como 'ya mostradas' las alertas de umbrales MAYORES al tiempo actual,
    para evitar que se muestren en cascada si el admin reduce el tiempo drásticamente.
    """
    global alerts_shown, last_known_remaining
    
    for threshold in ALERT_THRESHOLDS:
        if remaining_seconds <= threshold:
            # El tiempo actual ya pasó este umbral, marcar como mostrado
            # para evitar mostrar alertas de umbrales ya pasados
            alerts_shown[threshold] = True
        else:
            # El tiempo actual es mayor a este umbral, permitir que se muestre
            alerts_shown[threshold] = False
    
    last_known_remaining = remaining_seconds

def check_and_show_alerts(remaining_seconds, previous_remaining=None):
    """
    Verifica si se debe mostrar alguna alerta basándose en el tiempo restante.
    
    Lógica:
    - Si el tiempo cruzó un umbral (de arriba hacia abajo), mostrar alerta
    - Si hubo un cambio drástico de tiempo (ej: de 60min a 1min), solo mostrar
      la alerta del umbral actual, no todas las intermedias
    """
    global alerts_shown, last_known_remaining
    
    # Detectar si hubo un cambio drástico de tiempo (reducción de más de 2 minutos de golpe)
    if previous_remaining is not None and previous_remaining - remaining_seconds > 120:
        # Cambio drástico detectado - resetear alertas apropiadamente
        reset_alerts_for_new_session(remaining_seconds)
    
    # Verificar cada umbral
    for threshold in sorted(ALERT_THRESHOLDS, reverse=True):  # De mayor a menor
        if remaining_seconds <= threshold and not alerts_shown[threshold]:
            # Cruzamos este umbral y no se ha mostrado la alerta
            show_time_alert(threshold, remaining_seconds)
            alerts_shown[threshold] = True
            # Solo mostrar una alerta a la vez
            break
    
    last_known_remaining = remaining_seconds

def get_alert_message(threshold, remaining_seconds):
    """Genera el mensaje de alerta según el umbral"""
    minutes = threshold // 60
    
    if threshold == 600:
        return f"⚠️ AVISO: Te quedan 10 minutos de tiempo.\n\nGuarda tu trabajo."
    elif threshold == 300:
        return f"⚠️ ATENCIÓN: Te quedan 5 minutos de tiempo.\n\nPrepárate para terminar."
    elif threshold == 120:
        return f"🔴 ADVERTENCIA: Te quedan solo 2 minutos.\n\n¡Guarda todo ahora!"
    elif threshold == 60:
        return f"🚨 ¡ÚLTIMO MINUTO!\n\nLa PC se bloqueará en 1 minuto.\n¡Guarda tu trabajo inmediatamente!"
    else:
        return f"Quedan {minutes} minutos."

def show_time_alert(threshold, remaining_seconds):
    """
    Muestra una ventana emergente de alerta usando la API de Windows.
    La ventana aparece en primer plano para asegurar que el usuario la vea.
    """
    try:
        message = get_alert_message(threshold, remaining_seconds)
        
        # Determinar el tipo de icono según la urgencia
        if threshold <= 60:
            icon = 0x30  # MB_ICONWARNING (triángulo amarillo con !)
            title = "⚠️ ¡TIEMPO CASI AGOTADO!"
        elif threshold <= 120:
            icon = 0x30  # MB_ICONWARNING
            title = "⚠️ Advertencia de Tiempo"
        else:
            icon = 0x40  # MB_ICONINFORMATION
            title = "⏰ Aviso de Tiempo"
        
        # MB_OK | MB_TOPMOST | icon
        # MB_OK = 0x0
        # MB_TOPMOST = 0x40000 (hace que la ventana aparezca encima de todo)
        # MB_SETFOREGROUND = 0x10000 (trae la ventana al frente)
        flags = 0x0 | 0x40000 | 0x10000 | icon
        
        # Mostrar en un thread separado para no bloquear el monitoreo
        def show_message():
            user32.MessageBoxW(0, message, title, flags)
        
        alert_thread = threading.Thread(target=show_message, daemon=True)
        alert_thread.start()
        
        print(f"\n[ALERTA] {title}: {threshold//60} minuto(s) restante(s)")
        
    except Exception as e:
        print(f"Error al mostrar alerta: {e}")

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

def get_available_servers():
    """
    Obtiene la lista de servidores disponibles.
    Retorna lista con el servidor principal primero, seguido de servidores conocidos.
    """
    servers = []
    
    # Agregar servidor principal
    if SERVER_URL:
        servers.append({
            'url': SERVER_URL,
            'priority': 0  # Mayor prioridad
        })
    
    # Agregar servidores conocidos del registro
    if REGISTRY_AVAILABLE:
        known_servers = get_servers_from_registry()
        for server in known_servers:
            server_url = server.get('url')
            if server_url and server_url != SERVER_URL:
                servers.append({
                    'url': server_url,
                    'priority': 1  # Menor prioridad
                })
    
    return servers

def find_available_server(servers_list=None):
    """
    Intenta encontrar un servidor disponible de la lista.
    Retorna la URL del servidor disponible o None.
    """
    if servers_list is None:
        servers_list = get_available_servers()
    
    # Ordenar por prioridad
    servers_list.sort(key=lambda x: x.get('priority', 1))
    
    for server in servers_list:
        server_url = server.get('url')
        if not server_url:
            continue
        
        try:
            # Intentar conectar al servidor
            response = requests.get(f"{server_url}/api/health", timeout=3)
            if response.status_code == 200:
                return server_url
        except:
            continue
    
    return None

def register_new_client(existing_client_id=None):
    """
    Registra un nuevo cliente en el servidor o re-registra uno existente.
    Si se proporciona existing_client_id, se hace re-registro conservando el ID.
    También envía la sesión activa y configuración si existen en el registro local.
    """
    try:
        import socket
        client_name = socket.gethostname()
        
        # Preparar datos de registro
        # Verificar si hay un nombre personalizado guardado
        custom_name = None
        if REGISTRY_AVAILABLE:
            config_data = get_config_from_registry()
            if config_data:
                custom_name = config_data.get('custom_name')
        
        # Usar nombre personalizado si existe, sino el nombre del equipo
        register_data = {'name': custom_name if custom_name else client_name}
        
        # Si es re-registro, incluir el ID existente
        if existing_client_id:
            register_data['client_id'] = existing_client_id
        
        # Incluir sesión activa si existe en el registro local
        if REGISTRY_AVAILABLE:
            session_info = get_session_info()
            if session_info and not session_info['is_expired'] and session_info['remaining_seconds'] > 0:
                session_data = get_session_from_registry()
                if session_data:
                    register_data['session'] = {
                        'remaining_seconds': session_info['remaining_seconds'],
                        'time_limit_seconds': session_data.get('time_limit_seconds', session_info['remaining_seconds'])
                    }
                    print(f"[Re-registro] Enviando sesión activa: {session_info['remaining_seconds']}s restantes")
            
            # Incluir configuración actual del cliente (incluyendo nombre personalizado)
            if config_data:
                register_data['config'] = {
                    'sync_interval': config_data.get('sync_interval', 30),
                    'alert_thresholds': config_data.get('alert_thresholds', [600, 300, 120, 60]),
                    'custom_name': custom_name
                }
        
        # Incluir lista de servidores conocidos
        if REGISTRY_AVAILABLE:
            known_servers = get_servers_from_registry()
            register_data['known_servers'] = known_servers
        
        # Intentar con múltiples servidores
        servers_list = get_available_servers()
        available_server = find_available_server(servers_list)
        
        if not available_server:
            print("Error: No hay servidores disponibles")
            return None
        
        response = requests.post(
            f"{available_server}/api/register",
            json=register_data,
            timeout=10
        )
        
        if response.status_code == 201:
            data = response.json()
            client_id = data['client_id']
            session_restored = data.get('session_restored', False)
            server_config = data.get('config')
            known_servers = data.get('known_servers', [])
            
            # Guardar lista de servidores conocidos
            if REGISTRY_AVAILABLE and known_servers:
                save_servers_to_registry(known_servers)
                print(f"[Servidores] Actualizada lista de {len(known_servers)} servidores conocidos")
            
            # Guardar el ID del cliente
            client_id_file_path = os.path.join(BASE_PATH, os.path.basename(CLIENT_ID_FILE))
            with open(client_id_file_path, 'w') as f:
                f.write(client_id)
            
            # También guardar en registro
            if REGISTRY_AVAILABLE:
                save_client_id_to_registry(client_id)
                
                # Aplicar configuración recibida del servidor
                if server_config:
                    apply_server_config(server_config)
            
            if existing_client_id:
                print(f"Cliente re-registrado exitosamente. ID: {client_id}")
                if session_restored:
                    print(f"[Re-registro] Sesión restaurada en el servidor")
            else:
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

def apply_server_config(server_config):
    """
    Aplica la configuración recibida del servidor.
    Actualiza el registro local y las variables globales.
    """
    global SYNC_INTERVAL_CONFIG
    
    if not server_config:
        return
    
    try:
        # Obtener configuración actual
        current_config = get_config_from_registry() or {}
        
        # Actualizar con valores del servidor
        if 'sync_interval' in server_config:
            new_sync = server_config['sync_interval']
            if new_sync != current_config.get('sync_interval'):
                print(f"[Config] Intervalo de sincronización: {current_config.get('sync_interval', 30)} -> {new_sync}")
                current_config['sync_interval'] = new_sync
                SYNC_INTERVAL_CONFIG = new_sync
        
        if 'alert_thresholds' in server_config:
            new_thresholds = server_config['alert_thresholds']
            update_alert_thresholds(new_thresholds)
            current_config['alert_thresholds'] = new_thresholds
        
        if 'custom_name' in server_config:
            new_name = server_config['custom_name']
            old_name = current_config.get('custom_name')
            if new_name != old_name:
                if new_name:
                    print(f"[Config] Nombre personalizado: {old_name or '(ninguno)'} -> {new_name}")
                else:
                    print(f"[Config] Nombre personalizado eliminado (se usará nombre del equipo)")
                current_config['custom_name'] = new_name
        
        # Guardar configuración actualizada en el registro
        # Preservar server_url del registro local
        current_config['server_url'] = current_config.get('server_url', SERVER_URL)
        save_config_to_registry(current_config)
        
    except Exception as e:
        print(f"[Config] Error al aplicar configuración del servidor: {e}")

def report_session_to_server(client_id, server_url=None):
    """
    Reporta la sesión activa del cliente al servidor.
    Útil cuando el servidor perdió la información pero el cliente la tiene.
    """
    if not REGISTRY_AVAILABLE:
        return False
    
    session_info = get_session_info()
    if not session_info or session_info['is_expired'] or session_info['remaining_seconds'] <= 0:
        return False
    
    session_data = get_session_from_registry()
    if not session_data:
        return False
    
    # Usar servidor proporcionado o encontrar uno disponible
    if not server_url:
        servers_list = get_available_servers()
        available_server = find_available_server(servers_list)
        if not available_server:
            return False
        server_url = available_server
    
    try:
        response = requests.post(
            f"{server_url}/api/client/{client_id}/report-session",
            json={
                'remaining_seconds': session_info['remaining_seconds'],
                'time_limit_seconds': session_data.get('time_limit_seconds', session_info['remaining_seconds'])
            },
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"[Reporte] Sesión reportada al servidor: {session_info['remaining_seconds']}s restantes")
            return True
        else:
            print(f"[Reporte] Error al reportar sesión: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"[Reporte] Error de conexión: {e}")
        return False

def check_server_status(client_id):
    """Verifica el estado del cliente en el servidor"""
    # Buscar un servidor disponible
    servers_list = get_available_servers()
    available_server = find_available_server(servers_list)
    if not available_server:
        print(f"[Status] No hay servidores disponibles")
        return None
    
    server_url = available_server
    try:
        response = requests.get(
            f"{server_url}/api/client/{client_id}/status",
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get('client', {})
        elif response.status_code == 404:
            # Cliente no encontrado en el servidor (probablemente se reinició)
            print(f"Cliente no encontrado en el servidor (404). El servidor puede haberse reiniciado.")
            return None
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
    Intenta con múltiples servidores si uno falla.
    """
    global last_known_remaining  # Declarar al inicio de la función
    
    # Obtener lista de servidores disponibles
    servers_list = get_available_servers()
    available_server = find_available_server(servers_list)
    
    if not available_server:
        print("[Sincronización] No hay servidores disponibles")
        return False
    
    try:
        response = requests.get(
            f"{available_server}/api/client/{client_id}/status",
            timeout=10
        )
        
        if response.status_code == 404:
            # Cliente no encontrado - intentar re-registrarse CON EL MISMO ID
            # Esto permite que el servidor recupere la sesión del cliente
            print(f"\n[Re-registro] Cliente no encontrado en {available_server}. Intentando re-registrarse con ID existente...")
            new_client_id = register_new_client(existing_client_id=client_id)
            if new_client_id:
                print(f"[Re-registro] Cliente re-registrado exitosamente. ID: {new_client_id}")
                # Retornar el ID (debería ser el mismo) para que se use en el loop principal
                return new_client_id
            else:
                print("[Re-registro] Error: No se pudo re-registrar el cliente")
                return False
        
        if response.status_code != 200:
            print(f"Error al obtener estado desde {available_server}: {response.status_code}")
            # Intentar con otro servidor si hay más disponibles
            other_servers = [s for s in servers_list if s.get('url') != available_server]
            if other_servers:
                print(f"[Reintento] Intentando con otro servidor...")
                return sync_with_server(client_id)  # Recursión con otro servidor
            return False
        
        data = response.json()
        client_data = data.get('client', {})
        
        # Aplicar configuración del servidor si está disponible
        server_config = client_data.get('config')
        if server_config and REGISTRY_AVAILABLE:
            apply_server_config(server_config)
        
        session = client_data.get('session')
        
        if session is None:
            # El servidor no tiene sesión para este cliente
            # Verificar si el cliente tiene una sesión válida localmente
            if REGISTRY_AVAILABLE:
                local_session = get_session_info()
                if local_session and not local_session['is_expired'] and local_session['remaining_seconds'] > 0:
                    # El cliente tiene una sesión válida - reportarla al servidor
                    print(f"\n[Sincronización] Servidor {available_server} sin sesión, pero cliente tiene {local_session['remaining_seconds']}s restantes")
                    print(f"[Sincronización] Reportando sesión al servidor...")
                    if report_session_to_server(client_id, server_url=available_server):
                        # Sesión reportada exitosamente, no borrar registro local
                        return True
                    else:
                        # No se pudo reportar, pero NO borrar la sesión local
                        # El cliente debe seguir funcionando con su tiempo local
                        print(f"[Sincronización] No se pudo reportar al servidor, manteniendo sesión local")
                        return False
                else:
                    # No hay sesión válida localmente, limpiar registro
                    clear_session_from_registry()
            return False
        
        # Verificar que los datos de sesión sean válidos
        time_limit = session.get('time_limit_seconds', 0)
        start_time = session.get('start_time')
        end_time = session.get('end_time')
        
        if not all([time_limit, start_time, end_time]):
            print("Advertencia: Datos de sesión incompletos del servidor")
            return False
        
        # CÁLCULO SIMPLE: El cliente guarda su propia hora local
        # Cuando el servidor dice "tienes X segundos restantes", el cliente guarda:
        # end_time_local = hora_actual_cliente + X_segundos
        # Así, el cálculo siempre será correcto: end_time_local - hora_actual_cliente = X_segundos
        from datetime import datetime, timedelta
        now_local = datetime.now()
        remaining_from_server = session.get('remaining_seconds', 0)
        
        # Calcular end_time usando la hora local del cliente
        end_time_local = now_local + timedelta(seconds=remaining_from_server)
        
        # Calcular start_time local para referencia (no es crítico para el cálculo)
        elapsed_seconds = time_limit - remaining_from_server
        start_time_local = now_local - timedelta(seconds=elapsed_seconds)
        
        print(f"\n[Sincronización] Guardando en registro local:")
        print(f"  - Tiempo establecido: {time_limit}s ({time_limit//60} min)")
        print(f"  - Tiempo restante (servidor): {remaining_from_server}s")
        print(f"  - Hora actual (cliente): {now_local.isoformat()}")
        print(f"  - End time (local, guardado): {end_time_local.isoformat()}")
        print(f"  - El cliente bloqueará cuando llegue a: {end_time_local.isoformat()}")
        
        # Usar los valores calculados localmente
        end_time = end_time_local.isoformat()
        start_time = start_time_local.isoformat()
        
        # Detectar si es una nueva sesión o cambio drástico de tiempo
        # para resetear las alertas apropiadamente
        if last_known_remaining is None or abs(last_known_remaining - remaining_from_server) > 120:
            # Nueva sesión o cambio drástico - resetear alertas
            reset_alerts_for_new_session(remaining_from_server)
            print(f"[Alertas] Reset de alertas. Tiempo restante: {remaining_from_server}s")
        
        # Actualizar registro local con información del servidor
        if REGISTRY_AVAILABLE:
            # IMPORTANTE: Limpiar completamente la sesión anterior antes de guardar nueva
            # Esto asegura que no queden datos antiguos corruptos
            clear_session_from_registry()
            
            # Pequeña pausa para asegurar que el registro se limpió
            import time as time_module
            time_module.sleep(0.1)
            
            # Guardar nueva sesión con valores corregidos (start_time y end_time locales)
            success = save_session_to_registry(
                time_limit,
                start_time,  # start_time corregido local
                end_time     # end_time corregido local
            )
            
            if success:
                # Verificar que se guardó correctamente leyendo del registro
                import time as time_module
                time_module.sleep(0.1)  # Pequeña pausa para asegurar que se escribió
                
                saved_session = get_session_from_registry()
                if saved_session:
                    saved_end_time = saved_session.get('end_time')
                    saved_start_time = saved_session.get('start_time')
                    saved_time_limit = saved_session.get('time_limit_seconds')
                    
                    # Calcular tiempo restante desde el registro guardado
                    if saved_end_time:
                        try:
                            from datetime import datetime, timedelta
                            end_time_dt = datetime.fromisoformat(saved_end_time)
                            now = datetime.now()
                            remaining_from_registry = int((end_time_dt - now).total_seconds())
                            
                            # Verificar que los valores guardados sean correctos
                            remaining = session.get('remaining_seconds', 0)
                            print(f"\n[Verificación] Registro guardado correctamente:")
                            print(f"  - time_limit_seconds: {saved_time_limit}")
                            print(f"  - start_time guardado: {saved_start_time}")
                            print(f"  - end_time guardado: {saved_end_time}")
                            print(f"  - Tiempo restante calculado: {remaining_from_registry}s ({remaining_from_registry//60} min)")
                            print(f"  - Tiempo restante esperado (servidor): {remaining}s ({remaining//60} min)")
                            
                            # Si hay discrepancia, mostrar advertencia
                            if abs(remaining_from_registry - remaining) > 5:
                                print(f"[ADVERTENCIA] Discrepancia: {abs(remaining_from_registry - remaining)}s")
                        except Exception as e:
                            print(f"[Error] Al verificar registro guardado: {e}")
                            import traceback
                            traceback.print_exc()
                    else:
                        print("[ADVERTENCIA] No se encontró end_time en el registro guardado")
                else:
                    print("[ADVERTENCIA] No se pudo leer el registro después de guardar")
            else:
                print("[ERROR] No se pudo guardar la sesión en el registro")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión al sincronizar: {e}")
        return False
    except Exception as e:
        print(f"Error al sincronizar con servidor: {e}")
        import traceback
        traceback.print_exc()
        return False

def start_server_discovery_listener():
    """
    Inicia un servidor UDP que escucha broadcasts de nuevos servidores.
    Cuando recibe un broadcast, registra el servidor automáticamente.
    """
    def listener_thread():
        # Puerto para recibir broadcasts de servidores
        DISCOVERY_PORT = 5001
        
        try:
            # Crear socket UDP para escuchar broadcasts
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(('', DISCOVERY_PORT))
            sock.settimeout(1.0)  # Timeout para poder verificar si el thread debe continuar
            
            print(f"[Discovery] Escuchando broadcasts de servidores en puerto {DISCOVERY_PORT}...")
            print(f"[Discovery] El listener está activo y escuchando...")
            
            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                    server_info = json.loads(data.decode('utf-8'))
                    
                    server_url = server_info.get('url')
                    server_ip = server_info.get('ip', addr[0])
                    server_port = server_info.get('port', 5000)
                    
                    if server_url:
                        print(f"[Discovery] Nuevo servidor detectado: {server_url} desde {addr[0]}")
                        
                        # Registrar el servidor en nuestra lista
                        if REGISTRY_AVAILABLE:
                            known_servers = get_servers_from_registry()
                            
                            # Verificar si ya existe
                            if not any(s.get('url') == server_url for s in known_servers):
                                known_servers.append({
                                    'url': server_url,
                                    'ip': server_ip,
                                    'port': server_port,
                                    'last_seen': datetime.now().isoformat()
                                })
                                save_servers_to_registry(known_servers)
                                print(f"[Discovery] Servidor {server_url} registrado exitosamente")
                            else:
                                print(f"[Discovery] Servidor {server_url} ya conocido")
                        
                        # También registrar directamente en el servidor usando el endpoint
                        try:
                            response = requests.post(
                                f"{server_url}/api/register-server",
                                json={
                                    'url': server_url,
                                    'ip': server_ip,
                                    'port': server_port
                                },
                                timeout=2
                            )
                            if response.status_code == 201:
                                print(f"[Discovery] Servidor {server_url} confirmado")
                        except:
                            pass  # No crítico si falla
                            
                except socket.timeout:
                    # Timeout normal, continuar escuchando
                    continue
                except json.JSONDecodeError as e:
                    # Error al decodificar JSON, continuar escuchando
                    print(f"[Discovery] Error al decodificar JSON del broadcast: {e}")
                    continue
                except Exception as e:
                    # Error al procesar, continuar escuchando
                    print(f"[Discovery] Error al procesar broadcast: {e}")
                    continue
                    
        except Exception as e:
            print(f"[Discovery] Error en listener: {e}")
            # Reintentar después de un delay
            time.sleep(5)
            start_server_discovery_listener()
    
    # Iniciar thread en background
    thread = threading.Thread(target=listener_thread, daemon=True)
    thread.start()

def monitor_time(client_id):
    """
    Monitorea el tiempo restante leyendo del registro local.
    Sincroniza con el servidor periódicamente pero funciona principalmente del registro.
    """
    global alerts_shown  # Declarar al inicio de la función
    
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
    
    # Iniciar listener de descubrimiento de servidores
    start_server_discovery_listener()
    
    last_remaining = None
    last_sync_time = 0
    # Usar intervalo de sincronización desde configuración (o 30 por defecto)
    try:
        SYNC_INTERVAL = SYNC_INTERVAL_CONFIG
    except NameError:
        # Si no está definido, usar valor por defecto
        SYNC_INTERVAL = 30
    LOCAL_CHECK_INTERVAL = 1  # Verificar registro local cada segundo
    
    print(f"Intervalo de sincronización: {SYNC_INTERVAL} segundos")
    
    while True:
        try:
            current_time = time.time()
            
            # Sincronizar con servidor periódicamente
            if current_time - last_sync_time >= SYNC_INTERVAL:
                sync_result = sync_with_server(client_id)
                # Si sync_with_server retorna un nuevo client_id (re-registro), actualizarlo
                if sync_result and isinstance(sync_result, str):
                    print(f"[Actualización] Usando nuevo Client ID: {sync_result}")
                    client_id = sync_result
                last_sync_time = current_time
                # Forzar re-lectura del registro después de sincronizar
                # para asegurar que usamos los datos más recientes
                if REGISTRY_AVAILABLE:
                    session_info = get_session_info()
                    if session_info:
                        # Resetear last_remaining para forzar actualización de display
                        last_remaining = None
            
            # Leer del registro local (o del servidor si no hay registro)
            if REGISTRY_AVAILABLE:
                session_info = get_session_info()
                
                # Debug: mostrar qué se está leyendo del registro
                if session_info and last_remaining != session_info.get('remaining_seconds'):
                    session_data = get_session_from_registry()
                    if session_data:
                        print(f"\n[Debug] Leyendo del registro:")
                        print(f"  - time_limit_seconds: {session_data.get('time_limit_seconds')}")
                        print(f"  - end_time: {session_data.get('end_time')}")
                        print(f"  - remaining_seconds calculado: {session_info.get('remaining_seconds')}")
                
                if session_info is None:
                    # No hay sesión en registro, sincronizar más frecuentemente para detectar nuevos tiempos
                    if current_time - last_sync_time >= 2:  # Sincronizar cada 2 segundos si no hay sesión
                        sync_result = sync_with_server(client_id)
                        # Si sync_with_server retorna un nuevo client_id (re-registro), actualizarlo
                        if sync_result and isinstance(sync_result, str):
                            print(f"[Actualización] Usando nuevo Client ID: {sync_result}")
                            client_id = sync_result
                        last_sync_time = current_time
                        session_info = get_session_info()
                        # Resetear last_remaining para forzar actualización de display
                        if session_info:
                            last_remaining = None
                    
                    if session_info is None:
                        if last_remaining is not None:
                            print("\rEsperando asignación de tiempo...", end='', flush=True)
                            # Si antes había sesión y ahora no, resetear alertas para próxima sesión
                            alerts_shown = {threshold: False for threshold in ALERT_THRESHOLDS}
                        time.sleep(LOCAL_CHECK_INTERVAL)
                        continue
                
                remaining_seconds = session_info['remaining_seconds']
                is_expired = session_info['is_expired']
                
                # Si es la primera vez que vemos esta sesión, inicializar alertas
                if last_remaining is None:
                    reset_alerts_for_new_session(remaining_seconds)
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
                        # Si antes había sesión y ahora no, resetear alertas
                        alerts_shown = {threshold: False for threshold in ALERT_THRESHOLDS}
                    time.sleep(CHECK_INTERVAL)
                    continue
                
                remaining_seconds = session.get('remaining_seconds', 0)
                is_expired = session.get('is_expired', False)
                
                # Si es la primera vez que vemos esta sesión, inicializar alertas
                if last_remaining is None:
                    reset_alerts_for_new_session(remaining_seconds)
            
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
            
            # Verificar alertas de tiempo
            check_and_show_alerts(remaining_seconds, last_remaining)
            
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
    
    # La configuración ya se obtuvo al inicio del script (puede mostrar GUI)
    # Si llegamos aquí, la configuración está lista
    
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
