"""
CiberMonday para Android - Módulo unificado
Provee tanto la API HTTP (para clientes remotos) como acceso directo (para UI nativa).
Usa ClientManager de core/ para la lógica de negocio compartida con el servidor web.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import socket
import threading
import re
import time

from core import ClientManager


# ============== SINGLETON DEL MANAGER ==============

_manager_instance = None
_manager_lock = threading.Lock()


def get_manager():
    """Obtiene la instancia singleton del ClientManager."""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = ClientManager()
    return _manager_instance


# ============== FUNCIONES PARA LA UI NATIVA (Kotlin) ==============

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


def get_servers_json():
    """Obtiene los servidores conocidos como JSON string."""
    return json.dumps(get_manager().get_servers())


def set_client_config(client_id, sync_interval=None, alert_thresholds=None, max_server_timeouts=None):
    """Actualiza la configuración de un cliente."""
    if alert_thresholds is not None:
        if isinstance(alert_thresholds, (list, tuple)):
            alert_thresholds = list(alert_thresholds)
        else:
            alert_thresholds = None
    
    if max_server_timeouts is not None:
        try:
            max_server_timeouts = int(max_server_timeouts)
        except (ValueError, TypeError):
            max_server_timeouts = None
    
    result = get_manager().set_client_config(
        client_id,
        sync_interval=sync_interval,
        alert_thresholds=alert_thresholds,
        max_server_timeouts=max_server_timeouts
    )
    return json.dumps(result)


def get_local_ip():
    """Obtiene la IP local."""
    return ClientManager.get_local_ip()


def get_client_count():
    """Obtiene el número de clientes."""
    return len(get_manager().clients_db)


def get_server_config_json():
    """Obtiene la configuración del servidor como JSON string."""
    return json.dumps({
        'success': True,
        'config': get_manager().get_server_config()
    })


def set_server_config(broadcast_interval):
    """Actualiza la configuración del servidor."""
    result = get_manager().set_server_config(broadcast_interval=broadcast_interval)
    return json.dumps(result)


def register_server_manual(server_url, server_ip=None, server_port=None):
    """Registra un servidor manualmente desde la UI."""
    mgr = get_manager()
    result = mgr.register_server(server_url, server_ip, server_port)
    
    if result.get('success') and len(mgr.clients_db) > 0:
        print(f"[Servidor] Nuevo servidor {server_url} agregado manualmente. Los clientes lo recibirán en su próxima sincronización.")
    
    return json.dumps(result)


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
            ip = self.manager.get_local_ip()
            port = self.manager.server_port
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
                    <p class="subtitle">Servidor activo en {ip}:{port}</p>
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
            stats = self.manager.get_stats()
            self._send_json({
                'status': 'ok',
                'active_clients': stats['active_clients'],
                'total_clients': stats['total_clients']
            })
        
        elif path == '/api/clients':
            self._send_json({
                'success': True,
                'clients': self.manager.get_clients()
            })
        
        elif path == '/api/server-info':
            ip = self.manager.get_local_ip()
            config = self.manager.get_server_config()
            port = self.manager.server_port
            self._send_json({
                'success': True,
                'ip': ip,
                'port': port,
                'url': f"http://{ip}:{port}",
                'broadcast_interval': config['broadcast_interval']
            })
        
        elif path == '/api/servers':
            self._send_json({
                'success': True,
                'servers': self.manager.get_servers()
            })
        
        elif path == '/api/server-config':
            self._send_json({
                'success': True,
                'config': self.manager.get_server_config()
            })
        
        elif path.startswith('/api/client/') and path.endswith('/status'):
            client_id = path.split('/')[3]
            client = self.manager.get_client_status(client_id)
            if client:
                self._send_json({
                    'success': True,
                    'client': client,
                    'known_servers': self.manager.get_servers()
                })
            else:
                self._send_json({'success': False, 'message': 'Cliente no encontrado'}, 404)
        
        elif path.startswith('/api/client/') and path.endswith('/config'):
            client_id = path.split('/')[3]
            config = self.manager.get_client_config(client_id)
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
            # Obtener IP del cliente desde los datos o desde la conexión
            client_ip = data.get('client_ip') or self.client_address[0]
            diagnostic_port = data.get('diagnostic_port', 5002)
            
            result = self.manager.register_client(
                name=data.get('name', 'Cliente Sin Nombre'),
                client_id=data.get('client_id'),
                session_data=data.get('session'),
                config=data.get('config'),
                known_servers=data.get('known_servers', []),
                client_ip=client_ip,
                diagnostic_port=diagnostic_port
            )
            
            # Actualizar info de contacto del cliente
            if result['success']:
                cid = result['client_id']
                if cid in self.manager.clients_db:
                    self.manager.clients_db[cid]['client_ip'] = client_ip
                    self.manager.clients_db[cid]['diagnostic_port'] = diagnostic_port
            
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
                custom_name=data.get('custom_name'),
                max_server_timeouts=data.get('max_server_timeouts')
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
        
        elif path == '/api/register-server':
            server_url = data.get('url')
            if not server_url:
                self._send_json({'success': False, 'message': 'URL del servidor requerida'}, 400)
            else:
                # Verificar si es un servidor nuevo
                server_exists = any(
                    sd.get('url') == server_url for sd in self.manager.servers_db.values()
                )
                
                result = self.manager.register_server(
                    server_url,
                    data.get('ip'),
                    data.get('port')
                )
                result['known_servers'] = self.manager.get_servers()
                
                # Si es un nuevo servidor, sincronizar clientes entre servidores
                if not server_exists:
                    try:
                        self.manager._sync_with_other_servers()
                    except Exception as e:
                        print(f"[Servidor] Error al sincronizar con otros servidores: {e}")
                
                self._send_json(result, 201)
        
        elif path == '/api/sync-servers':
            servers_list = data.get('servers', [])
            clients_list = data.get('clients', [])
            
            known_servers = self.manager.sync_servers(servers_list)
            
            if clients_list:
                self.manager.sync_clients_from_remote(clients_list)
            
            self._send_json({
                'success': True,
                'known_servers': known_servers,
                'known_clients': self.manager.get_clients()
            }, 200)
        
        elif path == '/api/server-config':
            result = self.manager.set_server_config(
                broadcast_interval=data.get('broadcast_interval')
            )
            self._send_json(result, 200 if result['success'] else 400)
        
        else:
            self._send_json({'error': 'Not found'}, 404)
    
    def do_DELETE(self):
        """Handle DELETE requests."""
        path = self.path.split('?')[0]
        
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


# ============== SERVIDOR Y BROADCAST ==============

_server = None
_server_running = False
_server_error = None


def broadcast_server_presence(server_port=5000):
    """
    Hace broadcast UDP para anunciar la presencia de este servidor a los clientes.
    Los clientes escuchan en el puerto 5001 y registran automáticamente nuevos servidores.
    """
    def broadcast_thread():
        DISCOVERY_PORT = 5001
        mgr = get_manager()
        
        try:
            local_ip = mgr.get_local_ip()
            if local_ip == "127.0.0.1" or not local_ip:
                print(f"[Broadcast] IP no válida para broadcast: {local_ip}")
                return
            
            server_url = f"http://{local_ip}:{server_port}"
            server_info_data = {
                'url': server_url,
                'ip': local_ip,
                'port': server_port
            }
            
            broadcast_addr = mgr.get_broadcast_address(local_ip)
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                sock.bind(('', 0))
            except Exception as bind_error:
                print(f"[Broadcast] Advertencia al hacer bind: {bind_error}")
            
            config = mgr.get_server_config()
            print(f"[Broadcast] Iniciando anuncios de servidor en {local_ip}:{server_port}")
            print(f"[Broadcast] Dirección de broadcast: {broadcast_addr}:{DISCOVERY_PORT}")
            print(f"[Broadcast] Enviando broadcasts UDP cada {config['broadcast_interval']} segundos")
            print(f"[Broadcast] Los broadcasts se detendrán automáticamente cuando haya clientes conectados")
            
            # Direcciones de broadcast a intentar (subred específica + broadcast general)
            broadcast_targets = [broadcast_addr]
            if broadcast_addr != "255.255.255.255":
                broadcast_targets.append("255.255.255.255")
            
            last_client_count = 0
            broadcasts_paused = False
            last_error_logged = 0
            
            while _server_running:
                try:
                    config = mgr.get_server_config()
                    num_clients = len(mgr.clients_db)
                    
                    if num_clients > 0:
                        if not broadcasts_paused:
                            print(f"[Broadcast] Hay {num_clients} cliente(s) conectado(s). Broadcasts pausados.")
                            broadcasts_paused = True
                        elif num_clients != last_client_count:
                            print(f"[Broadcast] {num_clients} cliente(s) conectado(s). Broadcasts siguen pausados.")
                        last_client_count = num_clients
                        time.sleep(config['broadcast_interval'])
                        continue
                    else:
                        if broadcasts_paused:
                            print(f"[Broadcast] No hay clientes conectados. Reanudando broadcasts UDP.")
                            broadcasts_paused = False
                        last_client_count = 0
                    
                    message = json.dumps(server_info_data).encode('utf-8')
                    sent = False
                    for target_addr in broadcast_targets:
                        try:
                            sock.sendto(message, (target_addr, DISCOVERY_PORT))
                            sent = True
                            break
                        except OSError:
                            continue
                    
                    if sent:
                        last_error_logged = 0
                    else:
                        # Todos los targets fallaron - recrear socket e intentar una vez más
                        try:
                            sock.close()
                        except Exception:
                            pass
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        sock.bind(('', 0))
                        try:
                            sock.sendto(message, ('255.255.255.255', DISCOVERY_PORT))
                            sent = True
                            last_error_logged = 0
                        except OSError as e:
                            now = time.time()
                            if now - last_error_logged > 30:
                                print(f"[Broadcast] No se pudo enviar broadcast: {e}")
                                last_error_logged = now
                    
                    time.sleep(config['broadcast_interval'])
                except Exception as e:
                    now = time.time()
                    if now - last_error_logged > 30:
                        print(f"[Broadcast] Error al enviar broadcast: {e}")
                        last_error_logged = now
                    time.sleep(config.get('broadcast_interval', 1))
        except Exception as e:
            print(f"[Broadcast] Error en thread de broadcast: {e}")
            import traceback
            traceback.print_exc()
    
    thread = threading.Thread(target=broadcast_thread, daemon=True)
    thread.start()


def start_server(host='0.0.0.0', port=5000, data_dir=None):
    """Inicia el servidor HTTP."""
    global _server, _server_running, _server_error, _manager_instance
    _server_running = True
    _server_error = None
    
    try:
        print(f"[CiberMonday] Iniciando servidor HTTP en {host}:{port}")
        
        # Crear manager con el puerto correcto
        with _manager_lock:
            _manager_instance = ClientManager(server_port=port)
        
        CiberMondayHandler.manager = get_manager()
        
        _server = ThreadedHTTPServer((host, port), CiberMondayHandler)
        
        print(f"[CiberMonday] Servidor escuchando en {host}:{port}")
        
        broadcast_server_presence(server_port=port)
        
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
        mgr = get_manager()
        port = mgr.server_port
        response = urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2)
        return response.read().decode('utf-8')
    except Exception as e:
        return f"Error: {str(e)}"
