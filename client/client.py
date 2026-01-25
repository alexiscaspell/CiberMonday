"""
Cliente CiberMonday - Control de tiempo de uso en Windows
Este script debe ejecutarse en la PC del cliente y se conecta al servidor
para recibir el tiempo asignado y bloquear la PC cuando expire.
"""

import requests
import time
import sys
import os
import json
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

# Importar notificaciones
try:
    from notifications import show_time_warning
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False

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
    Si el servidor no tiene sesión pero el cliente sí, envía la información local al servidor.
    """
    try:
        # Verificar si el cliente tiene una sesión activa local antes de consultar al servidor
        local_session_data = None
        if REGISTRY_AVAILABLE:
            local_session_data = get_session_from_registry()
            if local_session_data:
                # Verificar que la sesión local no haya expirado
                end_time_str = local_session_data.get('end_time')
                if end_time_str:
                    try:
                        from datetime import datetime
                        end_time = datetime.fromisoformat(end_time_str)
                        remaining = int((end_time - datetime.now()).total_seconds())
                        if remaining <= 0:
                            local_session_data = None  # Sesión expirada, no enviar
                    except:
                        local_session_data = None
        
        # Construir URL con información de sesión local si existe
        url = f"{SERVER_URL}/api/client/{client_id}/status"
        params = []
        
        if local_session_data:
            # Enviar información de sesión local al servidor para que la recupere
            import urllib.parse
            session_json = json.dumps({
                'time_limit_seconds': local_session_data.get('time_limit_seconds', 0),
                'start_time': local_session_data.get('start_time', ''),
                'end_time': local_session_data.get('end_time', '')
            })
            params.append(f"session_data={urllib.parse.quote(session_json)}")
        
        # Enviar configuración actual del cliente al servidor
        if REGISTRY_AVAILABLE:
            try:
                from registry_manager import get_config_from_registry
                client_config = get_config_from_registry()
                if client_config:
                    config_json = json.dumps({
                        'sync_interval': client_config.get('sync_interval', 30),
                        'local_check_interval': client_config.get('local_check_interval', 1),
                        'expired_sync_interval': client_config.get('expired_sync_interval', 2),
                        'lock_delay': client_config.get('lock_delay', 2),
                        'warning_thresholds': client_config.get('warning_thresholds', [10, 5, 2, 1])
                    })
                    params.append(f"client_config={urllib.parse.quote(config_json)}")
            except:
                pass
        
        if params:
            url += "?" + "&".join(params)
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 404:
            # Cliente no encontrado - intentar re-registrarse
            print(f"\n[Re-registro] Cliente no encontrado en el servidor. Intentando re-registrarse...")
            new_client_id = register_new_client()
            if new_client_id:
                print(f"[Re-registro] Cliente re-registrado exitosamente con nuevo ID: {new_client_id}")
                # Actualizar el client_id en el registro y archivo
                if REGISTRY_AVAILABLE:
                    save_client_id_to_registry(new_client_id)
                client_id_file_path = os.path.join(BASE_PATH, os.path.basename(CLIENT_ID_FILE))
                with open(client_id_file_path, 'w') as f:
                    f.write(new_client_id)
                # Retornar el nuevo ID para que se use en el loop principal
                return new_client_id
            else:
                print("[Re-registro] Error: No se pudo re-registrar el cliente")
                return False
        
        if response.status_code != 200:
            print(f"Error al obtener estado: {response.status_code}")
            return False
        
        data = response.json()
        client_data = data.get('client', {})
        
        # Verificar si el servidor tiene configuración actualizada para el cliente
        # El servidor solo envía server_config cuando hay cambios
        config_was_updated = False
        server_config = client_data.get('server_config')
        if server_config and REGISTRY_AVAILABLE:
            # El servidor detectó cambios, sincronizarlos
            try:
                from registry_manager import get_config_from_registry, save_config_to_registry
                current_config = get_config_from_registry() or {}
                
                # Actualizar solo los campos que el servidor envió
                config_updated = False
                for key in ['sync_interval', 'local_check_interval', 'expired_sync_interval', 
                           'lock_delay', 'warning_thresholds']:
                    if key in server_config:
                        old_value = current_config.get(key)
                        new_value = server_config[key]
                        current_config[key] = new_value
                        # Solo marcar como actualizado si realmente cambió
                        if old_value != new_value:
                            config_updated = True
                
                if config_updated:
                    # Guardar configuración actualizada
                    current_config['server_url'] = current_config.get('server_url', SERVER_URL)
                    save_config_to_registry(current_config)
                    print(f"[Configuración] Configuración sincronizada desde el servidor:")
                    for key in ['sync_interval', 'local_check_interval', 'expired_sync_interval', 
                               'lock_delay', 'warning_thresholds']:
                        if key in server_config:
                            print(f"  - {key}: {server_config[key]}")
                    config_was_updated = True
            except Exception as e:
                print(f"[Advertencia] Error al sincronizar configuración: {e}")
        
        session = client_data.get('session')
        
        if session is None:
            # Si el servidor no tiene sesión pero el cliente sí tenía una local,
            # el servidor debería haberla recuperado. Si aún no hay sesión, limpiar registro local.
            if REGISTRY_AVAILABLE:
                # Esperar un momento y verificar de nuevo si el servidor recuperó la sesión
                # (esto puede pasar si el servidor acaba de reiniciar y está procesando)
                if local_session_data:
                    print("[Sincronización] Servidor sin sesión, pero cliente tiene sesión local.")
                    print("  - La sesión local se mantendrá hasta la próxima sincronización.")
                    # No limpiar el registro local todavía, dar oportunidad al servidor
                    return False
                else:
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
        
        # Retornar indicador de configuración actualizada si hubo cambios
        if config_was_updated:
            return {'config_updated': True}
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión al sincronizar: {e}")
        return False
    except Exception as e:
        print(f"Error al sincronizar con servidor: {e}")
        import traceback
        traceback.print_exc()
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
    is_expired_state = False  # Rastrear si estamos en estado de tiempo expirado
    
    # Función para cargar configuración desde el registro
    def load_config():
        """Carga la configuración desde el registro"""
        config_data = None
        if REGISTRY_AVAILABLE:
            try:
                from registry_manager import get_config_from_registry
                config_data = get_config_from_registry()
            except:
                pass
        
        # Usar valores de configuración o valores por defecto
        try:
            sync_interval = SYNC_INTERVAL_CONFIG
        except NameError:
            sync_interval = config_data.get('sync_interval', 30) if config_data else 30
        
        local_check_interval = config_data.get('local_check_interval', 1) if config_data else 1
        expired_sync_interval = config_data.get('expired_sync_interval', 2) if config_data else 2
        lock_delay = config_data.get('lock_delay', 2) if config_data else 2
        warning_thresholds = config_data.get('warning_thresholds', [10, 5, 2, 1]) if config_data else [10, 5, 2, 1]
        
        return {
            'sync_interval': sync_interval,
            'local_check_interval': local_check_interval,
            'expired_sync_interval': expired_sync_interval,
            'lock_delay': lock_delay,
            'warning_thresholds': warning_thresholds
        }
    
    # Cargar configuración inicial
    config = load_config()
    SYNC_INTERVAL = config['sync_interval']
    LOCAL_CHECK_INTERVAL = config['local_check_interval']
    EXPIRED_SYNC_INTERVAL = config['expired_sync_interval']
    LOCK_DELAY = config['lock_delay']
    WARNING_THRESHOLDS = config['warning_thresholds']
    
    # Rastrear qué notificaciones de tiempo ya se han mostrado
    # Para evitar mostrar la misma notificación múltiples veces
    shown_warnings = set()  # Almacena los umbrales ya mostrados (en minutos)
    
    print(f"Intervalo de sincronización: {SYNC_INTERVAL} segundos")
    print(f"Intervalo de verificación local: {LOCAL_CHECK_INTERVAL} segundos")
    print(f"Intervalo de sincronización (expirado): {EXPIRED_SYNC_INTERVAL} segundos")
    print(f"Tiempo de espera antes de bloquear: {LOCK_DELAY} segundos")
    print(f"Umbrales de notificación: {WARNING_THRESHOLDS} minutos")
    
    while True:
        try:
            current_time = time.time()
            
            # Sincronizar con servidor periódicamente
            if current_time - last_sync_time >= SYNC_INTERVAL:
                sync_result = sync_with_server(client_id)
                # Verificar si la configuración fue actualizada
                if isinstance(sync_result, dict) and sync_result.get('config_updated'):
                    # La configuración fue actualizada, recargarla
                    new_config = load_config()
                    config_changed = False
                    
                    if new_config['sync_interval'] != SYNC_INTERVAL:
                        SYNC_INTERVAL = new_config['sync_interval']
                        config_changed = True
                    if new_config['local_check_interval'] != LOCAL_CHECK_INTERVAL:
                        LOCAL_CHECK_INTERVAL = new_config['local_check_interval']
                        config_changed = True
                    if new_config['expired_sync_interval'] != EXPIRED_SYNC_INTERVAL:
                        EXPIRED_SYNC_INTERVAL = new_config['expired_sync_interval']
                        config_changed = True
                    if new_config['lock_delay'] != LOCK_DELAY:
                        LOCK_DELAY = new_config['lock_delay']
                        config_changed = True
                    if new_config['warning_thresholds'] != WARNING_THRESHOLDS:
                        WARNING_THRESHOLDS = new_config['warning_thresholds']
                        # Limpiar notificaciones mostradas cuando cambian los umbrales
                        shown_warnings.clear()
                        config_changed = True
                        print(f"[Configuración] Umbrales de notificación actualizados: {WARNING_THRESHOLDS} minutos")
                    
                    if config_changed:
                        print(f"[Configuración] Configuración aplicada en memoria")
                # Si sync_with_server retorna un nuevo client_id (re-registro), actualizarlo
                elif sync_result and isinstance(sync_result, str):
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
                    # Usar EXPIRED_SYNC_INTERVAL también para cuando no hay sesión
                    if current_time - last_sync_time >= EXPIRED_SYNC_INTERVAL:
                        sync_result = sync_with_server(client_id)
                        # Verificar si la configuración fue actualizada
                        if isinstance(sync_result, dict) and sync_result.get('config_updated'):
                            new_config = load_config()
                            if new_config['sync_interval'] != SYNC_INTERVAL:
                                SYNC_INTERVAL = new_config['sync_interval']
                            if new_config['local_check_interval'] != LOCAL_CHECK_INTERVAL:
                                LOCAL_CHECK_INTERVAL = new_config['local_check_interval']
                            if new_config['expired_sync_interval'] != EXPIRED_SYNC_INTERVAL:
                                EXPIRED_SYNC_INTERVAL = new_config['expired_sync_interval']
                            if new_config['lock_delay'] != LOCK_DELAY:
                                LOCK_DELAY = new_config['lock_delay']
                            if new_config['warning_thresholds'] != WARNING_THRESHOLDS:
                                WARNING_THRESHOLDS = new_config['warning_thresholds']
                                shown_warnings.clear()
                        # Si sync_with_server retorna un nuevo client_id (re-registro), actualizarlo
                        elif sync_result and isinstance(sync_result, str):
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
                # Marcar que estamos en estado expirado
                if not is_expired_state:
                    is_expired_state = True
                    # Limpiar notificaciones mostradas cuando expira por primera vez
                    shown_warnings.clear()
                    print("\n" + "=" * 50)
                    print("¡TIEMPO AGOTADO!")
                    print("La PC se bloqueará continuamente hasta que se asigne nuevo tiempo.")
                    print("=" * 50)
                
                # IMPORTANTE: Sincronizar con el servidor frecuentemente cuando está expirado
                # para verificar si se asignó nuevo tiempo antes de bloquear
                if current_time - last_sync_time >= EXPIRED_SYNC_INTERVAL:
                    sync_result = sync_with_server(client_id)
                    # Verificar si la configuración fue actualizada
                    if isinstance(sync_result, dict) and sync_result.get('config_updated'):
                        new_config = load_config()
                        if new_config['expired_sync_interval'] != EXPIRED_SYNC_INTERVAL:
                            EXPIRED_SYNC_INTERVAL = new_config['expired_sync_interval']
                        if new_config['lock_delay'] != LOCK_DELAY:
                            LOCK_DELAY = new_config['lock_delay']
                        if new_config['warning_thresholds'] != WARNING_THRESHOLDS:
                            WARNING_THRESHOLDS = new_config['warning_thresholds']
                            shown_warnings.clear()
                    # Si sync_with_server retorna un nuevo client_id (re-registro), actualizarlo
                    elif sync_result and isinstance(sync_result, str):
                        # Se re-registró el cliente, actualizar ID
                        print(f"[Actualización] Usando nuevo Client ID: {sync_result}")
                        client_id = sync_result
                    
                    last_sync_time = current_time
                    
                    # Verificar si ahora hay sesión activa después de sincronizar
                    if REGISTRY_AVAILABLE:
                        session_info = get_session_info()
                        if session_info and session_info.get('remaining_seconds', 0) > 0:
                            # Hay nuevo tiempo asignado, salir del bloqueo
                            print("[Bloqueo] Se detectó nuevo tiempo asignado. Desbloqueando...")
                            is_expired_state = False
                            last_remaining = None  # Resetear para forzar actualización
                            continue  # Salir del bloqueo y continuar normalmente
                
                # Esperar antes de bloquear (configurable)
                time.sleep(LOCK_DELAY)
                
                # Bloquear la estación de trabajo
                lock_workstation()
                
                # Esperar antes de verificar de nuevo
                time.sleep(EXPIRED_SYNC_INTERVAL)
                continue
            else:
                # Si el tiempo NO está expirado pero estábamos en estado expirado,
                # significa que se asignó nuevo tiempo
                if is_expired_state:
                    print("[Bloqueo] Tiempo restaurado. Desbloqueando...")
                    is_expired_state = False
                    shown_warnings.clear()  # Limpiar notificaciones para nueva sesión
                    last_remaining = None  # Resetear para forzar actualización
            
            # Verificar si debemos mostrar notificaciones de tiempo restante
            remaining_minutes = remaining_seconds // 60
            
            # Verificar cada umbral de advertencia
            for threshold_minutes in WARNING_THRESHOLDS:
                # Mostrar notificación si:
                # 1. El tiempo restante está en el umbral (o justo pasó)
                # 2. No hemos mostrado esta notificación antes
                # 3. El tiempo restante es menor o igual al umbral
                if (remaining_minutes <= threshold_minutes and 
                    threshold_minutes not in shown_warnings):
                    # Mostrar notificación
                    if NOTIFICATIONS_AVAILABLE:
                        show_time_warning(threshold_minutes)
                    else:
                        print(f"\n{'='*50}")
                        print(f"ADVERTENCIA: Quedan {threshold_minutes} minutos")
                        print(f"{'='*50}\n")
                    
                    # Marcar como mostrado
                    shown_warnings.add(threshold_minutes)
            
            # Si el tiempo restante aumenta (nueva sesión asignada), limpiar notificaciones
            if last_remaining is not None and remaining_seconds > last_remaining:
                # Nueva sesión asignada, limpiar notificaciones mostradas
                shown_warnings.clear()
            
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
