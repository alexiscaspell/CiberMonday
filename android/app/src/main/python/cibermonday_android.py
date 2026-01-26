"""
CiberMonday para Android - Módulo unificado
Provee tanto la API HTTP (para clientes remotos) como acceso directo (para UI nativa).
"""

from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import uuid
import json
import socket
import threading
import re


class ClientManager:
    """
    Gestor de clientes del ciber y sus sesiones de tiempo.
    Singleton compartido entre Flask y la UI nativa.
    """
    
    DEFAULT_CONFIG = {
        'sync_interval': 30,
        'alert_thresholds': [600, 300, 120, 60],
        'custom_name': None,
    }
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.clients_db = {}
                    cls._instance.client_sessions = {}
                    cls._instance.client_configs = {}
        return cls._instance
    
    def _generate_client_id(self):
        return str(uuid.uuid4())
    
    def register_client(self, name='Cliente Sin Nombre', client_id=None, 
                        session_data=None, config=None):
        is_reregister = client_id is not None
        if not is_reregister:
            client_id = self._generate_client_id()
        
        self.clients_db[client_id] = {
            'id': client_id,
            'name': name,
            'registered_at': datetime.now().isoformat(),
            'total_time_used': 0,
            'is_active': False
        }
        
        if config:
            self.client_configs[client_id] = {
                'sync_interval': config.get('sync_interval', self.DEFAULT_CONFIG['sync_interval']),
                'alert_thresholds': config.get('alert_thresholds', self.DEFAULT_CONFIG['alert_thresholds']),
                'custom_name': config.get('custom_name'),
            }
            if self.client_configs[client_id]['custom_name']:
                self.clients_db[client_id]['name'] = self.client_configs[client_id]['custom_name']
        elif client_id not in self.client_configs:
            self.client_configs[client_id] = self.DEFAULT_CONFIG.copy()
        
        session_restored = False
        if session_data:
            remaining_seconds = session_data.get('remaining_seconds', 0)
            time_limit = session_data.get('time_limit_seconds', remaining_seconds)
            
            if remaining_seconds > 0:
                end_time = datetime.now() + timedelta(seconds=remaining_seconds)
                start_time = end_time - timedelta(seconds=time_limit)
                
                self.client_sessions[client_id] = {
                    'time_limit': time_limit,
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat()
                }
                self.clients_db[client_id]['is_active'] = True
                session_restored = True
        
        return {
            'success': True,
            'client_id': client_id,
            'message': 'Cliente re-registrado' if is_reregister else 'Cliente registrado',
            'session_restored': session_restored,
            'config': self.client_configs.get(client_id, self.DEFAULT_CONFIG)
        }
    
    def get_clients(self):
        clients_list = []
        for client_id, client_data in self.clients_db.items():
            client_info = client_data.copy()
            
            if client_id in self.client_sessions:
                session = self.client_sessions[client_id]
                end_time = datetime.fromisoformat(session['end_time'])
                remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
                
                client_info['current_session'] = {
                    'time_limit': session['time_limit'],
                    'start_time': session['start_time'],
                    'end_time': session['end_time'],
                    'remaining_seconds': remaining_seconds
                }
            else:
                client_info['current_session'] = None
            
            client_info['config'] = self.client_configs.get(client_id, self.DEFAULT_CONFIG.copy())
            clients_list.append(client_info)
        
        return clients_list
    
    def set_client_time(self, client_id, time_value, time_unit='minutes'):
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        if time_unit == 'hours':
            total_seconds = time_value * 3600
        else:
            total_seconds = time_value * 60
        
        if total_seconds <= 0:
            return {'success': False, 'message': 'El tiempo debe ser mayor a 0'}
        
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=total_seconds)
        
        self.client_sessions[client_id] = {
            'time_limit': total_seconds,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat()
        }
        self.clients_db[client_id]['is_active'] = True
        
        return {
            'success': True,
            'message': f'Tiempo establecido: {time_value} {time_unit}'
        }
    
    def stop_client_session(self, client_id):
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        if client_id in self.client_sessions:
            session = self.client_sessions[client_id]
            start_time = datetime.fromisoformat(session['start_time'])
            time_used = int((datetime.now() - start_time).total_seconds())
            
            self.clients_db[client_id]['total_time_used'] += time_used
            del self.client_sessions[client_id]
            self.clients_db[client_id]['is_active'] = False
        
        return {'success': True, 'message': 'Sesión detenida'}
    
    def delete_client(self, client_id):
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        if client_id in self.client_sessions:
            del self.client_sessions[client_id]
        if client_id in self.client_configs:
            del self.client_configs[client_id]
        del self.clients_db[client_id]
        
        return {'success': True, 'message': 'Cliente eliminado'}
    
    def get_client_status(self, client_id):
        if client_id not in self.clients_db:
            return None
        
        client_data = self.clients_db[client_id].copy()
        
        if client_id in self.client_sessions:
            session = self.client_sessions[client_id]
            end_time = datetime.fromisoformat(session['end_time'])
            remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
            
            client_data['session'] = {
                'time_limit_seconds': session['time_limit'],
                'start_time': session['start_time'],
                'end_time': session['end_time'],
                'remaining_seconds': remaining_seconds,
                'is_expired': remaining_seconds == 0
            }
        else:
            client_data['session'] = None
        
        client_data['config'] = self.client_configs.get(client_id, self.DEFAULT_CONFIG.copy())
        return client_data
    
    def set_client_config(self, client_id, sync_interval=None, alert_thresholds=None, custom_name=None):
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        current_config = self.client_configs.get(client_id, self.DEFAULT_CONFIG.copy())
        
        if sync_interval is not None:
            if sync_interval < 5:
                return {'success': False, 'message': 'El intervalo mínimo es 5 segundos'}
            current_config['sync_interval'] = sync_interval
        
        if alert_thresholds is not None:
            if isinstance(alert_thresholds, list):
                current_config['alert_thresholds'] = sorted(alert_thresholds, reverse=True)
        
        if custom_name is not None:
            if custom_name:
                custom_name = str(custom_name).strip()[:50]
                current_config['custom_name'] = custom_name
                self.clients_db[client_id]['name'] = custom_name
            else:
                current_config['custom_name'] = None
        
        self.client_configs[client_id] = current_config
        
        return {'success': True, 'message': 'Configuración actualizada', 'config': current_config}
    
    def report_session(self, client_id, remaining_seconds, time_limit_seconds=None):
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        if remaining_seconds <= 0:
            return {'success': False, 'message': 'El tiempo debe ser mayor a 0'}
        
        time_limit = time_limit_seconds or remaining_seconds
        end_time = datetime.now() + timedelta(seconds=remaining_seconds)
        start_time = end_time - timedelta(seconds=time_limit)
        
        self.client_sessions[client_id] = {
            'time_limit': time_limit,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat()
        }
        self.clients_db[client_id]['is_active'] = True
        
        return {'success': True, 'message': f'Sesión reportada'}
    
    @staticmethod
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "No conectado"


# ============== FUNCIONES PARA LA UI NATIVA (Kotlin) ==============

def get_manager():
    """Obtiene la instancia singleton del ClientManager."""
    return ClientManager()

def get_clients_json():
    """Obtiene los clientes como JSON string."""
    return json.dumps(get_manager().get_clients())

def set_client_time(client_id, time_value, time_unit='minutes'):
    """Establece el tiempo de un cliente."""
    return json.dumps(get_manager().set_client_time(client_id, time_value, time_unit))

def stop_client_session(client_id):
    """Detiene la sesión de un cliente."""
    return json.dumps(get_manager().stop_client_session(client_id))

def delete_client(client_id):
    """Elimina un cliente."""
    return json.dumps(get_manager().delete_client(client_id))

def set_client_name(client_id, new_name):
    """Cambia el nombre de un cliente."""
    result = get_manager().set_client_config(client_id, custom_name=new_name)
    return json.dumps(result)

def set_client_config(client_id, sync_interval=None, alert_thresholds=None):
    """Actualiza la configuración de un cliente."""
    # Convertir alert_thresholds si viene como lista de Python
    if alert_thresholds is not None:
        if isinstance(alert_thresholds, (list, tuple)):
            alert_thresholds = list(alert_thresholds)
        else:
            # Si viene como string o otro tipo, intentar convertir
            alert_thresholds = None
    
    result = get_manager().set_client_config(
        client_id, 
        sync_interval=sync_interval, 
        alert_thresholds=alert_thresholds
    )
    return json.dumps(result)

def get_local_ip():
    """Obtiene la IP local."""
    return ClientManager.get_local_ip()

def get_client_count():
    """Obtiene el número de clientes."""
    return len(get_manager().clients_db)


# ============== SERVIDOR HTTP NATIVO (para clientes remotos) ==============

class CiberMondayHandler(BaseHTTPRequestHandler):
    """Handler HTTP para la API de CiberMonday."""
    
    manager = None
    
    def log_message(self, format, *args):
        """Log de requests."""
        print(f"[CiberMonday HTTP] {args[0]}")
    
    def _set_headers(self, status=200, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def _send_json(self, data, status=200):
        self._set_headers(status)
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def _read_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            return json.loads(body.decode('utf-8'))
        return {}
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self._set_headers(200)
    
    def do_GET(self):
        """Handle GET requests."""
        path = self.path.split('?')[0]
        
        if path == '/' or path == '/status':
            # Página HTML con estado del servidor
            ip = ClientManager.get_local_ip()
            clients = self.manager.get_clients()
            active = len([c for c in clients if c.get('is_active')])
            
            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CiberMonday Server</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
               min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }}
        .container {{ max-width: 600px; margin: 0 auto; }}
        .card {{ background: white; border-radius: 16px; padding: 24px; margin-bottom: 16px; 
                box-shadow: 0 4px 20px rgba(0,0,0,0.15); }}
        .status {{ display: flex; align-items: center; gap: 12px; }}
        .status-dot {{ width: 16px; height: 16px; background: #22c55e; border-radius: 50%; 
                      animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        h1 {{ margin: 0 0 8px 0; color: #1f2937; font-size: 24px; }}
        .subtitle {{ color: #6b7280; margin: 0; }}
        .info {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 20px; }}
        .info-item {{ background: #f3f4f6; padding: 16px; border-radius: 12px; text-align: center; }}
        .info-value {{ font-size: 28px; font-weight: bold; color: #1f2937; }}
        .info-label {{ color: #6b7280; font-size: 14px; }}
        .endpoint {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; 
                    padding: 12px; margin: 8px 0; font-family: monospace; font-size: 14px; }}
        .method {{ background: #3b82f6; color: white; padding: 2px 8px; border-radius: 4px; 
                  font-size: 12px; margin-right: 8px; }}
        .method.post {{ background: #22c55e; }}
        .method.delete {{ background: #ef4444; }}
        h2 {{ color: #1f2937; font-size: 18px; margin: 0 0 12px 0; }}
        .clients {{ margin-top: 16px; }}
        .client {{ background: #f9fafb; padding: 12px; border-radius: 8px; margin: 8px 0; 
                  display: flex; justify-content: space-between; align-items: center; }}
        .client-name {{ font-weight: 500; }}
        .client-status {{ font-size: 12px; padding: 4px 8px; border-radius: 4px; }}
        .client-status.active {{ background: #dcfce7; color: #166534; }}
        .client-status.inactive {{ background: #f3f4f6; color: #6b7280; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="status">
                <div class="status-dot"></div>
                <div>
                    <h1>CiberMonday Server</h1>
                    <p class="subtitle">Servidor activo en {ip}:5000</p>
                </div>
            </div>
            <div class="info">
                <div class="info-item">
                    <div class="info-value">{len(clients)}</div>
                    <div class="info-label">Clientes Totales</div>
                </div>
                <div class="info-item">
                    <div class="info-value">{active}</div>
                    <div class="info-label">Sesiones Activas</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>Clientes Registrados</h2>
            <div class="clients">
                {"".join([f'<div class="client"><span class="client-name">{c["name"]}</span><span class="client-status {"active" if c.get("is_active") else "inactive"}">{"Activo" if c.get("is_active") else "Inactivo"}</span></div>' for c in clients]) if clients else '<p style="color: #6b7280; text-align: center;">No hay clientes registrados</p>'}
            </div>
        </div>
        
        <div class="card">
            <h2>API Endpoints</h2>
            <div class="endpoint"><span class="method">GET</span>/api/health</div>
            <div class="endpoint"><span class="method">GET</span>/api/clients</div>
            <div class="endpoint"><span class="method post">POST</span>/api/register</div>
            <div class="endpoint"><span class="method">GET</span>/api/client/&lt;id&gt;/status</div>
            <div class="endpoint"><span class="method post">POST</span>/api/client/&lt;id&gt;/set-time</div>
            <div class="endpoint"><span class="method post">POST</span>/api/client/&lt;id&gt;/stop</div>
            <div class="endpoint"><span class="method delete">DELETE</span>/api/client/&lt;id&gt;</div>
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 10000);</script>
</body>
</html>'''
            self._set_headers(200, 'text/html')
            self.wfile.write(html.encode('utf-8'))
        
        elif path == '/api/health':
            self._send_json({
                'status': 'ok',
                'active_clients': len(self.manager.client_sessions),
                'total_clients': len(self.manager.clients_db)
            })
        
        elif path == '/api/clients':
            self._send_json({
                'success': True,
                'clients': self.manager.get_clients()
            })
        
        elif path == '/api/server-info':
            ip = ClientManager.get_local_ip()
            self._send_json({
                'success': True,
                'ip': ip,
                'port': 5000,
                'url': f"http://{ip}:5000"
            })
        
        elif path.startswith('/api/client/') and path.endswith('/status'):
            client_id = path.split('/')[3]
            client = self.manager.get_client_status(client_id)
            if client:
                self._send_json({'success': True, 'client': client})
            else:
                self._send_json({'success': False, 'message': 'Cliente no encontrado'}, 404)
        
        elif path.startswith('/api/client/') and path.endswith('/config'):
            client_id = path.split('/')[3]
            config = self.manager.client_configs.get(client_id)
            if config:
                self._send_json({'success': True, 'config': config})
            else:
                self._send_json({'success': False, 'message': 'Cliente no encontrado'}, 404)
        
        else:
            self._send_json({'error': 'Not found'}, 404)
    
    def do_POST(self):
        """Handle POST requests."""
        path = self.path.split('?')[0]
        data = self._read_body()
        
        if path == '/api/register':
            result = self.manager.register_client(
                name=data.get('name', 'Cliente Sin Nombre'),
                client_id=data.get('client_id'),
                session_data=data.get('session'),
                config=data.get('config')
            )
            self._send_json(result, 201)
        
        elif path.startswith('/api/client/') and path.endswith('/set-time'):
            client_id = path.split('/')[3]
            result = self.manager.set_client_time(
                client_id,
                data.get('time', 0),
                data.get('unit', 'minutes')
            )
            self._send_json(result, 200 if result['success'] else 400)
        
        elif path.startswith('/api/client/') and path.endswith('/config'):
            client_id = path.split('/')[3]
            result = self.manager.set_client_config(
                client_id,
                sync_interval=data.get('sync_interval'),
                alert_thresholds=data.get('alert_thresholds'),
                custom_name=data.get('custom_name')
            )
            self._send_json(result, 200 if result['success'] else 400)
        
        elif path.startswith('/api/client/') and path.endswith('/report-session'):
            client_id = path.split('/')[3]
            result = self.manager.report_session(
                client_id,
                data.get('remaining_seconds', 0),
                data.get('time_limit_seconds')
            )
            self._send_json(result, 200 if result['success'] else 400)
        
        elif path.startswith('/api/client/') and path.endswith('/stop'):
            client_id = path.split('/')[3]
            result = self.manager.stop_client_session(client_id)
            self._send_json(result)
        
        else:
            self._send_json({'error': 'Not found'}, 404)
    
    def do_DELETE(self):
        """Handle DELETE requests."""
        path = self.path.split('?')[0]
        
        # DELETE /api/client/<client_id>
        match = re.match(r'^/api/client/([^/]+)$', path)
        if match:
            client_id = match.group(1)
            result = self.manager.delete_client(client_id)
            self._send_json(result, 200 if result['success'] else 404)
        else:
            self._send_json({'error': 'Not found'}, 404)


class ThreadedHTTPServer(HTTPServer):
    """HTTPServer que maneja requests en threads separados."""
    allow_reuse_address = True
    
    def process_request(self, request, client_address):
        """Procesa cada request en un thread separado."""
        thread = threading.Thread(target=self._handle_request_thread, args=(request, client_address))
        thread.daemon = True
        thread.start()
    
    def _handle_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


# Variable global para el servidor
_server = None
_server_running = False
_server_error = None

def start_server(host='0.0.0.0', port=5000, data_dir=None):
    """Inicia el servidor HTTP."""
    global _server, _server_running, _server_error
    _server_running = True
    _server_error = None
    
    try:
        print(f"[CiberMonday] Iniciando servidor HTTP en {host}:{port}")
        
        # Configurar el handler con el manager
        CiberMondayHandler.manager = get_manager()
        
        # Crear el servidor
        _server = ThreadedHTTPServer((host, port), CiberMondayHandler)
        
        print(f"[CiberMonday] Servidor escuchando en {host}:{port}")
        
        # Ejecutar el servidor
        _server.serve_forever()
        
    except Exception as e:
        _server_error = str(e)
        _server_running = False
        print(f"[CiberMonday] ERROR al iniciar servidor: {e}")
        import traceback
        traceback.print_exc()
        raise e

def stop_server():
    """Detiene el servidor HTTP."""
    global _server, _server_running
    _server_running = False
    if _server:
        _server.shutdown()
        _server = None
    print("[CiberMonday] Servidor detenido")

def is_server_running():
    """Verifica si el servidor está corriendo."""
    return _server_running

def get_server_error():
    """Obtiene el último error del servidor."""
    return _server_error or ""

def test_server_connection():
    """Prueba si el servidor está respondiendo localmente."""
    import urllib.request
    try:
        response = urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=2)
        return response.read().decode('utf-8')
    except Exception as e:
        return f"Error: {str(e)}"
