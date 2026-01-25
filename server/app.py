from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from datetime import datetime, timedelta
import uuid
import threading
import time
import os
import socket

app = Flask(__name__, template_folder='templates')
CORS(app)

# Base de datos en memoria (en producción usarías una BD real)
clients_db = {}
client_sessions = {}

def generate_client_id():
    """Genera un ID único para cada cliente"""
    return str(uuid.uuid4())

@app.route('/api/register', methods=['POST'])
def register_client():
    """
    Registra un nuevo cliente o re-registra uno existente.
    Si se envía client_id, se re-registra el cliente con ese ID.
    Si se envía session_data, se restaura la sesión del cliente.
    """
    data = request.json
    client_name = data.get('name', 'Cliente Sin Nombre')
    existing_client_id = data.get('client_id')  # ID existente para re-registro
    session_data = data.get('session')  # Sesión activa del cliente
    
    # Determinar si es re-registro o nuevo registro
    if existing_client_id:
        client_id = existing_client_id
        is_reregister = True
    else:
        client_id = generate_client_id()
        is_reregister = False
    
    # Registrar/actualizar cliente en la base de datos
    clients_db[client_id] = {
        'id': client_id,
        'name': client_name,
        'registered_at': datetime.now().isoformat(),
        'total_time_used': 0,
        'is_active': False
    }
    
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
    
    message = 'Cliente re-registrado exitosamente' if is_reregister else 'Cliente registrado exitosamente'
    
    return jsonify({
        'success': True,
        'client_id': client_id,
        'message': message,
        'session_restored': session_data is not None and client_id in client_sessions
    }), 201

@app.route('/api/clients', methods=['GET'])
def get_clients():
    """Obtiene la lista de todos los clientes registrados"""
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
    """Obtiene el estado actual de un cliente"""
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
    
    return jsonify({
        'success': True,
        'client': client_data
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
        'url': f"http://{local_ip}:{port}"
    }), 200

@app.route('/', methods=['GET'])
def index():
    """Interfaz web del panel de control"""
    return render_template('index.html')

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
    app.run(host=host, port=port, debug=debug)
