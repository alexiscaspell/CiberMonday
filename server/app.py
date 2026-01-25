from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from datetime import datetime, timedelta
import uuid
import threading
import time
import os
import json
import socket

app = Flask(__name__, template_folder='templates')
CORS(app)

# Base de datos en memoria (en producción usarías una BD real)
clients_db = {}
client_sessions = {}

# Archivo para persistir datos del servidor
# En Docker, usar el directorio del volumen; en local, usar el directorio del servidor
if os.path.exists('/app/server_data'):
    # Ejecutándose en Docker
    DATA_DIR = '/app/server_data'
else:
    # Ejecutándose localmente
    DATA_DIR = os.path.dirname(__file__)

# Crear directorio si no existe
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, 'server_data.json')

def save_server_data():
    """Guarda los datos del servidor en un archivo JSON"""
    try:
        data = {
            'clients_db': clients_db,
            'client_sessions': client_sessions,
            'last_saved': datetime.now().isoformat()
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error al guardar datos del servidor: {e}")
        return False

def load_server_data():
    """Carga los datos del servidor desde un archivo JSON"""
    global clients_db, client_sessions
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                clients_db = data.get('clients_db', {})
                client_sessions = data.get('client_sessions', {})
                
                # Limpiar sesiones expiradas al cargar
                now = datetime.now()
                expired_sessions = []
                for client_id, session in client_sessions.items():
                    end_time = datetime.fromisoformat(session['end_time'])
                    if end_time < now:
                        expired_sessions.append(client_id)
                
                for client_id in expired_sessions:
                    del client_sessions[client_id]
                    if client_id in clients_db:
                        clients_db[client_id]['is_active'] = False
                
                print(f"Datos del servidor cargados: {len(clients_db)} clientes, {len(client_sessions)} sesiones activas")
                if expired_sessions:
                    print(f"  - {len(expired_sessions)} sesiones expiradas fueron limpiadas")
                return True
        else:
            print("No se encontró archivo de datos. Iniciando con base de datos vacía.")
            return False
    except Exception as e:
        print(f"Error al cargar datos del servidor: {e}")
        return False

def generate_client_id():
    """Genera un ID único para cada cliente"""
    return str(uuid.uuid4())

@app.route('/api/register', methods=['POST'])
def register_client():
    """Registra un nuevo cliente en el sistema"""
    data = request.json
    client_name = data.get('name', 'Cliente Sin Nombre')
    client_id = generate_client_id()
    
    clients_db[client_id] = {
        'id': client_id,
        'name': client_name,
        'registered_at': datetime.now().isoformat(),
        'total_time_used': 0,
        'is_active': False,
        'config': {}  # Configuración del cliente (se actualiza cuando el cliente sincroniza)
    }
    
    save_server_data()
    
    return jsonify({
        'success': True,
        'client_id': client_id,
        'message': 'Cliente registrado exitosamente'
    }), 201

@app.route('/api/clients', methods=['GET'])
def get_clients():
    """Obtiene la lista de todos los clientes registrados"""
    clients_list = []
    for client_id, client_data in clients_db.items():
        client_info = client_data.copy()
        if client_id in client_sessions:
            session = client_sessions[client_id]
            time_disabled = session.get('time_disabled', False)
            # Convertir end_time de string ISO a datetime para calcular remaining_seconds
            end_time = datetime.fromisoformat(session['end_time'])
            remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
            
            # Si el tiempo está deshabilitado, mantener remaining_seconds muy grande
            if time_disabled:
                remaining_seconds = max(remaining_seconds, 999999999)
            
            client_info['current_session'] = {
                'time_limit': session['time_limit'],
                'start_time': session['start_time'],
                'end_time': session['end_time'],
                'remaining_seconds': remaining_seconds,
                'time_disabled': time_disabled
            }
        clients_list.append(client_info)
    
    return jsonify({
        'success': True,
        'clients': clients_list
    }), 200

@app.route('/api/client/<client_id>/set-time', methods=['POST'])
def set_client_time(client_id):
    """Establece el tiempo de uso para un cliente específico"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    data = request.json
    time_value = data.get('time', 0)
    time_unit = data.get('unit', 'minutes')  # 'minutes' o 'hours'
    
    # Convertir a segundos
    if time_unit == 'hours':
        total_seconds = time_value * 3600
    else:
        total_seconds = time_value * 60
    
    if total_seconds <= 0:
        return jsonify({
            'success': False,
            'message': 'El tiempo debe ser mayor a 0'
        }), 400
    
    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=total_seconds)
    
    client_sessions[client_id] = {
        'time_limit': total_seconds,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat(),
        'time_disabled': False  # Asegurar que el tiempo está habilitado
    }
    
    clients_db[client_id]['is_active'] = True
    clients_db[client_id]['time_disabled'] = False  # Limpiar flag de tiempo deshabilitado
    save_server_data()
    
    return jsonify({
        'success': True,
        'message': f'Tiempo establecido: {time_value} {time_unit}',
        'session': {
            'time_limit_seconds': total_seconds,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'time_disabled': False
        }
    }), 200

@app.route('/api/client/<client_id>/config', methods=['GET'])
def get_client_config(client_id):
    """Obtiene la configuración actual del cliente"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    # La configuración del cliente se almacena en clients_db
    client_config = clients_db[client_id].get('config', {})
    
    return jsonify({
        'success': True,
        'config': client_config
    }), 200

@app.route('/api/client/<client_id>/config', methods=['POST'])
def update_client_config(client_id):
    """Actualiza la configuración del cliente desde el servidor"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    data = request.json
    if not data:
        return jsonify({
            'success': False,
            'message': 'No se proporcionaron datos de configuración'
        }), 400
    
    # Validar y actualizar configuración
    config = clients_db[client_id].get('config', {})
    
    # Actualizar solo los campos proporcionados
    if 'sync_interval' in data:
        sync_interval = int(data['sync_interval'])
        if 5 <= sync_interval <= 300:
            config['sync_interval'] = sync_interval
    
    if 'local_check_interval' in data:
        local_check = int(data['local_check_interval'])
        if 1 <= local_check <= 60:
            config['local_check_interval'] = local_check
    
    if 'expired_sync_interval' in data:
        expired_sync = int(data['expired_sync_interval'])
        if 1 <= expired_sync <= 60:
            config['expired_sync_interval'] = expired_sync
    
    if 'lock_delay' in data:
        lock_delay = int(data['lock_delay'])
        if 0 <= lock_delay <= 30:
            config['lock_delay'] = lock_delay
    
    if 'warning_thresholds' in data:
        thresholds = data['warning_thresholds']
        if isinstance(thresholds, list) and all(isinstance(t, int) and t > 0 for t in thresholds):
            config['warning_thresholds'] = sorted(thresholds, reverse=True)
    
    clients_db[client_id]['config'] = config
    save_server_data()
    
    return jsonify({
        'success': True,
        'message': 'Configuración actualizada',
        'config': config
    }), 200

@app.route('/api/client/<client_id>/status', methods=['GET'])
def get_client_status(client_id):
    """Obtiene el estado actual de un cliente"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    client_data = clients_db[client_id].copy()
    
    # PRIMERO: Verificar si el cliente está enviando su sesión local
    # Esto tiene prioridad sobre la sesión del servidor para asegurar que siempre tenemos la información más reciente
    client_session_data = request.args.get('session_data')
    if client_session_data:
        try:
            # El cliente puede enviar su información de sesión local como parámetro
            import urllib.parse
            session_info = json.loads(urllib.parse.unquote(client_session_data))
            
            # Recuperar sesión del cliente
            time_limit = session_info.get('time_limit_seconds', 0)
            end_time_str = session_info.get('end_time')
            start_time_str = session_info.get('start_time')
            
            if time_limit > 0 and end_time_str:
                end_time = datetime.fromisoformat(end_time_str)
                remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
                
                # Actualizar o crear la sesión en el servidor con la información del cliente
                time_disabled = session_info.get('time_disabled', False)
                client_sessions[client_id] = {
                    'time_limit': time_limit,
                    'start_time': start_time_str or datetime.now().isoformat(),
                    'end_time': end_time_str,
                    'time_disabled': time_disabled
                }
                # Actualizar flag en clients_db también
                clients_db[client_id]['time_disabled'] = time_disabled
                clients_db[client_id]['is_active'] = True
                save_server_data()
                
                print(f"[Recuperación] Sesión actualizada desde cliente {client_id}: {remaining_seconds}s restantes")
        except Exception as e:
            print(f"[Advertencia] Error al recuperar sesión del cliente: {e}")
    
    # Verificar si hay sesión en el servidor (ahora actualizada con la del cliente si la envió)
    if client_id in client_sessions:
        session = client_sessions[client_id]
        time_disabled = session.get('time_disabled', False)
        end_time = datetime.fromisoformat(session['end_time'])
        remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
        
        # Si el tiempo está deshabilitado, nunca considerar expirado
        if time_disabled:
            is_expired = False
            # Mantener remaining_seconds muy grande para que el cliente no bloquee
            remaining_seconds = max(remaining_seconds, 999999999)
        else:
            is_expired = remaining_seconds == 0
        
        # Si la sesión expiró (y no es tiempo deshabilitado), limpiarla
        if is_expired and not time_disabled:
            del client_sessions[client_id]
            clients_db[client_id]['is_active'] = False
            clients_db[client_id].pop('time_disabled', None)  # Limpiar flag si existe
            save_server_data()
            client_data['session'] = None
        else:
            client_data['session'] = {
                'time_limit_seconds': session['time_limit'],
                'start_time': session['start_time'],
                'end_time': session['end_time'],
                'remaining_seconds': remaining_seconds,
                'is_expired': is_expired,
                'time_disabled': time_disabled  # Incluir flag en la respuesta
            }
            # Actualizar flag en clients_db para referencia y marcar como activo
            clients_db[client_id]['time_disabled'] = time_disabled
            clients_db[client_id]['is_active'] = True
            save_server_data()
    else:
        # Si no hay sesión después de procesar la del cliente, establecer None
        if not client_data.get('session'):
            client_data['session'] = None
    
    # Verificar si se solicitó forzar sincronización (esto se hace siempre, tenga o no sesión)
    force_sync = clients_db[client_id].get('force_sync', False)
    
    # Obtener configuración del cliente si se envía (esto también se hace siempre)
    client_config_data = request.args.get('client_config')
    if client_config_data:
        try:
            import urllib.parse
            config_info = json.loads(urllib.parse.unquote(client_config_data))
            # Guardar configuración del cliente en el servidor
            clients_db[client_id]['config'] = config_info
            # Marcar cliente como activo cuando envía su configuración
            clients_db[client_id]['is_active'] = True
            # Si había una solicitud de force_sync, limpiarla
            if force_sync:
                clients_db[client_id].pop('force_sync', None)
                print(f"[Refresh] Configuración actualizada desde cliente {client_id}")
            save_server_data()
        except Exception as e:
            print(f"[Advertencia] Error al recibir configuración del cliente: {e}")
        
        # Comparar configuración del cliente con la del servidor
        # Solo enviar server_config si hay diferencias O si se solicitó force_sync
        server_config = clients_db[client_id].get('config', {})
        if server_config:
            # Obtener configuración del cliente desde el query param
            client_config_data = request.args.get('client_config')
            client_config = {}
            if client_config_data:
                try:
                    import urllib.parse
                    client_config = json.loads(urllib.parse.unquote(client_config_data))
                except:
                    pass
            
            # Comparar configuraciones - solo enviar si hay diferencias
            config_changed = False
            config_fields = ['sync_interval', 'local_check_interval', 'expired_sync_interval', 
                            'lock_delay', 'warning_thresholds']
            
            for field in config_fields:
                server_value = server_config.get(field)
                client_value = client_config.get(field)
                
                # Si el servidor tiene un valor y es diferente al del cliente, hay cambio
                if server_value is not None:
                    # Comparar listas de forma especial (warning_thresholds)
                    if field == 'warning_thresholds':
                        if isinstance(server_value, list) and isinstance(client_value, list):
                            if sorted(server_value) != sorted(client_value):
                                config_changed = True
                                break
                        elif client_value != server_value:
                            config_changed = True
                            break
                    else:
                        if client_value != server_value:
                            config_changed = True
                            break
            
            # Solo enviar server_config si hay cambios O si se solicitó force_sync
            # Cuando hay force_sync, siempre enviar para forzar al cliente a sincronizar su configuración
            if config_changed or force_sync:
                client_data['server_config'] = server_config
                # Incluir flag force_sync en la respuesta para que el cliente sepa que debe sincronizar inmediatamente
                if force_sync:
                    client_data['force_sync'] = True
                # Si había force_sync y el cliente envió su configuración, limpiar el flag
                if force_sync and client_config_data:
                    clients_db[client_id].pop('force_sync', None)
                    save_server_data()
    
    return jsonify({
        'success': True,
        'client': client_data
    }), 200

@app.route('/api/client/<client_id>/refresh', methods=['POST'])
def refresh_client(client_id):
    """Fuerza la sincronización con el cliente para obtener su configuración y estado actual"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    try:
        # Marcar que necesitamos forzar sincronización
        # Esto se usará cuando el cliente sincronice normalmente
        clients_db[client_id]['force_sync'] = True
        
        # Si el cliente tiene configuración guardada, marcarlo como activo
        client_config = clients_db[client_id].get('config', {})
        if client_config:
            clients_db[client_id]['is_active'] = True
        
        # Si el cliente tiene sesión activa, también marcarlo como activo
        if client_id in client_sessions:
            session = client_sessions[client_id]
            time_disabled = session.get('time_disabled', False)
            clients_db[client_id]['is_active'] = True
            clients_db[client_id]['time_disabled'] = time_disabled
        
        save_server_data()
        
        # Obtener información actualizada del cliente
        client_data = clients_db[client_id].copy()
        
        # Incluir información de sesión si existe
        if client_id in client_sessions:
            session = client_sessions[client_id]
            time_disabled = session.get('time_disabled', False)
            end_time = datetime.fromisoformat(session['end_time'])
            remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
            
            if time_disabled:
                remaining_seconds = max(remaining_seconds, 999999999)
            
            client_data['current_session'] = {
                'time_limit': session['time_limit'],
                'start_time': session['start_time'],
                'end_time': session['end_time'],
                'remaining_seconds': remaining_seconds,
                'time_disabled': time_disabled
            }
        
        return jsonify({
            'success': True,
            'message': 'Cliente refrescado. La configuración se actualizará cuando el cliente sincronice.',
            'client': client_data
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error al refrescar cliente: {str(e)}'
        }), 500

@app.route('/api/client/<client_id>/stop', methods=['POST'])
def stop_client_session(client_id):
    """Detiene la sesión de un cliente estableciendo tiempo infinito (bloqueo deshabilitado)"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    # Calcular tiempo usado si había una sesión activa
    if client_id in client_sessions:
        session = client_sessions[client_id]
        # Solo calcular tiempo usado si no es una sesión con tiempo deshabilitado
        if not session.get('time_disabled', False):
            start_time = datetime.fromisoformat(session['start_time'])
            end_time = datetime.now()
            time_used = int((end_time - start_time).total_seconds())
            clients_db[client_id]['total_time_used'] += time_used
    
    # Establecer sesión con tiempo "infinito" (bloqueo deshabilitado)
    # Usamos un valor muy grande: 999999999 segundos (~31 años)
    unlimited_seconds = 999999999
    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=unlimited_seconds)
    
    client_sessions[client_id] = {
        'time_limit': unlimited_seconds,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat(),
        'time_disabled': True  # Flag que indica que el bloqueo está deshabilitado
    }
    
    # Marcar cliente como activo pero con tiempo deshabilitado
    clients_db[client_id]['is_active'] = True
    clients_db[client_id]['time_disabled'] = True
    save_server_data()
    
    return jsonify({
        'success': True,
        'message': 'Bloqueo de tiempo deshabilitado. Cliente permanece activo sin límite de tiempo.',
        'session': {
            'time_limit_seconds': unlimited_seconds,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'time_disabled': True
        }
    }), 200

@app.route('/api/client/<client_id>', methods=['DELETE'])
def delete_client(client_id):
    """Elimina un cliente del sistema"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    if client_id in client_sessions:
        del client_sessions[client_id]
    
    del clients_db[client_id]
    save_server_data()
    
    return jsonify({
        'success': True,
        'message': 'Cliente eliminado'
    }), 200

@app.route('/api/health', methods=['GET'])
def health_check():
    """Endpoint de salud del servidor"""
    return jsonify({
        'status': 'ok',
        'active_clients': len(client_sessions),
        'total_clients': len(clients_db)
    }), 200

@app.route('/api/server-info', methods=['GET'])
def get_server_info():
    """Obtiene información del servidor (IP, puerto, URL)"""
    try:
        # Obtener IP local
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        # Intentar obtener IP desde la request
        remote_addr = request.remote_addr
        request_host = request.host
        
        # Obtener puerto desde la request o variables de entorno
        port = os.getenv('PORT', '5000')
        if ':' in request_host:
            port = request_host.split(':')[-1]
        
        # Construir URL
        # Si estamos en Docker o red local, usar la IP local
        # Si es localhost, usar localhost
        if request_host.startswith('localhost') or request_host.startswith('127.0.0.1'):
            server_url = f"http://{local_ip}:{port}"
            display_url = f"http://{local_ip}:{port}"
        else:
            server_url = f"http://{request_host}"
            display_url = f"http://{request_host}"
        
        # Obtener todas las IPs de la máquina
        ip_addresses = []
        try:
            # Obtener todas las interfaces de red
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            primary_ip = s.getsockname()[0]
            s.close()
            ip_addresses.append(primary_ip)
        except:
            pass
        
        # Agregar IP local
        if local_ip not in ip_addresses:
            ip_addresses.append(local_ip)
        
        return jsonify({
            'success': True,
            'hostname': hostname,
            'ip_addresses': ip_addresses,
            'primary_ip': ip_addresses[0] if ip_addresses else local_ip,
            'port': port,
            'server_url': server_url,
            'display_url': display_url
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/', methods=['GET'])
def index():
    """Interfaz web del panel de control"""
    return render_template('index.html')

if __name__ == '__main__':
    # Cargar datos persistidos al iniciar
    load_server_data()
    
    # Obtener configuración desde variables de entorno
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'production') == 'development'
    
    print("=" * 50)
    print("Servidor CiberMonday iniciado")
    print("=" * 50)
    print(f"API disponible en: http://{host}:{port}")
    print(f"Datos persistidos en: {DATA_FILE}")
    print("Endpoints disponibles:")
    print("  POST   /api/register - Registrar nuevo cliente")
    print("  GET    /api/clients - Listar todos los clientes")
    print("  POST   /api/client/<id>/set-time - Establecer tiempo")
    print("  GET    /api/client/<id>/status - Estado del cliente")
    print("  POST   /api/client/<id>/stop - Detener sesión")
    print("  DELETE /api/client/<id> - Eliminar cliente")
    print("=" * 50)
    app.run(host=host, port=port, debug=debug)
