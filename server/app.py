import sys
import os

# Agregar el directorio padre al path para poder importar core
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from datetime import datetime
import threading
import time
import socket
import json
import urllib.request
import urllib.error

from core import ClientManager

app = Flask(__name__, template_folder='templates')
CORS(app)

# Instancia única del gestor de clientes/servidores
manager = ClientManager()


# ==================== CLIENT ROUTES ====================

@app.route('/api/register', methods=['POST'])
def register_client():
    """Registra un nuevo cliente o re-registra uno existente."""
    data = request.json
    
    # Obtener IP del cliente desde la request
    client_ip = data.get('client_ip') or request.remote_addr
    diagnostic_port = data.get('diagnostic_port', 5002)
    
    result = manager.register_client(
        name=data.get('name', 'Cliente Sin Nombre'),
        client_id=data.get('client_id'),
        session_data=data.get('session'),
        config=data.get('config'),
        known_servers=data.get('known_servers', []),
        client_ip=client_ip,
        diagnostic_port=diagnostic_port
    )
    
    # Actualizar info de contacto del cliente (puede haber cambiado de IP)
    if result['success']:
        cid = result['client_id']
        manager.clients_db[cid]['client_ip'] = client_ip
        manager.clients_db[cid]['diagnostic_port'] = diagnostic_port
        manager.clients_db[cid]['last_contact'] = datetime.now().isoformat()
    
    return jsonify(result), 201


@app.route('/api/clients', methods=['GET'])
def get_clients():
    """Obtiene la lista de todos los clientes registrados."""
    return jsonify({
        'success': True,
        'clients': manager.get_clients()
    }), 200


@app.route('/api/client/<client_id>/set-time', methods=['POST'])
def set_client_time(client_id):
    """Establece el tiempo de uso para un cliente específico."""
    data = request.json
    result = manager.set_client_time(
        client_id,
        data.get('time', 0),
        data.get('unit', 'minutes')
    )
    status = 200 if result['success'] else (404 if 'no encontrado' in result['message'] else 400)
    return jsonify(result), status


@app.route('/api/client/<client_id>/status', methods=['GET'])
def get_client_status(client_id):
    """Obtiene el estado actual de un cliente, incluyendo su configuración."""
    client_data = manager.get_client_status(client_id)
    if client_data is None:
        return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
    
    return jsonify({
        'success': True,
        'client': client_data,
        'known_servers': manager.get_servers()
    }), 200


@app.route('/api/client/<client_id>/config', methods=['GET'])
def get_client_config(client_id):
    """Obtiene la configuración de un cliente."""
    config = manager.get_client_config(client_id)
    if config is None:
        return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
    
    return jsonify({'success': True, 'config': config}), 200


@app.route('/api/client/<client_id>/config', methods=['POST'])
def set_client_config(client_id):
    """Modifica la configuración de un cliente."""
    data = request.json
    
    result = manager.set_client_config(
        client_id,
        sync_interval=data.get('sync_interval'),
        alert_thresholds=data.get('alert_thresholds'),
        custom_name=data.get('custom_name'),
        max_server_timeouts=data.get('max_server_timeouts')
    )
    
    status = 200 if result['success'] else (404 if 'no encontrado' in result['message'] else 400)
    return jsonify(result), status


@app.route('/api/client/<client_id>/report-session', methods=['POST'])
def report_client_session(client_id):
    """Permite al cliente reportar su sesión activa al servidor."""
    data = request.json
    result = manager.report_session(
        client_id,
        data.get('remaining_seconds', 0),
        data.get('time_limit_seconds')
    )
    status = 200 if result['success'] else (404 if 'no encontrado' in result['message'] else 400)
    return jsonify(result), status


@app.route('/api/client/<client_id>/stop', methods=['POST'])
def stop_client_session(client_id):
    """Detiene la sesión de un cliente."""
    result = manager.stop_client_session(client_id)
    status = 200 if result['success'] else 404
    return jsonify(result), status


@app.route('/api/client/<client_id>', methods=['DELETE'])
def delete_client(client_id):
    """Elimina un cliente del sistema."""
    result = manager.delete_client(client_id)
    status = 200 if result['success'] else 404
    return jsonify(result), status


# ==================== SERVER INFO ROUTES ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Endpoint de salud del servidor."""
    stats = manager.get_stats()
    return jsonify({
        'status': 'ok',
        'active_clients': stats['active_clients'],
        'total_clients': stats['total_clients']
    }), 200


@app.route('/api/server-info', methods=['GET'])
def server_info():
    """Devuelve información del servidor (IP y puerto)."""
    port = int(os.getenv('PORT', 5000))
    local_ip = manager.get_local_ip()
    config = manager.get_server_config()
    
    return jsonify({
        'success': True,
        'ip': local_ip,
        'port': port,
        'url': f"http://{local_ip}:{port}",
        'broadcast_interval': config['broadcast_interval']
    }), 200


@app.route('/api/server-config', methods=['GET'])
def get_server_config():
    """Obtiene la configuración del servidor."""
    return jsonify({
        'success': True,
        'config': manager.get_server_config()
    }), 200


@app.route('/api/server-config', methods=['POST'])
def set_server_config():
    """Actualiza la configuración del servidor."""
    data = request.json
    result = manager.set_server_config(
        broadcast_interval=data.get('broadcast_interval')
    )
    status = 200 if result['success'] else 400
    return jsonify(result), status


# ==================== SERVER DISCOVERY ROUTES ====================

@app.route('/api/register-server', methods=['POST'])
def register_server_endpoint():
    """Registra un nuevo servidor (llamado por clientes u otros servidores o manualmente desde UI)."""
    data = request.json
    server_url = data.get('url')
    
    if not server_url:
        return jsonify({'success': False, 'message': 'URL del servidor requerida'}), 400
    
    # Verificar si el servidor ya existe
    server_exists = any(
        sd.get('url') == server_url for sd in manager.servers_db.values()
    )
    
    result = manager.register_server(server_url, data.get('ip'), data.get('port'))
    result['known_servers'] = manager.get_servers()
    
    # Si se agregó un nuevo servidor y hay clientes conectados, notificarlos
    if not server_exists and len(manager.clients_db) > 0:
        _notify_clients_new_server(server_url, data)
        manager._sync_with_other_servers()
    
    return jsonify(result), 201


@app.route('/api/servers', methods=['GET'])
def get_servers_endpoint():
    """Obtiene la lista de servidores conocidos."""
    return jsonify({
        'success': True,
        'servers': manager.get_servers()
    }), 200


@app.route('/api/sync-servers', methods=['POST'])
def sync_servers_endpoint():
    """Sincroniza servidores y clientes entre servidores (anycast/discovery)."""
    data = request.json
    servers_list = data.get('servers', [])
    clients_list = data.get('clients', [])
    
    known_servers = manager.sync_servers(servers_list)
    
    if clients_list:
        manager.sync_clients_from_remote(clients_list)
    
    return jsonify({
        'success': True,
        'known_servers': known_servers,
        'known_clients': manager.get_clients()
    }), 200


# ==================== WEB UI ====================

@app.route('/', methods=['GET'])
def index():
    """Interfaz web del panel de control."""
    return render_template('index.html')


# ==================== PLATFORM-SPECIFIC FUNCTIONS ====================

def _notify_clients_new_server(server_url, data):
    """
    Notifica a todos los clientes conectados sobre un nuevo servidor.
    Específico del servidor web (usa client_ip/diagnostic_port).
    """
    print(f"[Servidor] Nuevo servidor {server_url} agregado. Notificando a {len(manager.clients_db)} cliente(s)...")
    
    notified_count = 0
    for client_id, client_data in manager.clients_db.items():
        client_ip = client_data.get('client_ip')
        diagnostic_port = client_data.get('diagnostic_port', 5002)
        
        if client_ip:
            try:
                notification_url = f"http://{client_ip}:{diagnostic_port}/api/add-server"
                notification_data = {
                    'url': server_url,
                    'ip': data.get('ip'),
                    'port': data.get('port', 5000)
                }
                
                req = urllib.request.Request(
                    notification_url,
                    data=json.dumps(notification_data).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                
                with urllib.request.urlopen(req, timeout=2) as response:
                    if response.status == 200:
                        notified_count += 1
                        print(f"[Servidor] ✅ Cliente {client_id[:8]}... notificado exitosamente")
            except Exception as e:
                print(f"[Servidor] ⚠️  No se pudo notificar al cliente {client_id[:8]}... ({client_ip}:{diagnostic_port}): {e}")
    
    print(f"[Servidor] {notified_count}/{len(manager.clients_db)} cliente(s) notificado(s) exitosamente")


def broadcast_server_presence():
    """
    Hace broadcast UDP para anunciar la presencia de este servidor a los clientes.
    Los clientes escuchan en el puerto 5001 y registran automáticamente nuevos servidores.
    """
    def broadcast_thread():
        DISCOVERY_PORT = 5001
        
        try:
            # Obtener IP del host desde variable de entorno si está disponible (útil en Docker)
            host_ip = os.getenv('HOST_IP')
            if host_ip:
                local_ip = host_ip
                print(f"[Broadcast] Usando IP del host desde HOST_IP: {local_ip}")
            else:
                local_ip = manager.get_local_ip()
            
            if local_ip == "127.0.0.1" or not local_ip:
                print(f"[Broadcast] IP no válida para broadcast: {local_ip}")
                return
            
            server_url = f"http://{local_ip}:5000"
            server_info_data = {
                'url': server_url,
                'ip': local_ip,
                'port': 5000
            }
            
            broadcast_addr = manager.get_broadcast_address()
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                sock.bind(('', 0))
            except Exception as bind_error:
                print(f"[Broadcast] Advertencia al hacer bind: {bind_error}")
            
            config = manager.get_server_config()
            print(f"[Broadcast] Iniciando anuncios de servidor en {local_ip}:5000")
            print(f"[Broadcast] Dirección de broadcast: {broadcast_addr}:{DISCOVERY_PORT}")
            print(f"[Broadcast] Enviando broadcasts UDP cada {config['broadcast_interval']} segundos")
            print(f"[Broadcast] Los broadcasts se detendrán automáticamente cuando haya clientes conectados")
            
            last_client_count = 0
            broadcasts_paused = False
            
            while True:
                try:
                    config = manager.get_server_config()
                    num_clients = len(manager.clients_db)
                    
                    if num_clients > 0:
                        if not broadcasts_paused:
                            print(f"[Broadcast] ⏸️  Hay {num_clients} cliente(s) conectado(s). Broadcasts pausados.")
                            broadcasts_paused = True
                        elif num_clients != last_client_count:
                            print(f"[Broadcast] ⏸️  {num_clients} cliente(s) conectado(s). Broadcasts siguen pausados.")
                        last_client_count = num_clients
                        time.sleep(config['broadcast_interval'])
                        continue
                    else:
                        if broadcasts_paused:
                            print(f"[Broadcast] ▶️  No hay clientes conectados. Reanudando broadcasts UDP.")
                            broadcasts_paused = False
                        last_client_count = 0
                    
                    message = json.dumps(server_info_data).encode('utf-8')
                    sock.sendto(message, (broadcast_addr, DISCOVERY_PORT))
                    print(f"[Broadcast] 📡 Broadcast enviado a {broadcast_addr}:{DISCOVERY_PORT} - {server_url}")
                    time.sleep(config['broadcast_interval'])
                except Exception as e:
                    print(f"[Broadcast] Error al enviar broadcast: {e}")
                    import traceback
                    traceback.print_exc()
                    time.sleep(config.get('broadcast_interval', 1))
        except Exception as e:
            print(f"[Broadcast] Error en thread de broadcast: {e}")
            import traceback
            traceback.print_exc()
    
    thread = threading.Thread(target=broadcast_thread, daemon=True)
    thread.start()


if __name__ == '__main__':
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
    
    broadcast_server_presence()
    
    app.run(host=host, port=port, debug=debug)
