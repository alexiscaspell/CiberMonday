"""
CiberMonday para Android - Módulo unificado
API HTTP para clientes + panel admin (Expo static en admin_static/).
Usa ClientManager de core/ compartido con el servidor web.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import mimetypes
import os
import threading

from core import ClientManager


# ============== SINGLETON DEL MANAGER ==============

_manager_instance = None
_manager_lock = threading.Lock()
_ADMIN_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'admin_static')


def get_manager():
    """Obtiene la instancia singleton del ClientManager."""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = ClientManager()
    return _manager_instance


# ============== HELPERS (compat / diagnóstico) ==============

def get_clients_json():
    return json.dumps(get_manager().get_clients())


def set_client_time(client_id, time_value, time_unit='minutes'):
    return json.dumps(get_manager().set_client_time(client_id, time_value, time_unit))


def stop_client_session(client_id):
    return json.dumps(get_manager().stop_client_session(client_id))


def delete_client(client_id):
    return json.dumps(get_manager().delete_client(client_id))


def set_client_name(client_id, new_name):
    """Cambia el nombre de un cliente."""
    result = get_manager().set_client_config(client_id, custom_name=new_name)
    return json.dumps(result)


def get_servers_json():
    """Obtiene los servidores conocidos como JSON string."""
    return json.dumps(get_manager().get_servers())


def set_client_config(client_id, sync_interval=None, alert_thresholds=None,
                      max_server_timeouts=None, lock_recheck_interval=None):
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
    
    if lock_recheck_interval is not None:
        try:
            lock_recheck_interval = int(lock_recheck_interval)
        except (ValueError, TypeError):
            lock_recheck_interval = None
    
    result = get_manager().set_client_config(
        client_id,
        sync_interval=sync_interval,
        alert_thresholds=alert_thresholds,
        max_server_timeouts=max_server_timeouts,
        lock_recheck_interval=lock_recheck_interval
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

    def _serve_admin_static(self, path):
        """Sirve el panel Expo desde admin_static/ (SPA)."""
        rel = path.lstrip('/')
        if not rel or rel == 'status':
            rel = 'index.html'

        base = os.path.normpath(_ADMIN_STATIC)
        full = os.path.normpath(os.path.join(base, rel))
        if not full.startswith(base + os.sep) and full != base:
            self._send_json({'error': 'Forbidden'}, 403)
            return True

        if not os.path.isfile(full):
            full = os.path.join(base, 'index.html')
            if not os.path.isfile(full):
                self._set_headers(503, 'text/html; charset=utf-8')
                self.wfile.write(
                    b'<html><body><h1>Panel no construido</h1>'
                    b'<p>Ejecut&aacute; scripts/build_admin.sh</p></body></html>'
                )
                return True

        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype in (
            'application/javascript',
            'application/json',
            'image/svg+xml',
        ):
            ctype = f'{ctype}; charset=utf-8'

        with open(full, 'rb') as f:
            data = f.read()
        self._set_headers(200, ctype)
        self.wfile.write(data)
        return True

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self._set_headers(200)
    
    def do_GET(self):
        """Handle GET requests."""
        path = self.path.split('?')[0]
        
        if not path.startswith('/api/'):
            self._serve_admin_static(path)
            return
        
        if path == '/api/health':
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
            from_client = data.get('from_client', False)
            result = self.manager.set_client_config(
                client_id,
                sync_interval=data.get('sync_interval'),
                alert_thresholds=data.get('alert_thresholds'),
                custom_name=data.get('custom_name'),
                max_server_timeouts=data.get('max_server_timeouts'),
                lock_recheck_interval=data.get('lock_recheck_interval'),
                notify_client=not from_client
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
                'known_clients': self.manager.get_clients_sync_payload(),
            }, 200)
        
        elif path == '/api/force-sync':
            try:
                self.manager._sync_with_other_servers()
                self._send_json({
                    'success': True,
                    'message': 'Sincronización forzada completada',
                    'known_servers': self.manager.get_servers(),
                    'known_clients': self.manager.get_clients_sync_payload(),
                }, 200)
            except Exception as e:
                self._send_json({
                    'success': False,
                    'message': f'Error durante sincronización: {str(e)}'
                }, 500)
        
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
    """Inicia broadcast UDP usando ClientManager.start_broadcast()."""
    get_manager().start_broadcast(
        stop_check=lambda: not _server_running
    )


def start_server(host='0.0.0.0', port=5000, data_dir=None):
    """Inicia el servidor HTTP."""
    global _server, _server_running, _server_error, _manager_instance
    _server_running = True
    _server_error = None
    
    try:
        print(f"[CiberMonday] Iniciando servidor HTTP en {host}:{port}")
        
        # Reutilizar manager si ya existe (no borrar clientes al volver a primer plano)
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = ClientManager(server_port=port)
            else:
                _manager_instance.server_port = port
        
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
    srv = _server
    _server = None
    if srv:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
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
