from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from datetime import datetime, timedelta
import uuid
import threading
import time
import os
import socket
import json

app = Flask(__name__, template_folder='templates')
CORS(app)

# Base de datos en memoria (en producción usarías una BD real)
clients_db = {}
client_sessions = {}
client_configs = {}  # Configuración de cada cliente
servers_db = {}  # Diccionario de servidores conocidos: {server_id: {url, ip, port, last_seen, ...}}

# Configuración del servidor
server_config = {
    'broadcast_interval': 1  # Intervalo de broadcast en segundos (por defecto 1 segundo)
}

# Configuración por defecto para clientes
DEFAULT_CLIENT_CONFIG = {
    'sync_interval': 30,           # Segundos entre sincronizaciones
    'alert_thresholds': [600, 300, 120, 60],  # Alertas a los 10, 5, 2, 1 minutos
    'custom_name': None,           # Nombre personalizado (None = usar nombre del equipo)
}

def generate_client_id():
    """Genera un ID único para cada cliente"""
    return str(uuid.uuid4())

@app.route('/api/register', methods=['POST'])
def register_client():
    """
    Registra un nuevo cliente o re-registra uno existente.
    Si se envía client_id, se re-registra el cliente con ese ID.
    Si se envía session_data, se restaura la sesión del cliente.
    Si se envía config, se almacena la configuración del cliente.
    """
    data = request.json
    client_name = data.get('name', 'Cliente Sin Nombre')
    existing_client_id = data.get('client_id')  # ID existente para re-registro
    session_data = data.get('session')  # Sesión activa del cliente
    client_config = data.get('config')  # Configuración del cliente
    
    # Determinar si es re-registro o nuevo registro
    if existing_client_id:
        client_id = existing_client_id
        is_reregister = True
    else:
        client_id = generate_client_id()
        is_reregister = False
    
    # Registrar/actualizar cliente en la base de datos
    # Obtener información de contacto del cliente para notificaciones push
    client_ip = data.get('client_ip') or request.remote_addr
    diagnostic_port = data.get('diagnostic_port', 5002)
    
    clients_db[client_id] = {
        'id': client_id,
        'name': client_name,
        'registered_at': datetime.now().isoformat(),
        'total_time_used': 0,
        'is_active': False,
        'client_ip': client_ip,
        'diagnostic_port': diagnostic_port,
        'last_contact': datetime.now().isoformat()
    }
    
    # Almacenar configuración del cliente (o usar la existente si es re-registro)
    if client_config:
        # El cliente envió su configuración actual
        client_configs[client_id] = {
            'sync_interval': client_config.get('sync_interval', DEFAULT_CLIENT_CONFIG['sync_interval']),
            'alert_thresholds': client_config.get('alert_thresholds', DEFAULT_CLIENT_CONFIG['alert_thresholds']),
            'custom_name': client_config.get('custom_name', None),
        }
        # Si el cliente tiene un nombre personalizado, usarlo en lugar del nombre del equipo
        if client_configs[client_id]['custom_name']:
            clients_db[client_id]['name'] = client_configs[client_id]['custom_name']
        print(f"[Registro] Cliente {client_id[:8]}... envió configuración: sync={client_configs[client_id]['sync_interval']}s, alertas={client_configs[client_id]['alert_thresholds']}, nombre={client_configs[client_id]['custom_name']}")
    elif client_id not in client_configs:
        # Nuevo cliente sin configuración - usar valores por defecto
        client_configs[client_id] = DEFAULT_CLIENT_CONFIG.copy()
    
    # Si el cliente envía datos de sesión, restaurarla
    if session_data:
        remaining_seconds = session_data.get('remaining_seconds', 0)
        time_limit = session_data.get('time_limit_seconds', remaining_seconds)
        
        if remaining_seconds > 0:
            # Calcular end_time basado en el tiempo restante reportado
            end_time = datetime.now() + timedelta(seconds=remaining_seconds)
            start_time = end_time - timedelta(seconds=time_limit)
            
            client_sessions[client_id] = {
                'time_limit': time_limit,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat()
            }
            clients_db[client_id]['is_active'] = True
            
            print(f"[Re-registro] Cliente {client_id[:8]}... restauró sesión con {remaining_seconds}s restantes")
    
    # Si el cliente envía lista de servidores conocidos, sincronizarlos
    known_servers = data.get('known_servers', [])
    if known_servers:
        sync_servers(known_servers)
    
    # Guardar información del cliente para notificaciones (IP y puerto de diagnóstico)
    client_ip = request.remote_addr
    diagnostic_port = data.get('diagnostic_port', 5002)  # Puerto por defecto del servidor de diagnóstico
    
    # Almacenar información de contacto del cliente para notificaciones push
    if client_id not in clients_db:
        clients_db[client_id] = {}
    clients_db[client_id]['client_ip'] = client_ip
    clients_db[client_id]['diagnostic_port'] = diagnostic_port
    clients_db[client_id]['last_contact'] = datetime.now().isoformat()
    
    # Auto-registrar este servidor en su propia lista
    local_ip = get_local_ip()
    if local_ip and local_ip != "127.0.0.1":
        local_server_url = f"http://{local_ip}:5000"
        register_server(local_server_url, local_ip, 5000)
    
    message = 'Cliente re-registrado exitosamente' if is_reregister else 'Cliente registrado exitosamente'
    
    return jsonify({
        'success': True,
        'client_id': client_id,
        'message': message,
        'session_restored': session_data is not None and client_id in client_sessions,
        'config': client_configs.get(client_id, DEFAULT_CLIENT_CONFIG),
        'known_servers': get_servers()
    }), 201

def _get_clients_list():
    """Función auxiliar que retorna la lista de clientes como lista de diccionarios."""
    clients_list = []
    for client_id, client_data in clients_db.items():
        client_info = client_data.copy()
        if client_id in client_sessions:
            session = client_sessions[client_id]
            # Convertir end_time de string ISO a datetime para calcular remaining_seconds
            end_time = datetime.fromisoformat(session['end_time'])
            remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
            
            client_info['current_session'] = {
                'time_limit': session['time_limit'],
                'start_time': session['start_time'],
                'end_time': session['end_time'],
                'remaining_seconds': remaining_seconds
            }
        
        # Incluir configuración del cliente
        client_info['config'] = client_configs.get(client_id, DEFAULT_CLIENT_CONFIG.copy())
        clients_list.append(client_info)
    
    return clients_list

@app.route('/api/clients', methods=['GET'])
def get_clients():
    """Obtiene la lista de todos los clientes registrados"""
    clients_list = _get_clients_list()
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
        'end_time': end_time.isoformat()
    }
    
    clients_db[client_id]['is_active'] = True
    
    return jsonify({
        'success': True,
        'message': f'Tiempo establecido: {time_value} {time_unit}',
        'session': {
            'time_limit_seconds': total_seconds,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat()
        }
    }), 200

@app.route('/api/client/<client_id>/status', methods=['GET'])
def get_client_status(client_id):
    """Obtiene el estado actual de un cliente, incluyendo su configuración"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    client_data = clients_db[client_id].copy()
    
    if client_id in client_sessions:
        session = client_sessions[client_id]
        end_time = datetime.fromisoformat(session['end_time'])
        remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
        is_expired = remaining_seconds == 0
        
        client_data['session'] = {
            'time_limit_seconds': session['time_limit'],
            'start_time': session['start_time'],
            'end_time': session['end_time'],
            'remaining_seconds': remaining_seconds,
            'is_expired': is_expired
        }
    else:
        client_data['session'] = None
    
    # Incluir configuración del cliente
    client_data['config'] = client_configs.get(client_id, DEFAULT_CLIENT_CONFIG.copy())
    
    # Incluir lista de servidores conocidos para que el cliente los sincronice
    return jsonify({
        'success': True,
        'client': client_data,
        'known_servers': get_servers()  # Incluir servidores conocidos en cada sincronización
    }), 200

@app.route('/api/client/<client_id>/config', methods=['GET'])
def get_client_config(client_id):
    """Obtiene la configuración de un cliente"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    config = client_configs.get(client_id, DEFAULT_CLIENT_CONFIG.copy())
    
    return jsonify({
        'success': True,
        'config': config
    }), 200

@app.route('/api/client/<client_id>/config', methods=['POST'])
def set_client_config(client_id):
    """Modifica la configuración de un cliente"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    data = request.json
    
    # Obtener configuración actual o usar defaults
    current_config = client_configs.get(client_id, DEFAULT_CLIENT_CONFIG.copy())
    
    # Actualizar solo los campos enviados
    if 'sync_interval' in data:
        sync_interval = int(data['sync_interval'])
        if sync_interval < 5:
            return jsonify({
                'success': False,
                'message': 'El intervalo de sincronización mínimo es 5 segundos'
            }), 400
        current_config['sync_interval'] = sync_interval
    
    if 'alert_thresholds' in data:
        thresholds = data['alert_thresholds']
        if isinstance(thresholds, list) and all(isinstance(t, int) and t > 0 for t in thresholds):
            # Ordenar de mayor a menor
            current_config['alert_thresholds'] = sorted(thresholds, reverse=True)
        else:
            return jsonify({
                'success': False,
                'message': 'Los umbrales de alerta deben ser una lista de números positivos'
            }), 400
    
    if 'custom_name' in data:
        custom_name = data['custom_name']
        if custom_name:
            custom_name = str(custom_name).strip()
            if len(custom_name) > 50:
                return jsonify({
                    'success': False,
                    'message': 'El nombre no puede tener más de 50 caracteres'
                }), 400
            current_config['custom_name'] = custom_name
            # Actualizar también el nombre en clients_db para que se muestre en la UI
            clients_db[client_id]['name'] = custom_name
        else:
            # Si se envía vacío o None, eliminar el nombre personalizado
            current_config['custom_name'] = None
    
    client_configs[client_id] = current_config
    
    print(f"[Config] Cliente {client_id[:8]}... configuración actualizada: {current_config}")
    
    return jsonify({
        'success': True,
        'message': 'Configuración actualizada',
        'config': current_config
    }), 200

@app.route('/api/client/<client_id>/report-session', methods=['POST'])
def report_client_session(client_id):
    """
    Permite al cliente reportar su sesión activa al servidor.
    Útil cuando el servidor se reinicia y pierde la información en memoria,
    pero el cliente aún tiene su sesión guardada localmente.
    """
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    data = request.json
    remaining_seconds = data.get('remaining_seconds', 0)
    time_limit = data.get('time_limit_seconds', remaining_seconds)
    
    if remaining_seconds <= 0:
        return jsonify({
            'success': False,
            'message': 'El tiempo restante debe ser mayor a 0'
        }), 400
    
    # Calcular tiempos basados en lo que reporta el cliente
    end_time = datetime.now() + timedelta(seconds=remaining_seconds)
    start_time = end_time - timedelta(seconds=time_limit)
    
    client_sessions[client_id] = {
        'time_limit': time_limit,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat()
    }
    clients_db[client_id]['is_active'] = True
    
    print(f"[Reporte] Cliente {client_id[:8]}... reportó sesión: {remaining_seconds}s restantes de {time_limit}s totales")
    
    return jsonify({
        'success': True,
        'message': f'Sesión reportada: {remaining_seconds} segundos restantes',
        'session': {
            'time_limit_seconds': time_limit,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'remaining_seconds': remaining_seconds
        }
    }), 200

@app.route('/api/client/<client_id>/stop', methods=['POST'])
def stop_client_session(client_id):
    """Detiene la sesión de un cliente"""
    if client_id not in clients_db:
        return jsonify({
            'success': False,
            'message': 'Cliente no encontrado'
        }), 404
    
    if client_id in client_sessions:
        # Calcular tiempo usado
        session = client_sessions[client_id]
        start_time = datetime.fromisoformat(session['start_time'])
        end_time = datetime.now()
        time_used = int((end_time - start_time).total_seconds())
        
        clients_db[client_id]['total_time_used'] += time_used
        del client_sessions[client_id]
        clients_db[client_id]['is_active'] = False
    
    return jsonify({
        'success': True,
        'message': 'Sesión detenida'
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

def get_local_ip():
    """Obtiene la IP local del servidor"""
    try:
        # Crear un socket para determinar la IP local
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

@app.route('/api/server-info', methods=['GET'])
def server_info():
    """Devuelve información del servidor (IP y puerto)"""
    port = int(os.getenv('PORT', 5000))
    local_ip = get_local_ip()
    
    return jsonify({
        'success': True,
        'ip': local_ip,
        'port': port,
        'url': f"http://{local_ip}:{port}",
        'broadcast_interval': server_config['broadcast_interval']
    }), 200

@app.route('/api/server-config', methods=['GET'])
def get_server_config():
    """Obtiene la configuración del servidor"""
    return jsonify({
        'success': True,
        'config': server_config.copy()
    }), 200

@app.route('/api/server-config', methods=['POST'])
def set_server_config():
    """Actualiza la configuración del servidor"""
    global server_config
    data = request.json
    
    if 'broadcast_interval' in data:
        broadcast_interval = int(data['broadcast_interval'])
        if broadcast_interval < 1:
            return jsonify({
                'success': False,
                'message': 'El intervalo de broadcast debe ser al menos 1 segundo'
            }), 400
        server_config['broadcast_interval'] = broadcast_interval
        print(f"[Config] Intervalo de broadcast actualizado a {broadcast_interval} segundos")
    
    return jsonify({
        'success': True,
        'config': server_config.copy(),
        'message': 'Configuración actualizada correctamente'
    }), 200

@app.route('/api/register-server', methods=['POST'])
def register_server_endpoint():
    """Registra un nuevo servidor (llamado por clientes u otros servidores o manualmente desde UI)"""
    data = request.json
    server_url = data.get('url')
    
    if not server_url:
        return jsonify({'success': False, 'message': 'URL del servidor requerida'}), 400
    
    # Verificar si el servidor ya existe
    server_exists = False
    for server_id, server_data in servers_db.items():
        if server_data.get('url') == server_url:
            server_exists = True
            break
    
    result = register_server(
        server_url,
        data.get('ip'),
        data.get('port')
    )
    result['known_servers'] = get_servers()
    
    # Si se agregó un nuevo servidor y hay clientes conectados, notificarlos inmediatamente
    if not server_exists and len(clients_db) > 0:
        print(f"[Servidor] Nuevo servidor {server_url} agregado manualmente. Notificando a {len(clients_db)} cliente(s) conectado(s)...")
        
        # Notificar a todos los clientes conectados sobre el nuevo servidor
        notified_count = 0
        for client_id, client_data in clients_db.items():
            client_ip = client_data.get('client_ip')
            diagnostic_port = client_data.get('diagnostic_port', 5002)
            
            if client_ip:
                try:
                    import urllib.request
                    import urllib.error
                    import json as json_lib
                    
                    notification_url = f"http://{client_ip}:{diagnostic_port}/api/add-server"
                    notification_data = {
                        'url': server_url,
                        'ip': data.get('ip'),
                        'port': data.get('port', 5000)
                    }
                    
                    req = urllib.request.Request(
                        notification_url,
                        data=json_lib.dumps(notification_data).encode('utf-8'),
                        headers={'Content-Type': 'application/json'}
                    )
                    
                    with urllib.request.urlopen(req, timeout=2) as response:
                        if response.status == 200:
                            notified_count += 1
                            print(f"[Servidor] ✅ Cliente {client_id[:8]}... notificado exitosamente")
                except Exception as e:
                    # Cliente no disponible o no responde, continuar con el siguiente
                    print(f"[Servidor] ⚠️  No se pudo notificar al cliente {client_id[:8]}... ({client_ip}:{diagnostic_port}): {e}")
        
        print(f"[Servidor] {notified_count}/{len(clients_db)} cliente(s) notificado(s) exitosamente")
        
        # También sincronizar con otros servidores conocidos
        _sync_with_other_servers()
    
    return jsonify(result), 201

@app.route('/api/servers', methods=['GET'])
def get_servers_endpoint():
    """Obtiene la lista de servidores conocidos"""
    return jsonify({
        'success': True,
        'servers': get_servers()
    }), 200

@app.route('/api/sync-servers', methods=['POST'])
def sync_servers_endpoint():
    """Sincroniza servidores y clientes entre servidores (anycast/discovery)"""
    data = request.json
    servers_list = data.get('servers', [])
    clients_list = data.get('clients', [])
    
    # Sincronizar servidores
    known_servers = sync_servers(servers_list)
    
    # Sincronizar clientes (registrar clientes de otros servidores si no existen localmente)
    if clients_list:
        for client_data in clients_list:
            client_id = client_data.get('id')
            if client_id and client_id not in clients_db:
                # Registrar cliente de otro servidor (sin sesión activa)
                clients_db[client_id] = {
                    'id': client_id,
                    'name': client_data.get('name', 'Cliente Remoto'),
                    'registered_at': datetime.now().isoformat(),
                    'total_time_used': 0,
                    'is_active': False
                }
                if client_id not in client_configs:
                    client_configs[client_id] = DEFAULT_CLIENT_CONFIG.copy()
    
    # Obtener respuesta de get_clients() para retornar
    response_data = get_clients()
    clients_list = response_data.get_json()['clients'] if hasattr(response_data, 'get_json') else []
    
    return jsonify({
        'success': True,
        'known_servers': known_servers,
        'known_clients': _get_clients_list()
    }), 200

def register_server(server_url, server_ip=None, server_port=None):
    """Registra o actualiza un servidor conocido."""
    import hashlib
    server_id = hashlib.md5(server_url.encode()).hexdigest()[:16]
    
    # Parsear URL si no se proporcionan IP y puerto
    if not server_ip or not server_port:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(server_url)
            server_ip = server_ip or parsed.hostname or "unknown"
            server_port = server_port or parsed.port or 5000
        except:
            server_ip = server_ip or "unknown"
            server_port = server_port or 5000
    
    servers_db[server_id] = {
        'id': server_id,
        'url': server_url,
        'ip': server_ip,
        'port': server_port,
        'last_seen': datetime.now().isoformat(),
        'is_active': True
    }
    
    return {'success': True, 'server_id': server_id}

def get_servers():
    """Obtiene la lista de servidores conocidos."""
    servers_list = []
    for server_id, server_data in servers_db.items():
        servers_list.append(server_data.copy())
    return servers_list

def sync_servers(servers_list):
    """Sincroniza la lista de servidores con otros servidores."""
    # Agregar/actualizar servidores recibidos
    for server_data in servers_list:
        server_url = server_data.get('url')
        if server_url:
            register_server(
                server_url,
                server_data.get('ip'),
                server_data.get('port')
            )
    
    # Intentar sincronizar con otros servidores (anycast/discovery)
    _sync_with_other_servers()
    
    # Retornar lista combinada (local + recibidos)
    return get_servers()

def _sync_with_other_servers():
    """Sincroniza información con otros servidores conocidos."""
    import urllib.request
    import urllib.error
    import json
    
    local_ip = get_local_ip()
    if local_ip == "127.0.0.1" or not local_ip:
        return
    
    local_server_url = f"http://{local_ip}:5000"
    
    # Preparar datos para enviar
    sync_data = {
        'servers': get_servers(),
        'clients': _get_clients_list()
    }
    
    # Intentar sincronizar con cada servidor conocido (excepto nosotros mismos)
    for server_id, server_data in list(servers_db.items()):
        server_url = server_data.get('url')
        if not server_url or server_url == local_server_url:
            continue
        
        try:
            req = urllib.request.Request(
                f"{server_url}/api/sync-servers",
                data=json.dumps(sync_data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=3) as response:
                if response.status == 200:
                    response_data = json.loads(response.read().decode('utf-8'))
                    # Actualizar con servidores recibidos del otro servidor
                    if response_data.get('known_servers'):
                        for other_server in response_data['known_servers']:
                            if other_server.get('url') != local_server_url:
                                register_server(
                                    other_server.get('url'),
                                    other_server.get('ip'),
                                    other_server.get('port')
                                )
        except:
            # Servidor no disponible, continuar con el siguiente
            pass

@app.route('/', methods=['GET'])
def index():
    """Interfaz web del panel de control"""
    return render_template('index.html')

def get_broadcast_address(ip_address):
    """
    Calcula la dirección de broadcast basándose en la IP.
    Para IPs como 192.168.68.101, asume máscara /24 (255.255.255.0)
    y retorna 192.168.68.255
    """
    try:
        parts = ip_address.split('.')
        if len(parts) == 4:
            # Asumir máscara /24 (255.255.255.0)
            return f"{parts[0]}.{parts[1]}.{parts[2]}.255"
    except:
        pass
    return "255.255.255.255"  # Fallback

def broadcast_server_presence():
    """
    Hace broadcast UDP para anunciar la presencia de este servidor a los clientes.
    Los clientes escuchan en el puerto 5001 y registran automáticamente nuevos servidores.
    """
    def broadcast_thread():
        DISCOVERY_PORT = 5001
        global server_config
        
        try:
            # Obtener IP del host desde variable de entorno si está disponible (útil en Docker)
            host_ip = os.getenv('HOST_IP')
            if host_ip:
                local_ip = host_ip
                print(f"[Broadcast] Usando IP del host desde HOST_IP: {local_ip}")
            else:
                local_ip = get_local_ip()
            
            if local_ip == "127.0.0.1" or not local_ip:
                print(f"[Broadcast] IP no válida para broadcast: {local_ip}")
                return
            
            server_url = f"http://{local_ip}:5000"
            server_info = {
                'url': server_url,
                'ip': local_ip,
                'port': 5000
            }
            
            # Calcular dirección de broadcast
            broadcast_addr = get_broadcast_address(local_ip)
            
            # Crear socket UDP para broadcast
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # En macOS, es mejor no hacer bind a una IP específica para broadcasts
            # El sistema elegirá automáticamente la interfaz correcta
            try:
                sock.bind(('', 0))  # Bind a todas las interfaces, puerto 0 = sistema elige
            except Exception as bind_error:
                print(f"[Broadcast] Advertencia al hacer bind: {bind_error}")
                # Continuar de todas formas, algunos sistemas permiten enviar sin bind
            
            print(f"[Broadcast] Iniciando anuncios de servidor en {local_ip}:5000")
            print(f"[Broadcast] Dirección de broadcast: {broadcast_addr}:{DISCOVERY_PORT}")
            print(f"[Broadcast] Enviando broadcasts UDP cada {server_config['broadcast_interval']} segundos")
            print(f"[Broadcast] Los broadcasts se detendrán automáticamente cuando haya clientes conectados")
            
            last_client_count = 0
            broadcasts_paused = False
            
            while True:
                try:
                    # Verificar si hay clientes conectados
                    num_clients = len(clients_db)
                    
                    if num_clients > 0:
                        # Hay clientes conectados, no enviar broadcast pero seguir verificando
                        if not broadcasts_paused:
                            # Primera vez que detectamos clientes - pausar broadcasts
                            print(f"[Broadcast] ⏸️  Hay {num_clients} cliente(s) conectado(s). Broadcasts pausados.")
                            broadcasts_paused = True
                        elif num_clients != last_client_count:
                            # El número de clientes cambió, actualizar log
                            print(f"[Broadcast] ⏸️  {num_clients} cliente(s) conectado(s). Broadcasts siguen pausados.")
                        last_client_count = num_clients
                        time.sleep(server_config['broadcast_interval'])
                        continue
                    else:
                        # No hay clientes
                        if broadcasts_paused:
                            # Se desconectaron todos los clientes - reanudar broadcasts
                            print(f"[Broadcast] ▶️  No hay clientes conectados. Reanudando broadcasts UDP.")
                            broadcasts_paused = False
                        last_client_count = 0
                    
                    # No hay clientes, enviar broadcast
                    message = json.dumps(server_info).encode('utf-8')
                    sock.sendto(message, (broadcast_addr, DISCOVERY_PORT))
                    print(f"[Broadcast] 📡 Broadcast enviado a {broadcast_addr}:{DISCOVERY_PORT} - {server_url}")
                    time.sleep(server_config['broadcast_interval'])
                except Exception as e:
                    print(f"[Broadcast] Error al enviar broadcast: {e}")
                    import traceback
                    traceback.print_exc()
                    time.sleep(BROADCAST_INTERVAL)
        except Exception as e:
            print(f"[Broadcast] Error en thread de broadcast: {e}")
            import traceback
            traceback.print_exc()
    
    # Iniciar thread de broadcast en background
    thread = threading.Thread(target=broadcast_thread, daemon=True)
    thread.start()

if __name__ == '__main__':
    # Obtener configuración desde variables de entorno
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'production') == 'development'
    
    print("=" * 50)
    print("Servidor CiberMonday iniciado")
    print("=" * 50)
    print(f"API disponible en: http://{host}:{port}")
    print("Endpoints disponibles:")
    print("  POST   /api/register - Registrar nuevo cliente")
    print("  GET    /api/clients - Listar todos los clientes")
    print("  POST   /api/client/<id>/set-time - Establecer tiempo")
    print("  GET    /api/client/<id>/status - Estado del cliente")
    print("  POST   /api/client/<id>/stop - Detener sesión")
    print("  DELETE /api/client/<id> - Eliminar cliente")
    print("=" * 50)
    
    # Iniciar broadcast de presencia del servidor
    # Los clientes escucharán estos broadcasts y registrarán automáticamente este servidor
    broadcast_server_presence()
    
    app.run(host=host, port=port, debug=debug)
