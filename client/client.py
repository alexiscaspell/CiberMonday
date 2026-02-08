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
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Asegurar que stdout/stderr existan (PyInstaller --windowed los deja en None)
# Sin esto, cualquier print() crashea el proceso inmediatamente
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

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
            get_servers_from_registry,
            increment_server_timeouts,
            reset_server_timeout_count
        )
    except ImportError:
        # Si no están disponibles, definir funciones dummy
        def save_servers_to_registry(servers_list):
            return False
        def get_servers_from_registry():
            return []
        def increment_server_timeouts(server_urls):
            pass
        def reset_server_timeout_count(server_url):
            pass
except ImportError:
    REGISTRY_AVAILABLE = False
    # Funciones dummy si no hay registro disponible
    def save_servers_to_registry(servers_list):
        return False
    def get_servers_from_registry():
        return []
    def increment_server_timeouts(server_urls):
        pass
    def reset_server_timeout_count(server_url):
        pass

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

# Modo configuración: si se pasa --configure, solo muestra la GUI y sale
# Usado por el instalador del servicio para configurar antes de instalar
CONFIGURE_ONLY = '--configure' in sys.argv
if CONFIGURE_ONLY:
    IS_SERVICE = False  # Forzar mostrar GUI

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
                
                # NOTA: La lista de servidores conocidos se resetea cuando se configura un nuevo servidor
                # desde la GUI (ver config_gui.py). Aquí solo verificamos que el servidor principal esté.
                # Los servidores se descubren automáticamente durante la sincronización.
                if REGISTRY_AVAILABLE:
                    try:
                        from registry_manager import get_servers_from_registry
                        known_servers = get_servers_from_registry()
                        print(f"[Inicio] Servidores conocidos en registro: {len(known_servers)}")
                        if known_servers:
                            print(f"[Inicio] Servidores: {', '.join([s.get('url', 'Unknown') for s in known_servers])}")
                    except Exception as e:
                        print(f"[Inicio] ⚠️  Advertencia: No se pudo leer lista de servidores: {e}")
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
                    
                    # NOTA: La lista de servidores conocidos se resetea cuando se configura un nuevo servidor
                    # desde la GUI (ver config_gui.py). Aquí solo verificamos que el servidor principal esté.
                    # Los servidores se descubren automáticamente durante la sincronización.
                    if REGISTRY_AVAILABLE:
                        try:
                            from registry_manager import get_servers_from_registry
                            known_servers = get_servers_from_registry()
                            print(f"[Inicio] Servidores conocidos en registro: {len(known_servers)}")
                            if known_servers:
                                print(f"[Inicio] Servidores: {', '.join([s.get('url', 'Unknown') for s in known_servers])}")
                        except Exception as e:
                            print(f"[Inicio] ⚠️  Advertencia: No se pudo leer lista de servidores: {e}")
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
            
            # NOTA: La lista de servidores conocidos se resetea cuando se configura un nuevo servidor
            # desde la GUI (ver config_gui.py). Aquí solo verificamos que el servidor principal esté.
            # Los servidores se descubren automáticamente durante la sincronización.
            if REGISTRY_AVAILABLE:
                try:
                    from registry_manager import get_servers_from_registry
                    known_servers = get_servers_from_registry()
                    print(f"[Inicio] Servidores conocidos en registro: {len(known_servers)}")
                    if known_servers:
                        print(f"[Inicio] Servidores: {', '.join([s.get('url', 'Unknown') for s in known_servers])}")
                except Exception as e:
                    print(f"[Inicio] ⚠️  Advertencia: No se pudo leer lista de servidores: {e}")
    
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
    """
    Obtiene el ID del cliente desde registro, archivo, servidor o lo genera localmente.
    NUNCA retorna None - si no puede registrarse con un servidor, genera un ID local
    y lo intentará registrar más adelante durante la sincronización.
    """
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
    
    # Intentar registrar con el servidor
    client_id = register_new_client()
    if client_id:
        return client_id
    
    # Si no se pudo registrar con ningún servidor, generar un ID local
    # El cliente se registrará con un servidor cuando uno esté disponible
    import uuid
    client_id = str(uuid.uuid4())
    print(f"[Inicio] No se pudo contactar ningún servidor. Generando ID local: {client_id}")
    print(f"[Inicio] El cliente se registrará con un servidor cuando uno esté disponible.")
    
    # Guardar el ID local
    try:
        client_id_file_path = os.path.join(BASE_PATH, os.path.basename(CLIENT_ID_FILE))
        with open(client_id_file_path, 'w') as f:
            f.write(client_id)
    except Exception as e:
        print(f"[Inicio] Advertencia: No se pudo guardar ID en archivo: {e}")
    
    if REGISTRY_AVAILABLE:
        save_client_id_to_registry(client_id)
    
    return client_id

def get_available_servers():
    """
    Obtiene la lista de servidores disponibles.
    Retorna lista con todos los servidores (principal + descubiertos) con igual prioridad.
    Los servidores descubiertos recientemente tienen prioridad ligeramente mayor.
    """
    servers = []
    seen_urls = set()
    
    # Primero agregar servidores descubiertos (más recientes primero)
    if REGISTRY_AVAILABLE:
        known_servers = get_servers_from_registry()
        
        known_servers_sorted = sorted(
            known_servers,
            key=lambda s: s.get('last_seen', ''),
            reverse=True
        )
        
        for server in known_servers_sorted:
            server_url = server.get('url')
            if server_url:
                servers.append({
                    'url': server_url,
                    'priority': 0,
                    'last_seen': server.get('last_seen', ''),
                    'source': 'discovered'
                })
                seen_urls.add(server_url)
    
    # Luego agregar servidor principal si no está ya en la lista
    if SERVER_URL and SERVER_URL not in seen_urls:
        servers.append({
            'url': SERVER_URL,
            'priority': 0,
            'source': 'configured'
        })
    
    return servers

def find_available_server(servers_list=None):
    """
    Intenta encontrar un servidor disponible de la lista.
    Retorna la URL del servidor disponible o None.
    Incrementa timeout_count en caso de fallo y elimina servidores con 10+ timeouts.
    """
    if servers_list is None:
        servers_list = get_available_servers()
    
    servers_list.sort(key=lambda x: (x.get('priority', 1), x.get('last_seen', ''), ''), reverse=True)
    
    failed_servers = []
    
    for server in servers_list:
        server_url = server.get('url')
        if not server_url:
            continue
        
        try:
            response = requests.get(f"{server_url}/api/health", timeout=3)
            if response.status_code == 200:
                if REGISTRY_AVAILABLE:
                    reset_server_timeout_count(server_url)
                return server_url
            else:
                failed_servers.append(server_url)
        except Exception:
            failed_servers.append(server_url)
    
    if REGISTRY_AVAILABLE and failed_servers:
        increment_server_timeouts(failed_servers)
    
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
        
        # Obtener IP local y puerto de diagnóstico para notificaciones push
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            client_ip = s.getsockname()[0]
            s.close()
            register_data['client_ip'] = client_ip
            register_data['diagnostic_port'] = 5002  # Puerto del servidor de diagnóstico
        except:
            # Si no se puede obtener IP, continuar sin ella
            pass
        
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
                    pass  # Sesión activa incluida en registro
            
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
            print("[Registro] No hay servidores disponibles para registrar el cliente")
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
            
            # Merge lista de servidores conocidos (NO reemplazar, para no perder descubiertos por broadcast)
            if REGISTRY_AVAILABLE and known_servers:
                current_servers = get_servers_from_registry()
                current_urls = {s.get('url') for s in current_servers}
                for server in known_servers:
                    srv_url = server.get('url')
                    if srv_url and srv_url not in current_urls:
                        server.setdefault('timeout_count', 0)
                        server.setdefault('last_seen', datetime.now().isoformat())
                        current_servers.append(server)
                    elif srv_url:
                        # Actualizar last_seen del existente
                        for s in current_servers:
                            if s.get('url') == srv_url:
                                s['last_seen'] = datetime.now().isoformat()
                                s['timeout_count'] = 0
                                break
                save_servers_to_registry(current_servers)
            
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
            
            print(f"[Registro] Cliente {'re-' if existing_client_id else ''}registrado: {client_id[:8]}...")
            
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
        
        if 'max_server_timeouts' in server_config:
            new_max = server_config['max_server_timeouts']
            if isinstance(new_max, int) and new_max > 0:
                old_max = current_config.get('max_server_timeouts', 10)
                if new_max != old_max:
                    print(f"[Config] Reintentos máx. antes de eliminar servidor: {old_max} -> {new_max}")
                    current_config['max_server_timeouts'] = new_max
        
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
            return True
        else:
            return False
    except requests.exceptions.RequestException:
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

def sync_with_all_servers(client_id):
    """
    Sincroniza con TODOS los servidores conocidos.
    Esto permite que todos los servidores conozcan a todos los clientes y servidores.
    """
    global last_known_remaining  # Declarar al inicio de la función
    
    # Obtener lista de servidores disponibles
    servers_list = get_available_servers()
    
    if not servers_list:
        return False
    
    # Obtener lista de servidores conocidos para enviar a cada servidor
    known_servers = []
    if REGISTRY_AVAILABLE:
        known_servers = get_servers_from_registry()
    
    success_count = 0
    failed_servers = []
    
    # Incrementar contadores de timeouts para servidores que fallaron al final
    def increment_failed_servers():
        if REGISTRY_AVAILABLE and failed_servers:
            increment_server_timeouts(failed_servers)
    
    # Sincronizar con cada servidor disponible
    for server_info in servers_list:
        server_url = server_info.get('url')
        if not server_url:
            continue
        
        try:
            health_response = requests.get(f"{server_url}/api/health", timeout=3)
            if health_response.status_code != 200:
                failed_servers.append(server_url)
                continue
            
            # Obtener estado del cliente desde este servidor
            response = requests.get(
                f"{server_url}/api/client/{client_id}/status",
                timeout=10
            )
            
            if response.status_code == 404:
                new_client_id = register_new_client(existing_client_id=client_id)
                if new_client_id:
                    client_id = new_client_id
                    success_count += 1
                    if REGISTRY_AVAILABLE:
                        reset_server_timeout_count(server_url)
                else:
                    failed_servers.append(server_url)
                continue
            
            if response.status_code != 200:
                failed_servers.append(server_url)
                continue
            
            # Resetear contador de timeouts al tener éxito
            if REGISTRY_AVAILABLE:
                reset_server_timeout_count(server_url)
            
            # Procesar respuesta exitosa
            data = response.json()
            client_data = data.get('client', {})
            
            # Actualizar lista de servidores conocidos si el servidor la envía
            if 'known_servers' in data and REGISTRY_AVAILABLE:
                try:
                    from registry_manager import save_servers_to_registry
                    from datetime import datetime
                    received_servers = data.get('known_servers', [])
                    if received_servers:
                        # Actualizar last_seen para servidores existentes o agregar nuevos
                        current_servers = get_servers_from_registry()
                        current_urls = {s.get('url') for s in current_servers}
                        
                        for server in received_servers:
                            server_url_received = server.get('url')
                            if server_url_received:
                                if server_url_received in current_urls:
                                    # Actualizar last_seen y resetear timeout_count
                                    for s in current_servers:
                                        if s.get('url') == server_url_received:
                                            s['last_seen'] = datetime.now().isoformat()
                                            s['timeout_count'] = 0  # Resetear al recibir del servidor
                                            break
                                else:
                                    # Agregar nuevo servidor (con timeout_count inicializado en 0)
                                    current_servers.append({
                                        'url': server_url_received,
                                        'ip': server.get('ip'),
                                        'port': server.get('port', 5000),
                                        'last_seen': datetime.now().isoformat(),
                                        'timeout_count': 0
                                    })
                        
                        save_servers_to_registry(current_servers)
                except Exception:
                    pass
            
            # Aplicar configuración del servidor si está disponible
            server_config = client_data.get('config')
            if server_config and REGISTRY_AVAILABLE:
                apply_server_config(server_config)
            
            session = client_data.get('session')
            
            if session:
                # Actualizar registro local con datos del servidor (solo del primer servidor exitoso)
                if success_count == 0:
                    time_limit = session.get('time_limit_seconds', 0)
                    start_time = session.get('start_time')
                    end_time = session.get('end_time')
                    remaining_from_server = session.get('remaining_seconds', 0)
                    
                    if all([time_limit, start_time, end_time]):
                        from datetime import datetime, timedelta
                        now_local = datetime.now()
                        end_time_local = now_local + timedelta(seconds=remaining_from_server)
                        elapsed_seconds = time_limit - remaining_from_server
                        start_time_local = now_local - timedelta(seconds=elapsed_seconds)
                        
                        if REGISTRY_AVAILABLE:
                            save_session_to_registry(
                                time_limit_seconds=time_limit,
                                start_time_iso=start_time_local.isoformat(),
                                end_time_iso=end_time_local.isoformat()
                            )
                            last_known_remaining = remaining_from_server
            
            # Enviar lista de servidores conocidos a este servidor para sincronización
            if known_servers:
                try:
                    sync_response = requests.post(
                        f"{server_url}/api/sync-servers",
                        json={
                            'servers': known_servers,
                            'clients': []  # El servidor ya tiene la lista de clientes
                        },
                        timeout=5
                    )
                    if sync_response.status_code == 200:
                        sync_data = sync_response.json()
                        updated_servers = sync_data.get('known_servers', [])
                        if updated_servers and REGISTRY_AVAILABLE:
                            save_servers_to_registry(updated_servers)
                except Exception:
                    pass
            
            success_count += 1
            
        except requests.exceptions.RequestException:
            failed_servers.append(server_url)
        except Exception:
            failed_servers.append(server_url)
    
    return client_id if success_count > 0 else False

def sync_with_server(client_id):
    """
    Sincroniza con TODOS los servidores conocidos.
    Mantiene compatibilidad con código existente (usado por sync_with_all_servers).
    NOTA: El SyncManager usa su propia lógica de sincronización con UN solo servidor.
    """
    return sync_with_all_servers(client_id)

class SyncManager:
    """
    Gestor de sincronización que corre en un hilo dedicado.
    Cada N segundos (sync_interval), busca UN servidor disponible y sincroniza con él.
    
    Responsabilidades:
    - Encontrar un servidor disponible
    - Obtener el estado del cliente desde el servidor
    - Actualizar el registro local con la sesión del servidor
    - Registrar/re-registrar el cliente si es necesario
    - Sincronizar lista de servidores conocidos
    - Aplicar configuración del servidor
    - Manejar fallos sin romper el cliente
    """
    
    def __init__(self, client_id, sync_interval):
        self._client_id = client_id
        self._sync_interval = sync_interval
        self._client_registered = False
        self._consecutive_failures = 0
        self._last_successful_server = None
        self._running = True
        self._thread = None
        self._lock = threading.Lock()
    
    @property
    def client_id(self):
        """Client ID (thread-safe read)."""
        with self._lock:
            return self._client_id
    
    @client_id.setter
    def client_id(self, value):
        """Update client ID (thread-safe write)."""
        with self._lock:
            self._client_id = value
    
    @property
    def client_registered(self):
        with self._lock:
            return self._client_registered
    
    @property
    def consecutive_failures(self):
        with self._lock:
            return self._consecutive_failures
    
    @property
    def last_successful_server(self):
        with self._lock:
            return self._last_successful_server
    
    def start(self):
        """Inicia el hilo de sincronización."""
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        print(f"[SyncManager] Hilo de sincronización iniciado (intervalo: {self._sync_interval}s)")
    
    def stop(self):
        """Señala al hilo de sincronización que se detenga."""
        self._running = False
    
    def _sync_loop(self):
        """Loop principal del hilo de sincronización."""
        # Primera sincronización inmediata al arrancar
        self._do_sync()
        
        while self._running:
            # Dormir en intervalos cortos para poder responder al stop rápido
            for _ in range(int(self._sync_interval)):
                if not self._running:
                    return
                time.sleep(1)
            
            self._do_sync()
    
    def _do_sync(self):
        """Realiza un ciclo de sincronización con TODOS los servidores disponibles."""
        try:
            client_id = self.client_id
            
            # Obtener lista de servidores conocidos
            servers_list = get_available_servers()
            
            if not servers_list:
                with self._lock:
                    self._consecutive_failures += 1
                if self._consecutive_failures == 1:
                    print("[SyncManager] No hay servidores conocidos. Esperando descubrimiento por broadcast...")
                elif self._consecutive_failures % 5 == 0:
                    print(f"[SyncManager] {self._consecutive_failures} ciclos sin servidores. Seguirá reintentando...")
                return
            
            # Log de servidores con los que se va a intentar sincronizar
            server_urls = [s.get('url', '?') for s in servers_list]
            print(f"[SyncManager] Sincronizando con {len(servers_list)} servidor(es): {', '.join(server_urls)}")
            
            # Intentar sincronizar con TODOS los servidores disponibles
            any_success = False
            all_failed = True
            
            for server_info in servers_list:
                server_url = server_info.get('url')
                if not server_url:
                    continue
                
                # Verificar si el servidor está disponible
                try:
                    health_response = requests.get(f"{server_url}/api/health", timeout=3)
                    if health_response.status_code != 200:
                        continue
                except requests.exceptions.RequestException:
                    continue
                
                all_failed = False
                
                # Sincronizar con este servidor
                success = self._sync_with_server(client_id, server_url)
                if success:
                    any_success = True
                    if REGISTRY_AVAILABLE:
                        reset_server_timeout_count(server_url)
                else:
                    if REGISTRY_AVAILABLE:
                        increment_server_timeouts([server_url])
            
            if all_failed:
                with self._lock:
                    self._consecutive_failures += 1
                if self._consecutive_failures == 1:
                    print(f"[SyncManager] Ningún servidor respondió. Reintentando en {self._sync_interval}s...")
                elif self._consecutive_failures % 5 == 0:
                    print(f"[SyncManager] {self._consecutive_failures} intentos fallidos consecutivos.")
                
                # Si el cliente no se ha registrado aún, intentar registrarlo
                if not self._client_registered:
                    self._try_register(client_id)
                return
            
            success = any_success
            
            if success:
                with self._lock:
                    self._consecutive_failures = 0
                    self._last_successful_server = server_url
                    self._client_registered = True
            else:
                with self._lock:
                    self._consecutive_failures += 1
        
        except Exception as e:
            with self._lock:
                self._consecutive_failures += 1
            print(f"[SyncManager] Error durante sincronización: {e}")
            if self._consecutive_failures % 5 == 0:
                print(f"[SyncManager] {self._consecutive_failures} intentos fallidos. El cliente sigue funcionando offline.")
    
    def _try_register(self, client_id):
        """Intenta registrar el cliente con algún servidor disponible."""
        try:
            print(f"[SyncManager] Cliente aún no registrado. Intentando registrar...")
            new_id = register_new_client(existing_client_id=client_id)
            if new_id:
                self.client_id = new_id
                with self._lock:
                    self._client_registered = True
                    self._consecutive_failures = 0
                print(f"[SyncManager] ✅ Cliente registrado exitosamente: {new_id}")
        except Exception as e:
            print(f"[SyncManager] Error al intentar registrar: {e}")
    
    def _sync_with_server(self, client_id, server_url):
        """
        Sincroniza con UN servidor específico.
        El cliente es la fuente de verdad: REPORTA su sesión al server.
        Los servers son pasivos y solo almacenan lo que el cliente les informa.
        Retorna True si la sincronización fue exitosa.
        """
        try:
            # Verificar si el cliente existe en este servidor
            response = requests.get(
                f"{server_url}/api/client/{client_id}/status",
                timeout=10
            )
            
            if response.status_code == 404:
                # Cliente no encontrado en ESTE servidor - registrar directamente
                print(f"[SyncManager] Registrando en {server_url}...")
                registered = self._register_on_server(client_id, server_url)
                if registered:
                    print(f"[SyncManager] Registrado en {server_url}")
                    if REGISTRY_AVAILABLE:
                        reset_server_timeout_count(server_url)
                    return True
                else:
                    print(f"[SyncManager] Error al registrar en {server_url}")
                    return False
            
            if response.status_code != 200:
                print(f"[SyncManager] Error {response.status_code} desde {server_url}")
                if REGISTRY_AVAILABLE:
                    increment_server_timeouts([server_url])
                return False
            
            if REGISTRY_AVAILABLE:
                reset_server_timeout_count(server_url)
            
            data = response.json()
            
            # Actualizar lista de servidores conocidos si el servidor la envía
            if 'known_servers' in data and REGISTRY_AVAILABLE:
                self._update_servers_from_response(data, server_url)
            
            # REPORTAR el estado local al servidor (el cliente es la fuente de verdad)
            self._report_state_to_server(client_id, server_url)
            
            # Enviar lista de servidores conocidos al servidor
            if REGISTRY_AVAILABLE:
                known_servers = get_servers_from_registry()
                if known_servers:
                    self._send_servers_to_server(known_servers, server_url)
            
            return True
        
        except requests.exceptions.RequestException as e:
            print(f"[SyncManager] Error de conexión con {server_url}: {e}")
            if REGISTRY_AVAILABLE:
                increment_server_timeouts([server_url])
            return False
        except Exception as e:
            print(f"[SyncManager] Error inesperado con {server_url}: {e}")
            return False
    
    def _report_state_to_server(self, client_id, server_url):
        """
        Reporta el estado actual del cliente al servidor.
        Incluye sesión, configuración y nombre.
        El cliente es la fuente de verdad.
        """
        if not REGISTRY_AVAILABLE:
            return
        
        # Reportar sesión actual (o limpiarla si no hay sesión activa)
        session_info = get_session_info()
        if session_info and not session_info['is_expired'] and session_info['remaining_seconds'] > 0:
            report_session_to_server(client_id, server_url=server_url)
        else:
            # Informar al server que no hay sesión activa
            try:
                requests.post(
                    f"{server_url}/api/client/{client_id}/report-session",
                    json={'remaining_seconds': 0, 'time_limit_seconds': 0},
                    timeout=5
                )
            except:
                pass
        
        # Reportar configuración y nombre
        try:
            config_data = get_config_from_registry()
            if config_data:
                config_payload = {}
                if config_data.get('custom_name'):
                    config_payload['custom_name'] = config_data['custom_name']
                if config_data.get('sync_interval'):
                    config_payload['sync_interval'] = config_data['sync_interval']
                if config_data.get('alert_thresholds'):
                    config_payload['alert_thresholds'] = config_data['alert_thresholds']
                if config_data.get('max_server_timeouts'):
                    config_payload['max_server_timeouts'] = config_data['max_server_timeouts']
                
                if config_payload:
                    config_payload['from_client'] = True
                    requests.post(
                        f"{server_url}/api/client/{client_id}/config",
                        json=config_payload,
                        timeout=5
                    )
        except Exception:
            pass
    
    def _register_on_server(self, client_id, server_url):
        """
        Registra el cliente directamente en un servidor específico.
        A diferencia de register_new_client() que elige cualquier servidor disponible,
        este método siempre registra en el server_url indicado.
        """
        try:
            import socket as sock_mod
            client_name = sock_mod.gethostname()
            
            custom_name = None
            config_data = None
            if REGISTRY_AVAILABLE:
                config_data = get_config_from_registry()
                if config_data:
                    custom_name = config_data.get('custom_name')
            
            register_data = {
                'name': custom_name if custom_name else client_name,
                'client_id': client_id
            }
            
            # Obtener IP local y puerto de diagnóstico
            try:
                s = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                client_ip = s.getsockname()[0]
                s.close()
                register_data['client_ip'] = client_ip
                register_data['diagnostic_port'] = 5002
            except:
                pass
            
            # Incluir sesión activa si existe
            if REGISTRY_AVAILABLE:
                session_info = get_session_info()
                if session_info and not session_info['is_expired'] and session_info['remaining_seconds'] > 0:
                    session_data = get_session_from_registry()
                    if session_data:
                        register_data['session'] = {
                            'remaining_seconds': session_info['remaining_seconds'],
                            'time_limit_seconds': session_data.get('time_limit_seconds', session_info['remaining_seconds'])
                        }
                
                # Incluir configuración
                if config_data:
                    register_data['config'] = {
                        'sync_interval': config_data.get('sync_interval', 30),
                        'alert_thresholds': config_data.get('alert_thresholds', [600, 300, 120, 60]),
                        'custom_name': custom_name
                    }
                
                # Incluir servidores conocidos
                known_servers = get_servers_from_registry()
                register_data['known_servers'] = known_servers
            
            response = requests.post(
                f"{server_url}/api/register",
                json=register_data,
                timeout=10
            )
            
            if response.status_code == 201:
                data = response.json()
                known_servers_resp = data.get('known_servers', [])
                
                # Merge servidores (NO reemplazar, para no perder descubiertos por broadcast)
                if REGISTRY_AVAILABLE and known_servers_resp:
                    current_servers = get_servers_from_registry()
                    current_urls = {s.get('url') for s in current_servers}
                    for srv in known_servers_resp:
                        srv_url = srv.get('url')
                        if srv_url and srv_url not in current_urls:
                            srv.setdefault('timeout_count', 0)
                            srv.setdefault('last_seen', datetime.now().isoformat())
                            current_servers.append(srv)
                        elif srv_url:
                            for s in current_servers:
                                if s.get('url') == srv_url:
                                    s['last_seen'] = datetime.now().isoformat()
                                    s['timeout_count'] = 0
                                    break
                    save_servers_to_registry(current_servers)
                
                print(f"[SyncManager] Cliente registrado en {server_url}")
                return True
            else:
                print(f"[SyncManager] Error al registrar en {server_url}: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"[SyncManager] Error de conexión al registrar en {server_url}: {e}")
            return False
        except Exception as e:
            print(f"[SyncManager] Error inesperado al registrar en {server_url}: {e}")
            return False
    
    def _update_servers_from_response(self, data, server_url):
        """Actualiza la lista de servidores conocidos desde la respuesta del servidor."""
        try:
            received_servers = data.get('known_servers', [])
            if not received_servers:
                return
            
            current_servers = get_servers_from_registry()
            current_urls = {s.get('url') for s in current_servers}
            
            for server in received_servers:
                server_url_received = server.get('url')
                if not server_url_received:
                    continue
                
                if server_url_received in current_urls:
                    # Actualizar last_seen y resetear timeout_count
                    for s in current_servers:
                        if s.get('url') == server_url_received:
                            s['last_seen'] = datetime.now().isoformat()
                            s['timeout_count'] = 0
                            break
                else:
                    # Agregar nuevo servidor
                    current_servers.append({
                        'url': server_url_received,
                        'ip': server.get('ip'),
                        'port': server.get('port', 5000),
                        'last_seen': datetime.now().isoformat(),
                        'timeout_count': 0
                    })
            
            save_servers_to_registry(current_servers)
            print(f"[SyncManager] ✅ Lista de servidores actualizada desde {server_url}")
        except Exception as e:
            print(f"[SyncManager] ⚠️  Error al actualizar servidores: {e}")
    
    def _update_session_from_server(self, session, server_url):
        """Actualiza la sesión local desde los datos del servidor."""
        global last_known_remaining
        
        time_limit = session.get('time_limit_seconds', 0)
        start_time = session.get('start_time')
        end_time = session.get('end_time')
        remaining_from_server = session.get('remaining_seconds', 0)
        
        if not all([time_limit, start_time, end_time]):
            print(f"[SyncManager] ⚠️  Datos de sesión incompletos desde {server_url}")
            return
        
        now_local = datetime.now()
        end_time_local = now_local + timedelta(seconds=remaining_from_server)
        elapsed_seconds = time_limit - remaining_from_server
        start_time_local = now_local - timedelta(seconds=elapsed_seconds)
        
        if REGISTRY_AVAILABLE:
            save_session_to_registry(
                time_limit_seconds=time_limit,
                start_time_iso=start_time_local.isoformat(),
                end_time_iso=end_time_local.isoformat()
            )
            
            # Detectar nueva sesión o cambio drástico para resetear alertas
            if last_known_remaining is None or abs(last_known_remaining - remaining_from_server) > 120:
                reset_alerts_for_new_session(remaining_from_server)
            
            last_known_remaining = remaining_from_server
            print(f"[SyncManager] ✅ Sesión actualizada desde {server_url}: {remaining_from_server}s restantes")
    
    def _handle_no_server_session(self, client_id, server_url):
        """Maneja el caso donde el servidor no tiene sesión para este cliente."""
        if not REGISTRY_AVAILABLE:
            return
        
        local_session = get_session_info()
        if local_session and not local_session['is_expired'] and local_session['remaining_seconds'] > 0:
            # El cliente tiene sesión válida - reportarla al servidor
            print(f"[SyncManager] Servidor sin sesión, reportando sesión local ({local_session['remaining_seconds']}s)...")
            report_session_to_server(client_id, server_url=server_url)
        else:
            # No hay sesión válida en ningún lado
            clear_session_from_registry()
    
    def _send_servers_to_server(self, known_servers, server_url):
        """Envía la lista de servidores conocidos al servidor para sincronización."""
        try:
            sync_response = requests.post(
                f"{server_url}/api/sync-servers",
                json={
                    'servers': known_servers
                },
                timeout=5
            )
            if sync_response.status_code == 200:
                sync_data = sync_response.json()
                updated_servers = sync_data.get('known_servers', [])
                if updated_servers and REGISTRY_AVAILABLE:
                    save_servers_to_registry(updated_servers)
        except Exception:
            pass


def start_server_discovery_listener():
    """
    Inicia un servidor UDP que escucha broadcasts de nuevos servidores.
    Cuando recibe un broadcast, registra el servidor automáticamente.
    """
    def listener_thread():
        # Puerto para recibir broadcasts de servidores
        DISCOVERY_PORT = 5001
        broadcast_count = 0
        last_broadcast_time = None
        
        try:
            # Crear socket UDP para escuchar broadcasts
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # En Windows, SO_REUSEADDR puede comportarse diferente
            # Intentar configurarlo, pero continuar si falla
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception as e:
                print(f"[Discovery] Advertencia: No se pudo configurar SO_REUSEADDR: {e}")
            
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # Intentar hacer bind al puerto
            try:
                sock.bind(('0.0.0.0', DISCOVERY_PORT))
                print(f"[Discovery] ✅ Socket vinculado correctamente a 0.0.0.0:{DISCOVERY_PORT}")
            except OSError as e:
                if e.errno == 10048 or "Address already in use" in str(e):
                    print(f"[Discovery] ❌ ERROR: El puerto {DISCOVERY_PORT} ya está en uso")
                    print(f"[Discovery] Posible causa: Otro proceso está usando el puerto o el listener anterior no se cerró")
                    print(f"[Discovery] Solución: Cierra otros procesos que usen el puerto {DISCOVERY_PORT} o reinicia el cliente")
                    return
                else:
                    raise
            
            sock.settimeout(1.0)  # Timeout para poder verificar si el thread debe continuar
            
            print(f"[Discovery] ✅ Escuchando broadcasts de servidores en puerto {DISCOVERY_PORT}...")
            print(f"[Discovery] ✅ El listener está activo y escuchando...")
            print(f"[Discovery] Esperando broadcasts UDP desde la red local...")
            
            # Marcar listener como iniciado
            global _discovery_stats
            _discovery_stats['listener_started'] = True
            
            # Log cada 30 segundos si no se reciben broadcasts
            last_status_log = time.time()
            
            known_server_urls = set()  # Para trackear qué servers ya conocemos
            
            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                    broadcast_count += 1
                    last_broadcast_time = time.time()
                    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Actualizar estadísticas globales (silencioso)
                    update_discovery_stats(
                        broadcast_count=broadcast_count,
                        last_broadcast_time=current_time_str,
                        last_broadcast_from=addr[0]
                    )
                    
                    try:
                        server_info = json.loads(data.decode('utf-8'))
                    except json.JSONDecodeError:
                        continue
                    
                    server_url = server_info.get('url')
                    server_ip = server_info.get('ip', addr[0])
                    server_port = server_info.get('port', 5000)
                    
                    if server_url:
                        update_discovery_stats(server_url=server_url)
                    
                    if server_url:
                        is_new = server_url not in known_server_urls
                        
                        # Registrar el servidor en nuestra lista
                        if REGISTRY_AVAILABLE:
                            known_servers = get_servers_from_registry()
                            
                            server_exists = False
                            for server in known_servers:
                                if server.get('url') == server_url:
                                    server['last_seen'] = datetime.now().isoformat()
                                    if server_ip:
                                        server['ip'] = server_ip
                                    if server_port:
                                        server['port'] = server_port
                                    save_servers_to_registry(known_servers)
                                    server_exists = True
                                    break
                            
                            if not server_exists:
                                known_servers.append({
                                    'url': server_url,
                                    'ip': server_ip,
                                    'port': server_port,
                                    'last_seen': datetime.now().isoformat()
                                })
                                save_servers_to_registry(known_servers)
                                print(f"[Discovery] Nuevo servidor registrado: {server_url}")
                        
                        # Solo loguear la primera vez que vemos este server
                        if is_new:
                            known_server_urls.add(server_url)
                            print(f"[Discovery] Servidor detectado: {server_url} ({server_ip}:{server_port})")
                            
                            # Confirmar con el servidor
                            try:
                                requests.post(
                                    f"{server_url}/api/register-server",
                                    json={'url': server_url, 'ip': server_ip, 'port': server_port},
                                    timeout=2
                                )
                            except Exception:
                                pass
                        
                except socket.timeout:
                    current_time = time.time()
                    if current_time - last_status_log >= 60:
                        if broadcast_count == 0:
                            print(f"[Discovery] Sin broadcasts recibidos aún")
                        last_status_log = current_time
                    continue
                except Exception as e:
                    print(f"[Discovery] Error: {e}")
                    continue
                    
        except OSError as e:
            if e.errno == 10048 or "Address already in use" in str(e):
                print(f"[Discovery] ❌ ERROR CRÍTICO: El puerto {DISCOVERY_PORT} ya está en uso")
                print(f"[Discovery] El listener no puede iniciarse porque otro proceso está usando el puerto")
                print(f"[Discovery] Esto impedirá que el cliente reciba broadcasts de servidores")
                print(f"[Discovery] Solución: Cierra otros procesos o reinicia el cliente")
            else:
                print(f"[Discovery] ❌ Error en listener (OSError): {e}")
                import traceback
                traceback.print_exc()
            # Reintentar después de un delay más largo para errores críticos
            time.sleep(10)
            start_server_discovery_listener()
        except Exception as e:
            print(f"[Discovery] ❌ Error en listener: {e}")
            import traceback
            traceback.print_exc()
            # Reintentar después de un delay
            time.sleep(5)
            start_server_discovery_listener()
    
    # Iniciar thread en background
    thread = threading.Thread(target=listener_thread, daemon=True)
    thread.start()
    print(f"[Discovery] Thread de descubrimiento iniciado (daemon={thread.daemon})")

# Variables globales para el servidor de diagnóstico
_diagnostic_server = None
_discovery_stats = {
    'broadcast_count': 0,
    'last_broadcast_time': None,
    'last_broadcast_from': None,
    'servers_discovered': set(),
    'listener_started': False
}

class DiagnosticHandler(BaseHTTPRequestHandler):
    """Handler HTTP para endpoints de diagnóstico del cliente"""
    
    def log_message(self, format, *args):
        """Suprimir logs del servidor HTTP"""
        pass
    
    def do_GET(self):
        """Handle GET requests"""
        path = self.path.split('?')[0]
        
        if path == '/api/diagnostic':
            self._send_diagnostic_info()
        elif path == '/api/servers':
            self._send_servers_info()
        elif path == '/api/status':
            self._send_status_info()
        elif path == '/api/discovery':
            self._send_discovery_info()
        elif path == '/':
            self._send_html_dashboard()
        else:
            self._send_json({'error': 'Not found'}, 404)
    
    def do_POST(self):
        """Handle POST requests"""
        path = self.path.split('?')[0]
        
        if path == '/api/add-server':
            self._handle_add_server()
        elif path == '/api/push/session':
            self._handle_push_session()
        elif path == '/api/push/config':
            self._handle_push_config()
        elif path == '/api/push/stop':
            self._handle_push_stop()
        else:
            self._send_json({'error': 'Not found'}, 404)
    
    def _read_post_data(self):
        """Lee y parsea el body JSON de un POST request."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return None
        post_data = self.rfile.read(content_length)
        return json.loads(post_data.decode('utf-8'))
    
    def _handle_push_session(self):
        """
        Recibe una notificación push del server cuando el admin cambia el tiempo.
        El cliente actualiza su sesión local y luego propaga a todos los servers.
        """
        global last_known_remaining
        
        try:
            data = self._read_post_data()
            if not data:
                self._send_json({'success': False, 'message': 'No data'}, 400)
                return
            
            time_limit = data.get('time_limit_seconds', 0)
            remaining = data.get('remaining_seconds', 0)
            start_time_iso = data.get('start_time')
            end_time_iso = data.get('end_time')
            
            if not all([time_limit, remaining]):
                self._send_json({'success': False, 'message': 'Datos incompletos'}, 400)
                return
            
            # Calcular tiempos locales basados en remaining
            now_local = datetime.now()
            end_time_local = now_local + timedelta(seconds=remaining)
            elapsed_seconds = time_limit - remaining
            start_time_local = now_local - timedelta(seconds=elapsed_seconds)
            
            if REGISTRY_AVAILABLE:
                save_session_to_registry(
                    time_limit_seconds=time_limit,
                    start_time_iso=start_time_local.isoformat(),
                    end_time_iso=end_time_local.isoformat()
                )
                
                # Resetear alertas para la nueva sesión
                reset_alerts_for_new_session(remaining)
                last_known_remaining = remaining
            
            print(f"[Push] Sesión recibida del servidor: {remaining}s restantes ({time_limit}s total)")
            
            # Propagar a todos los servers en background
            self._trigger_propagation()
            
            self._send_json({'success': True, 'message': f'Sesión actualizada: {remaining}s restantes'})
            
        except json.JSONDecodeError:
            self._send_json({'success': False, 'message': 'Invalid JSON'}, 400)
        except Exception as e:
            print(f"[Push] Error al procesar push de sesión: {e}")
            import traceback
            traceback.print_exc()
            self._send_json({'success': False, 'message': str(e)}, 500)
    
    def _handle_push_config(self):
        """
        Recibe una notificación push del server cuando el admin cambia la configuración.
        """
        try:
            data = self._read_post_data()
            if not data:
                self._send_json({'success': False, 'message': 'No data'}, 400)
                return
            
            if REGISTRY_AVAILABLE:
                apply_server_config(data)
            
            print(f"[Push] Configuración recibida del servidor: {data}")
            
            # Propagar a todos los servers en background
            self._trigger_propagation()
            
            self._send_json({'success': True, 'message': 'Configuración actualizada'})
            
        except json.JSONDecodeError:
            self._send_json({'success': False, 'message': 'Invalid JSON'}, 400)
        except Exception as e:
            print(f"[Push] Error al procesar push de config: {e}")
            self._send_json({'success': False, 'message': str(e)}, 500)
    
    def _handle_push_stop(self):
        """
        Recibe una notificación push del server cuando el admin detiene la sesión.
        """
        try:
            if REGISTRY_AVAILABLE:
                clear_session_from_registry()
            
            print(f"[Push] Sesión detenida por el servidor")
            
            # Propagar a todos los servers en background
            self._trigger_propagation()
            
            self._send_json({'success': True, 'message': 'Sesión detenida'})
            
        except Exception as e:
            print(f"[Push] Error al procesar push de stop: {e}")
            self._send_json({'success': False, 'message': str(e)}, 500)
    
    def _trigger_propagation(self):
        """
        Lanza en background la propagación del estado actual del cliente a todos los servers.
        Esto se ejecuta después de recibir un push del server, para que todos los demás
        servers se enteren del cambio.
        """
        import threading
        
        def _propagate():
            try:
                if not REGISTRY_AVAILABLE:
                    return
                
                client_id = get_client_id()
                if not client_id:
                    return
                
                servers_list = get_available_servers()
                if not servers_list:
                    return
                
                session_info = get_session_info()
                
                for server_info in servers_list:
                    server_url = server_info.get('url')
                    if not server_url:
                        continue
                    
                    try:
                        # Verificar que el server está vivo
                        health = requests.get(f"{server_url}/api/health", timeout=3)
                        if health.status_code != 200:
                            continue
                        
                        if session_info and not session_info['is_expired'] and session_info['remaining_seconds'] > 0:
                            # Reportar sesión activa
                            report_session_to_server(client_id, server_url=server_url)
                        else:
                            # Reportar que la sesión fue detenida
                            # Usar report-session con remaining=0 para limpiar en el server
                            # sin disparar el flujo de admin (stop) que volvería a notificar
                            try:
                                requests.post(
                                    f"{server_url}/api/client/{client_id}/report-session",
                                    json={'remaining_seconds': 0, 'time_limit_seconds': 0},
                                    timeout=5
                                )
                            except:
                                pass
                        
                    except Exception:
                        pass
            except Exception:
                pass
        
        threading.Thread(target=_propagate, daemon=True).start()
    
    def _handle_add_server(self):
        """Maneja la notificación de un nuevo servidor desde el servidor principal"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self._send_json({'success': False, 'message': 'No data provided'}, 400)
                return
            
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            server_url = data.get('url')
            server_ip = data.get('ip')
            server_port = data.get('port', 5000)
            
            if not server_url:
                self._send_json({'success': False, 'message': 'Server URL required'}, 400)
                return
            
            # Agregar servidor a la lista de servidores conocidos
            if REGISTRY_AVAILABLE:
                try:
                    from registry_manager import get_servers_from_registry, save_servers_to_registry
                    from datetime import datetime
                    
                    known_servers = get_servers_from_registry()
                    current_urls = {s.get('url') for s in known_servers}
                    
                    if server_url not in current_urls:
                        # Agregar nuevo servidor
                        known_servers.append({
                            'url': server_url,
                            'ip': server_ip,
                            'port': server_port,
                            'last_seen': datetime.now().isoformat(),
                            'timeout_count': 0
                        })
                        save_servers_to_registry(known_servers)
                        print(f"[Notificación] Nuevo servidor agregado: {server_url}")
                        self._send_json({'success': True, 'message': f'Servidor {server_url} agregado exitosamente'})
                    else:
                        # Actualizar servidor existente (silencioso)
                        for s in known_servers:
                            if s.get('url') == server_url:
                                s['last_seen'] = datetime.now().isoformat()
                                s['timeout_count'] = 0
                                if server_ip:
                                    s['ip'] = server_ip
                                if server_port:
                                    s['port'] = server_port
                                break
                        save_servers_to_registry(known_servers)
                        self._send_json({'success': True, 'message': f'Servidor {server_url} actualizado'})
                except Exception as e:
                    print(f"[Notificación] ❌ Error al agregar servidor: {e}")
                    import traceback
                    traceback.print_exc()
                    self._send_json({'success': False, 'message': str(e)}, 500)
            else:
                self._send_json({'success': False, 'message': 'Registry not available'}, 500)
                
        except json.JSONDecodeError:
            self._send_json({'success': False, 'message': 'Invalid JSON'}, 400)
        except Exception as e:
            print(f"[Notificación] ❌ Error al procesar notificación: {e}")
            import traceback
            traceback.print_exc()
            self._send_json({'success': False, 'message': str(e)}, 500)
    
    def _send_json(self, data, status=200):
        """Envía respuesta JSON"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))
    
    def _send_html_dashboard(self):
        """Envía dashboard HTML de diagnóstico"""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>CiberMonday - Diagnóstico del Cliente</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .card { background: white; padding: 20px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #333; }
        h2 { color: #667eea; border-bottom: 2px solid #667eea; padding-bottom: 5px; }
        .status { padding: 5px 10px; border-radius: 3px; display: inline-block; }
        .status.ok { background: #4CAF50; color: white; }
        .status.error { background: #f44336; color: white; }
        .status.warning { background: #ff9800; color: white; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f5f5f5; }
        .refresh-btn { background: #667eea; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; }
        .refresh-btn:hover { background: #5568d3; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🖥️ CiberMonday - Diagnóstico del Cliente</h1>
        <button class="refresh-btn" onclick="location.reload()">🔄 Actualizar</button>
        
        <div class="card">
            <h2>Estado General</h2>
            <div id="status-info">Cargando...</div>
        </div>
        
        <div class="card">
            <h2>Descubrimiento de Servidores</h2>
            <div id="discovery-info">Cargando...</div>
        </div>
        
        <div class="card">
            <h2>Servidores Conocidos</h2>
            <div id="servers-info">Cargando...</div>
        </div>
        
        <div class="card">
            <h2>Información Completa</h2>
            <pre id="full-info">Cargando...</pre>
        </div>
    </div>
    
    <script>
        async function loadData() {
            try {
                const [status, discovery, servers, diagnostic] = await Promise.all([
                    fetch('/api/status').then(r => r.json()),
                    fetch('/api/discovery').then(r => r.json()),
                    fetch('/api/servers').then(r => r.json()),
                    fetch('/api/diagnostic').then(r => r.json())
                ]);
                
                // Estado general
                document.getElementById('status-info').innerHTML = `
                    <p><strong>Cliente ID:</strong> ${status.client_id || 'N/A'}</p>
                    <p><strong>Servidor Principal:</strong> ${status.server_url || 'N/A'}</p>
                    <p><strong>Registro Disponible:</strong> <span class="status ${status.registry_available ? 'ok' : 'error'}">${status.registry_available ? 'Sí' : 'No'}</span></p>
                    <p><strong>Sesión Activa:</strong> <span class="status ${status.has_session ? 'ok' : 'warning'}">${status.has_session ? 'Sí' : 'No'}</span></p>
                    ${status.has_session ? `<p><strong>Tiempo Restante:</strong> ${status.remaining_seconds || 0} segundos</p>` : ''}
                `;
                
                // Descubrimiento
                document.getElementById('discovery-info').innerHTML = `
                    <p><strong>Listener Activo:</strong> <span class="status ${discovery.listener_active ? 'ok' : 'error'}">${discovery.listener_active ? 'Sí' : 'No'}</span></p>
                    <p><strong>Broadcasts Recibidos:</strong> ${discovery.broadcast_count || 0}</p>
                    <p><strong>Último Broadcast:</strong> ${discovery.last_broadcast_time || 'Nunca'}</p>
                    <p><strong>Desde:</strong> ${discovery.last_broadcast_from || 'N/A'}</p>
                    <p><strong>Servidores Descubiertos:</strong> ${discovery.servers_discovered_count || 0}</p>
                `;
                
                // Servidores conocidos
                if (servers.servers && servers.servers.length > 0) {
                    let table = '<table><tr><th>URL</th><th>IP</th><th>Puerto</th><th>Última Vez Visto</th><th>Estado</th></tr>';
                    servers.servers.forEach(server => {
                        const status = server.available ? '<span class="status ok">Disponible</span>' : '<span class="status error">No disponible</span>';
                        table += `<tr>
                            <td>${server.url}</td>
                            <td>${server.ip || 'N/A'}</td>
                            <td>${server.port || 'N/A'}</td>
                            <td>${server.last_seen || 'N/A'}</td>
                            <td>${status}</td>
                        </tr>`;
                    });
                    table += '</table>';
                    document.getElementById('servers-info').innerHTML = table;
                } else {
                    document.getElementById('servers-info').innerHTML = '<p>No hay servidores conocidos</p>';
                }
                
                // Información completa
                document.getElementById('full-info').textContent = JSON.stringify(diagnostic, null, 2);
            } catch (error) {
                console.error('Error:', error);
            }
        }
        
        loadData();
        setInterval(loadData, 5000); // Actualizar cada 5 segundos
    </script>
</body>
</html>"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def _send_diagnostic_info(self):
        """Envía información completa de diagnóstico"""
        global _discovery_stats
        
        # Obtener información del cliente
        client_id = None
        try:
            if REGISTRY_AVAILABLE:
                client_id = get_client_id_from_registry()
        except:
            pass
        
        # Obtener información de sesión
        session_info = None
        if REGISTRY_AVAILABLE:
            try:
                session_info = get_session_info()
            except:
                pass
        
        # Obtener servidores conocidos
        known_servers = []
        if REGISTRY_AVAILABLE:
            try:
                known_servers = get_servers_from_registry()
            except:
                pass
        
        # Probar disponibilidad de servidores
        for server in known_servers:
            server_url = server.get('url')
            if server_url:
                try:
                    response = requests.get(f"{server_url}/api/health", timeout=2)
                    server['available'] = response.status_code == 200
                except:
                    server['available'] = False
        
        self._send_json({
            'success': True,
            'client_id': client_id,
            'server_url': SERVER_URL,
            'registry_available': REGISTRY_AVAILABLE,
            'session': session_info,
            'known_servers': known_servers,
            'discovery': {
                'listener_active': _discovery_stats['listener_started'],
                'broadcast_count': _discovery_stats['broadcast_count'],
                'last_broadcast_time': _discovery_stats['last_broadcast_time'],
                'last_broadcast_from': _discovery_stats['last_broadcast_from'],
                'servers_discovered': list(_discovery_stats['servers_discovered'])
            }
        })
    
    def _send_status_info(self):
        """Envía información de estado del cliente"""
        client_id = None
        session_info = None
        
        if REGISTRY_AVAILABLE:
            try:
                client_id = get_client_id_from_registry()
                session_info = get_session_info()
            except:
                pass
        
        self._send_json({
            'success': True,
            'client_id': client_id,
            'server_url': SERVER_URL,
            'registry_available': REGISTRY_AVAILABLE,
            'has_session': session_info is not None and not session_info.get('is_expired', True),
            'remaining_seconds': session_info.get('remaining_seconds', 0) if session_info else 0
        })
    
    def _send_discovery_info(self):
        """Envía información sobre el descubrimiento de servidores"""
        global _discovery_stats
        self._send_json({
            'success': True,
            'listener_active': _discovery_stats['listener_started'],
            'broadcast_count': _discovery_stats['broadcast_count'],
            'last_broadcast_time': _discovery_stats['last_broadcast_time'],
            'last_broadcast_from': _discovery_stats['last_broadcast_from'],
            'servers_discovered_count': len(_discovery_stats['servers_discovered']),
            'servers_discovered': list(_discovery_stats['servers_discovered'])
        })
    
    def _send_servers_info(self):
        """Envía información sobre servidores conocidos"""
        known_servers = []
        if REGISTRY_AVAILABLE:
            try:
                known_servers = get_servers_from_registry()
                # Probar disponibilidad
                for server in known_servers:
                    server_url = server.get('url')
                    if server_url:
                        try:
                            response = requests.get(f"{server_url}/api/health", timeout=2)
                            server['available'] = response.status_code == 200
                        except:
                            server['available'] = False
            except:
                pass
        
        self._send_json({
            'success': True,
            'servers': known_servers,
            'count': len(known_servers)
        })

def start_diagnostic_server(port=5002):
    """Inicia el servidor HTTP de diagnóstico del cliente"""
    global _diagnostic_server
    
    def server_thread():
        try:
            # Escuchar en todas las interfaces (0.0.0.0) para permitir conexiones desde la red
            server = HTTPServer(('0.0.0.0', port), DiagnosticHandler)
            _diagnostic_server = server
            
            # Obtener IP local para mostrar en logs
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except:
                local_ip = "0.0.0.0"
            
            print(f"[Diagnóstico] Servidor de diagnóstico iniciado en http://{local_ip}:{port}")
            print(f"[Diagnóstico] Dashboard disponible en http://{local_ip}:{port}/")
            print(f"[Diagnóstico] Endpoints disponibles:")
            print(f"[Diagnóstico]   GET  /api/diagnostic - Información completa")
            print(f"[Diagnóstico]   GET  /api/status - Estado del cliente")
            print(f"[Diagnóstico]   GET  /api/discovery - Estado del descubrimiento")
            print(f"[Diagnóstico]   GET  /api/servers - Servidores conocidos")
            print(f"[Diagnóstico]   POST /api/add-server - Agregar servidor (notificación)")
            print(f"[Diagnóstico]   POST /api/push/session - Push de sesión desde server")
            print(f"[Diagnóstico]   POST /api/push/config - Push de config desde server")
            print(f"[Diagnóstico]   POST /api/push/stop - Push de stop desde server")
            server.serve_forever()
        except OSError as e:
            if e.errno == 10048 or "Address already in use" in str(e):
                print(f"[Diagnóstico] ⚠️  El puerto {port} ya está en uso. El servidor de diagnóstico no se iniciará.")
            else:
                print(f"[Diagnóstico] ❌ Error al iniciar servidor de diagnóstico: {e}")
        except Exception as e:
            print(f"[Diagnóstico] ❌ Error en servidor de diagnóstico: {e}")
    
    thread = threading.Thread(target=server_thread, daemon=True)
    thread.start()

def update_discovery_stats(broadcast_count=None, last_broadcast_time=None, last_broadcast_from=None, server_url=None):
    """Actualiza las estadísticas de descubrimiento"""
    global _discovery_stats
    if broadcast_count is not None:
        _discovery_stats['broadcast_count'] = broadcast_count
    if last_broadcast_time is not None:
        _discovery_stats['last_broadcast_time'] = last_broadcast_time
    if last_broadcast_from is not None:
        _discovery_stats['last_broadcast_from'] = last_broadcast_from
    if server_url is not None:
        _discovery_stats['servers_discovered'].add(server_url)

def monitor_time(client_id):
    """
    Monitorea el tiempo restante leyendo del registro local.
    La sincronización con el servidor corre en un hilo dedicado (SyncManager).
    Este loop principal solo lee del registro local y maneja el tiempo/bloqueo.
    """
    global alerts_shown  # Declarar al inicio de la función
    
    print("=" * 50)
    print("Cliente CiberMonday iniciado")
    print("=" * 50)
    print(f"ID del cliente: {client_id}")
    print(f"Servidor configurado: {SERVER_URL}")
    if REGISTRY_AVAILABLE:
        print("Modo: Registro local + sincronización en hilo dedicado")
    else:
        print("Modo: Consulta directa al servidor")
    print("Esperando asignación de tiempo...")
    print("=" * 50)
    
    # Verificar y agregar regla del firewall al iniciar si no existe
    try:
        from firewall_manager import check_firewall_rule, add_firewall_rule, is_admin
        
        print("\n[Firewall] Verificando configuración del firewall...")
        
        if not check_firewall_rule():
            print("[Firewall] ⚠️  La regla del firewall no está configurada")
            
            # Intentar agregar automáticamente si tenemos privilegios de administrador
            if is_admin():
                print("[Firewall] Intentando agregar regla automáticamente...")
                if add_firewall_rule():
                    print("[Firewall] ✅ Regla del firewall agregada exitosamente\n")
                else:
                    print("[Firewall] ❌ No se pudo agregar la regla automáticamente")
                    print("[Firewall] El cliente puede no recibir broadcasts UDP de servidores")
                    print("[Firewall] Para agregar manualmente, ejecuta como administrador:")
                    print("[Firewall]   python firewall_manager.py add\n")
            else:
                print("[Firewall] ⚠️  Se requieren privilegios de administrador para agregar la regla")
                print("[Firewall] El cliente puede no recibir broadcasts UDP de servidores")
                print("[Firewall] Para agregar la regla, ejecuta como administrador:")
                print("[Firewall]   python firewall_manager.py add")
                print("[Firewall] O desde PowerShell como administrador:")
                print("[Firewall]   netsh advfirewall firewall add rule name=\"CiberMonday Client UDP Discovery\" dir=in action=allow protocol=UDP localport=5001 enable=yes\n")
        else:
            print("[Firewall] ✅ Regla del firewall configurada correctamente\n")
    except ImportError:
        # firewall_manager no disponible, continuar sin verificar
        print("[Firewall] ⚠️  Módulo firewall_manager no disponible. No se puede verificar/configurar firewall.\n")
    except Exception as e:
        print(f"[Firewall] ⚠️  Error al verificar/configurar firewall: {e}")
        import traceback
        traceback.print_exc()
        print()
    
    # Iniciar listener de descubrimiento de servidores
    start_server_discovery_listener()
    
    # Iniciar servidor de diagnóstico
    start_diagnostic_server(port=5002)
    
    # Intervalo de sincronización desde configuración (o 30 por defecto)
    try:
        SYNC_INTERVAL = SYNC_INTERVAL_CONFIG
    except NameError:
        SYNC_INTERVAL = 30
    
    LOCAL_CHECK_INTERVAL = 1  # Verificar registro local cada segundo
    
    # Iniciar hilo de sincronización con SyncManager
    # El SyncManager se encarga de toda la comunicación con servidores
    sync_manager = SyncManager(client_id, SYNC_INTERVAL)
    sync_manager.start()
    
    last_remaining = None
    
    print(f"Intervalo de sincronización: {SYNC_INTERVAL} segundos")
    
    while True:
        try:
            # Leer el client_id más reciente del SyncManager
            # (puede cambiar si hubo re-registro)
            client_id = sync_manager.client_id
            
            # Leer del registro local
            if REGISTRY_AVAILABLE:
                session_info = get_session_info()
                
                if session_info is None:
                    # No hay sesión en registro - esperando a que el servidor asigne tiempo
                    if last_remaining is not None:
                        print("\rEsperando asignación de tiempo...", end='', flush=True)
                        # Si antes había sesión y ahora no, resetear alertas para próxima sesión
                        alerts_shown = {threshold: False for threshold in ALERT_THRESHOLDS}
                        last_remaining = None
                    time.sleep(LOCAL_CHECK_INTERVAL)
                    continue
                
                remaining_seconds = session_info['remaining_seconds']
                is_expired = session_info['is_expired']
                
                # Si es la primera vez que vemos esta sesión, inicializar alertas
                if last_remaining is None:
                    reset_alerts_for_new_session(remaining_seconds)
            else:
                # Fallback: consultar servidor directamente (sin registro disponible)
                client_data = check_server_status(client_id)
                if client_data is None:
                    time.sleep(CHECK_INTERVAL)
                    continue
                
                session = client_data.get('session')
                if session is None:
                    if last_remaining is not None:
                        print("\rEsperando asignación de tiempo...", end='', flush=True)
                        alerts_shown = {threshold: False for threshold in ALERT_THRESHOLDS}
                        last_remaining = None
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
                last_remaining = remaining_seconds
                
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
            sync_manager.stop()
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
    
    # Si solo se pidió configurar (--configure), la GUI ya se mostró al cargar el módulo
    # Solo salimos exitosamente
    if CONFIGURE_ONLY:
        print("[Config] Configuración completada. Saliendo...")
        sys.exit(0)
    
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
    # get_client_id() NUNCA retorna None - genera un ID local si no puede contactar servidores
    client_id = get_client_id()
    
    print(f"[Inicio] Cliente ID: {client_id}")
    
    # Iniciar monitoreo - el cliente siempre inicia aunque no haya servidores disponibles
    # Los servidores se descubrirán por broadcast o se reintentará la conexión periódicamente
    try:
        monitor_time(client_id)
    except Exception as e:
        print(f"Error fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
