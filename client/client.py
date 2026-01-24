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
    """
    try:
        response = requests.get(
            f"{SERVER_URL}/api/client/{client_id}/status",
            timeout=10
        )
        
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
        
        session = client_data.get('session')
        
        if session is None:
            # No hay sesión activa en el servidor, limpiar registro local
            if REGISTRY_AVAILABLE:
                clear_session_from_registry()
            return False
        
        # Verificar que los datos de sesión sean válidos
        time_limit = session.get('time_limit_seconds', 0)
        start_time = session.get('start_time')
        end_time = session.get('end_time')
        
        if not all([time_limit, start_time, end_time]):
            print("Advertencia: Datos de sesión incompletos del servidor")
            return False
        
        # CORRECCIÓN DE ZONA HORARIA:
        # En lugar de usar el end_time del servidor (que puede estar en UTC),
        # calcular el end_time correcto basándose en el tiempo actual del cliente + time_limit
        # Esto asegura que el cálculo del tiempo restante sea correcto independientemente de la zona horaria
        from datetime import datetime, timedelta
        now_local = datetime.now()
        
        # Calcular cuánto tiempo ha pasado desde que empezó la sesión en el servidor
        try:
            start_time_dt = datetime.fromisoformat(start_time)
            # Calcular el tiempo transcurrido desde el inicio de la sesión
            # Usar el remaining_seconds del servidor para saber cuánto tiempo queda
            remaining_from_server = session.get('remaining_seconds', 0)
            
            # Calcular el end_time correcto: ahora + tiempo restante del servidor
            # O alternativamente: ahora + (time_limit - tiempo ya transcurrido)
            correct_end_time = now_local + timedelta(seconds=remaining_from_server)
            
            # Usar el end_time corregido para guardar en el registro
            end_time_corrected = correct_end_time.isoformat()
            
            print(f"[Corrección Zona Horaria] End time servidor: {end_time}")
            print(f"[Corrección Zona Horaria] End time corregido (local): {end_time_corrected}")
            print(f"[Corrección Zona Horaria] Tiempo restante servidor: {remaining_from_server}s")
            
            end_time = end_time_corrected
        except Exception as e:
            print(f"[Advertencia] No se pudo corregir zona horaria, usando end_time del servidor: {e}")
        
        # Actualizar registro local con información del servidor
        if REGISTRY_AVAILABLE:
            # Limpiar sesión anterior antes de guardar nueva
            clear_session_from_registry()
            
            # Guardar nueva sesión con end_time corregido
            success = save_session_to_registry(
                time_limit,
                start_time,
                end_time
            )
            
            if success:
                # Verificar que se guardó correctamente leyendo del registro
                saved_session = get_session_from_registry()
                if saved_session:
                    saved_end_time = saved_session.get('end_time')
                    saved_time_limit = saved_session.get('time_limit_seconds')
                    
                    # Calcular tiempo restante desde el registro guardado
                    if saved_end_time:
                        try:
                            from datetime import datetime, timedelta
                            end_time_dt = datetime.fromisoformat(saved_end_time)
                            start_time_dt = datetime.fromisoformat(start_time) if start_time else None
                            now = datetime.now()
                            remaining_from_registry = int((end_time_dt - now).total_seconds())
                            
                            # Calcular tiempo restante corregido basándose en start_time + time_limit
                            remaining_corrected = None
                            if start_time_dt and time_limit > 0:
                                correct_end_time = start_time_dt + timedelta(seconds=time_limit)
                                remaining_corrected = int((correct_end_time - now).total_seconds())
                            
                            # Log para depuración
                            remaining = session.get('remaining_seconds', 0)
                            print(f"\n[Sincronización] Tiempo establecido: {time_limit}s ({time_limit//60} min)")
                            print(f"[Sincronización] Start time: {start_time}")
                            print(f"[Sincronización] End time (servidor): {end_time}")
                            print(f"[Sincronización] End time (guardado): {saved_end_time}")
                            print(f"[Sincronización] Hora actual (cliente): {now.isoformat()}")
                            print(f"[Sincronización] Restante (servidor): {remaining}s")
                            print(f"[Sincronización] Restante (registro, original): {remaining_from_registry}s")
                            if remaining_corrected is not None:
                                print(f"[Sincronización] Restante (registro, corregido): {remaining_corrected}s")
                            
                            # Si hay discrepancia grande, mostrar advertencia
                            if abs(remaining_from_registry - remaining) > 5:
                                print(f"[ADVERTENCIA] Discrepancia entre servidor y registro: {abs(remaining_from_registry - remaining)}s")
                                if remaining_corrected is not None and abs(remaining_corrected - remaining) < abs(remaining_from_registry - remaining):
                                    print(f"[INFO] Usando cálculo corregido basado en start_time + time_limit")
                        except Exception as e:
                            print(f"[Error] Al verificar registro guardado: {e}")
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
                    # No hay sesión en registro, intentar sincronizar inmediatamente
                    if current_time - last_sync_time >= 5:  # Esperar al menos 5 segundos
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
