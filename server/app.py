import sys
import os
import functools

# Agregar el directorio padre al path para poder importar core
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from datetime import datetime
import json
import urllib.request
import urllib.error

from core import ClientManager

app = Flask(__name__, template_folder='templates')
CORS(app)

# Instancia única del gestor de clientes/servidores
_port = int(os.getenv('PORT', 5000))
manager = ClientManager(server_port=_port)

# ==================== ADMIN ACCESS CONTROL ====================

# IPs permitidas para acceder a rutas de admin
# Siempre incluye localhost; se pueden agregar más via ADMIN_ALLOWED_IPS (comma-separated)
_LOCALHOST_IPS = {'127.0.0.1', '::1'}
_extra_ips = os.getenv('ADMIN_ALLOWED_IPS', '')
ADMIN_ALLOWED_IPS = _LOCALHOST_IPS | {ip.strip() for ip in _extra_ips.split(',') if ip.strip()}


def _is_admin_request():
    """Verifica si la request viene de una IP autorizada para admin."""
    return request.remote_addr in ADMIN_ALLOWED_IPS


def admin_only(f):
    """Decorator que restringe una ruta a IPs de admin (localhost por defecto)."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not _is_admin_request():
            return jsonify({
                'success': False,
                'message': 'Acceso denegado. Solo disponible desde el servidor.'
            }), 403
        return f(*args, **kwargs)
    return decorated


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
@admin_only
def get_clients():
    """Obtiene la lista de todos los clientes registrados."""
    return jsonify({
        'success': True,
        'clients': manager.get_clients()
    }), 200


@app.route('/api/client/<client_id>/set-time', methods=['POST'])
@admin_only
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
    
    # Si from_client=True, es el cliente reportando su config (público)
    # Si no, es el admin cambiando config (solo localhost)
    from_client = data.get('from_client', False)
    
    if not from_client and not _is_admin_request():
        return jsonify({
            'success': False,
            'message': 'Acceso denegado. Solo disponible desde el servidor.'
        }), 403
    
    result = manager.set_client_config(
        client_id,
        sync_interval=data.get('sync_interval'),
        alert_thresholds=data.get('alert_thresholds'),
        custom_name=data.get('custom_name'),
        max_server_timeouts=data.get('max_server_timeouts'),
        lock_recheck_interval=data.get('lock_recheck_interval'),
        notify_client=not from_client
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
@admin_only
def stop_client_session(client_id):
    """Detiene la sesión de un cliente."""
    result = manager.stop_client_session(client_id)
    status = 200 if result['success'] else 404
    return jsonify(result), status


@app.route('/api/client/<client_id>', methods=['DELETE'])
@admin_only
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
@admin_only
def get_server_config():
    """Obtiene la configuración del servidor."""
    return jsonify({
        'success': True,
        'config': manager.get_server_config()
    }), 200


@app.route('/api/server-config', methods=['POST'])
@admin_only
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
    """
    Sincroniza la lista de servidores entre servidores o con el cliente.
    Solo sincroniza SERVIDORES. Los clientes son su propia fuente de verdad
    y propagan su estado directamente a cada server.
    """
    data = request.json
    servers_list = data.get('servers', [])
    
    known_servers = manager.sync_servers(servers_list)
    
    return jsonify({
        'success': True,
        'known_servers': known_servers
    }), 200


@app.route('/api/force-sync', methods=['POST'])
@admin_only
def force_sync_endpoint():
    """Fuerza una sincronización completa con todos los servidores conocidos."""
    try:
        manager._sync_with_other_servers()
        return jsonify({
            'success': True,
            'message': 'Sincronización forzada completada',
            'known_servers': manager.get_servers(),
            'known_clients': manager.get_clients()
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error durante sincronización: {str(e)}'
        }), 500


# ==================== WEB UI ====================

@app.route('/', methods=['GET'])
@admin_only
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


def broadcast_server_presence(server_port=5000):
    """Inicia broadcast UDP usando ClientManager.start_broadcast()."""
    host_ip = os.getenv('HOST_IP')
    if host_ip:
        print(f"[Broadcast] Usando IP del host desde HOST_IP: {host_ip}")
    manager.start_broadcast(host_ip_override=host_ip)


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
    
    broadcast_server_presence(server_port=port)
    
    app.run(host=host, port=port, debug=debug)
