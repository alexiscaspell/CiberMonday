"""
Wrapper del servidor Flask para Android
Este módulo permite ejecutar el servidor Flask en Android usando Chaquopy
"""

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from datetime import datetime, timedelta
import uuid
import threading
import socket
import os

# Variable global para el servidor
server_instance = None
server_thread = None
shutdown_event = threading.Event()

# Base de datos en memoria
clients_db = {}
client_sessions = {}
client_configs = {}

# Configuración por defecto para clientes
DEFAULT_CLIENT_CONFIG = {
    'sync_interval': 30,
    'alert_thresholds': [600, 300, 120, 60],
    'custom_name': None,
}

def create_app(data_dir):
    """Crea y configura la aplicación Flask"""
    
    # Determinar la ruta de templates
    # En Android, los templates se copian al directorio de Python
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    
    app = Flask(__name__, template_folder=template_dir)
    CORS(app)
    
    def generate_client_id():
        return str(uuid.uuid4())
    
    @app.route('/api/register', methods=['POST'])
    def register_client():
        data = request.json
        client_name = data.get('name', 'Cliente Sin Nombre')
        existing_client_id = data.get('client_id')
        session_data = data.get('session')
        client_config = data.get('config')
        
        if existing_client_id:
            client_id = existing_client_id
            is_reregister = True
        else:
            client_id = generate_client_id()
            is_reregister = False
        
        clients_db[client_id] = {
            'id': client_id,
            'name': client_name,
            'registered_at': datetime.now().isoformat(),
            'total_time_used': 0,
            'is_active': False
        }
        
        if client_config:
            client_configs[client_id] = {
                'sync_interval': client_config.get('sync_interval', DEFAULT_CLIENT_CONFIG['sync_interval']),
                'alert_thresholds': client_config.get('alert_thresholds', DEFAULT_CLIENT_CONFIG['alert_thresholds']),
                'custom_name': client_config.get('custom_name', None),
            }
            if client_configs[client_id]['custom_name']:
                clients_db[client_id]['name'] = client_configs[client_id]['custom_name']
        elif client_id not in client_configs:
            client_configs[client_id] = DEFAULT_CLIENT_CONFIG.copy()
        
        if session_data:
            remaining_seconds = session_data.get('remaining_seconds', 0)
            time_limit = session_data.get('time_limit_seconds', remaining_seconds)
            
            if remaining_seconds > 0:
                end_time = datetime.now() + timedelta(seconds=remaining_seconds)
                start_time = end_time - timedelta(seconds=time_limit)
                
                client_sessions[client_id] = {
                    'time_limit': time_limit,
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat()
                }
                clients_db[client_id]['is_active'] = True
        
        message = 'Cliente re-registrado exitosamente' if is_reregister else 'Cliente registrado exitosamente'
        
        return jsonify({
            'success': True,
            'client_id': client_id,
            'message': message,
            'session_restored': session_data is not None and client_id in client_sessions,
            'config': client_configs.get(client_id, DEFAULT_CLIENT_CONFIG)
        }), 201
    
    @app.route('/api/clients', methods=['GET'])
    def get_clients():
        clients_list = []
        for client_id, client_data in clients_db.items():
            client_info = client_data.copy()
            if client_id in client_sessions:
                session = client_sessions[client_id]
                end_time = datetime.fromisoformat(session['end_time'])
                remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
                
                client_info['current_session'] = {
                    'time_limit': session['time_limit'],
                    'start_time': session['start_time'],
                    'end_time': session['end_time'],
                    'remaining_seconds': remaining_seconds
                }
            
            client_info['config'] = client_configs.get(client_id, DEFAULT_CLIENT_CONFIG.copy())
            clients_list.append(client_info)
        
        return jsonify({
            'success': True,
            'clients': clients_list
        }), 200
    
    @app.route('/api/client/<client_id>/set-time', methods=['POST'])
    def set_client_time(client_id):
        if client_id not in clients_db:
            return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
        
        data = request.json
        time_value = data.get('time', 0)
        time_unit = data.get('unit', 'minutes')
        
        if time_unit == 'hours':
            total_seconds = time_value * 3600
        else:
            total_seconds = time_value * 60
        
        if total_seconds <= 0:
            return jsonify({'success': False, 'message': 'El tiempo debe ser mayor a 0'}), 400
        
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
        if client_id not in clients_db:
            return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
        
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
        
        client_data['config'] = client_configs.get(client_id, DEFAULT_CLIENT_CONFIG.copy())
        
        return jsonify({'success': True, 'client': client_data}), 200
    
    @app.route('/api/client/<client_id>/config', methods=['GET'])
    def get_client_config(client_id):
        if client_id not in clients_db:
            return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
        
        config = client_configs.get(client_id, DEFAULT_CLIENT_CONFIG.copy())
        return jsonify({'success': True, 'config': config}), 200
    
    @app.route('/api/client/<client_id>/config', methods=['POST'])
    def set_client_config(client_id):
        if client_id not in clients_db:
            return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
        
        data = request.json
        current_config = client_configs.get(client_id, DEFAULT_CLIENT_CONFIG.copy())
        
        if 'sync_interval' in data:
            sync_interval = int(data['sync_interval'])
            if sync_interval < 5:
                return jsonify({'success': False, 'message': 'El intervalo mínimo es 5 segundos'}), 400
            current_config['sync_interval'] = sync_interval
        
        if 'alert_thresholds' in data:
            thresholds = data['alert_thresholds']
            if isinstance(thresholds, list) and all(isinstance(t, int) and t > 0 for t in thresholds):
                current_config['alert_thresholds'] = sorted(thresholds, reverse=True)
        
        if 'custom_name' in data:
            custom_name = data['custom_name']
            if custom_name:
                custom_name = str(custom_name).strip()[:50]
                current_config['custom_name'] = custom_name
                clients_db[client_id]['name'] = custom_name
            else:
                current_config['custom_name'] = None
        
        client_configs[client_id] = current_config
        
        return jsonify({'success': True, 'message': 'Configuración actualizada', 'config': current_config}), 200
    
    @app.route('/api/client/<client_id>/report-session', methods=['POST'])
    def report_client_session(client_id):
        if client_id not in clients_db:
            return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
        
        data = request.json
        remaining_seconds = data.get('remaining_seconds', 0)
        time_limit = data.get('time_limit_seconds', remaining_seconds)
        
        if remaining_seconds <= 0:
            return jsonify({'success': False, 'message': 'El tiempo debe ser mayor a 0'}), 400
        
        end_time = datetime.now() + timedelta(seconds=remaining_seconds)
        start_time = end_time - timedelta(seconds=time_limit)
        
        client_sessions[client_id] = {
            'time_limit': time_limit,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat()
        }
        clients_db[client_id]['is_active'] = True
        
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
        if client_id not in clients_db:
            return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
        
        if client_id in client_sessions:
            session = client_sessions[client_id]
            start_time = datetime.fromisoformat(session['start_time'])
            end_time = datetime.now()
            time_used = int((end_time - start_time).total_seconds())
            
            clients_db[client_id]['total_time_used'] += time_used
            del client_sessions[client_id]
            clients_db[client_id]['is_active'] = False
        
        return jsonify({'success': True, 'message': 'Sesión detenida'}), 200
    
    @app.route('/api/client/<client_id>', methods=['DELETE'])
    def delete_client(client_id):
        if client_id not in clients_db:
            return jsonify({'success': False, 'message': 'Cliente no encontrado'}), 404
        
        if client_id in client_sessions:
            del client_sessions[client_id]
        if client_id in client_configs:
            del client_configs[client_id]
        del clients_db[client_id]
        
        return jsonify({'success': True, 'message': 'Cliente eliminado'}), 200
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({
            'status': 'ok',
            'active_clients': len(client_sessions),
            'total_clients': len(clients_db)
        }), 200
    
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return "127.0.0.1"
    
    @app.route('/api/server-info', methods=['GET'])
    def server_info():
        local_ip = get_local_ip()
        return jsonify({
            'success': True,
            'ip': local_ip,
            'port': 5000,
            'url': f"http://{local_ip}:5000"
        }), 200
    
    @app.route('/', methods=['GET'])
    def index():
        return render_template('index.html')
    
    return app

def start_server(host, port, data_dir):
    """Inicia el servidor Flask"""
    global server_instance, shutdown_event
    
    shutdown_event.clear()
    app = create_app(data_dir)
    
    # Usar servidor de desarrollo con threaded=True
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)

def stop_server():
    """Detiene el servidor Flask"""
    global shutdown_event
    shutdown_event.set()
