"""
CiberMonday - Gestor de Clientes y Servidores
Lógica de negocio pura, sin dependencias de Flask/HTTP.
Reutilizable por el servidor web y la app Android.
"""

from datetime import datetime, timedelta
import uuid
import json
import socket
import hashlib
import urllib.request
import urllib.error
from urllib.parse import urlparse


class ClientManager:
    """
    Gestiona los clientes del ciber, sus sesiones de tiempo,
    configuración y la lista de servidores conocidos.
    """
    
    DEFAULT_CONFIG = {
        'sync_interval': 30,
        'alert_thresholds': [600, 300, 120, 60],
        'custom_name': None,
        'max_server_timeouts': 10,
    }
    
    def __init__(self, server_port=5000):
        self.clients_db = {}
        self.client_sessions = {}
        self.client_configs = {}
        self.servers_db = {}
        self.server_config = {
            'broadcast_interval': 1
        }
        self.server_port = server_port
        self._local_server_url = None
    
    @property
    def local_server_url(self):
        """URL del servidor local. Se usa para no sincronizar consigo mismo."""
        if self._local_server_url:
            return self._local_server_url
        local_ip = self.get_local_ip()
        if local_ip and local_ip != "127.0.0.1":
            return f"http://{local_ip}:{self.server_port}"
        return None
    
    @local_server_url.setter
    def local_server_url(self, url):
        self._local_server_url = url
    
    # ==================== CLIENT MANAGEMENT ====================
    
    def _generate_client_id(self):
        """Genera un ID único para cada cliente."""
        return str(uuid.uuid4())
    
    def register_client(self, name='Cliente Sin Nombre', client_id=None, 
                        session_data=None, config=None, known_servers=None,
                        client_ip=None, diagnostic_port=None):
        """
        Registra un nuevo cliente o re-registra uno existente.
        
        Args:
            name: Nombre del cliente
            client_id: ID existente para re-registro (opcional)
            session_data: Datos de sesión activa para restaurar (opcional)
            config: Configuración del cliente (opcional)
            known_servers: Lista de servidores conocidos por el cliente (opcional)
            client_ip: IP del cliente para notificaciones push (opcional)
            diagnostic_port: Puerto de diagnóstico del cliente (opcional)
            
        Returns:
            dict con success, client_id, message, session_restored, config, known_servers
        """
        is_reregister = client_id is not None
        if not is_reregister:
            client_id = self._generate_client_id()
        
        client_data = {
            'id': client_id,
            'name': name,
            'registered_at': datetime.now().isoformat(),
            'total_time_used': 0,
            'is_active': False
        }
        
        # Guardar IP y puerto de diagnóstico si se proporcionan
        if client_ip:
            client_data['client_ip'] = client_ip
        if diagnostic_port:
            client_data['diagnostic_port'] = diagnostic_port
        
        self.clients_db[client_id] = client_data
        
        # Configuración
        if config:
            self.client_configs[client_id] = {
                'sync_interval': config.get('sync_interval', self.DEFAULT_CONFIG['sync_interval']),
                'alert_thresholds': config.get('alert_thresholds', self.DEFAULT_CONFIG['alert_thresholds']),
                'custom_name': config.get('custom_name'),
                'max_server_timeouts': config.get('max_server_timeouts', self.DEFAULT_CONFIG['max_server_timeouts']),
            }
            if self.client_configs[client_id]['custom_name']:
                self.clients_db[client_id]['name'] = self.client_configs[client_id]['custom_name']
        elif client_id not in self.client_configs:
            self.client_configs[client_id] = self.DEFAULT_CONFIG.copy()
        
        # Restaurar sesión si se proporcionó
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
        
        # Registrar servidores conocidos del cliente
        if known_servers:
            for server in known_servers:
                server_url = server.get('url')
                if server_url:
                    self.register_server(server_url, server.get('ip'), server.get('port'))
        
        # Auto-registrar el servidor local
        local_ip = self.get_local_ip()
        if local_ip and local_ip != "127.0.0.1":
            local_url = f"http://{local_ip}:{self.server_port}"
            self.register_server(local_url, local_ip, self.server_port)
        
        message = 'Cliente re-registrado' if is_reregister else 'Cliente registrado'
        print(f"[Registro] {message}: {client_id[:8]}... nombre={name}")
        
        return {
            'success': True,
            'client_id': client_id,
            'message': message,
            'session_restored': session_restored,
            'config': self.client_configs.get(client_id, self.DEFAULT_CONFIG),
            'known_servers': self.get_servers()
        }
    
    def get_clients(self):
        """
        Obtiene la lista de todos los clientes con sus sesiones y configuración.
        
        Returns:
            list de diccionarios con info de cada cliente
        """
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
    
    def get_client_status(self, client_id):
        """
        Obtiene el estado de un cliente específico.
        
        Returns:
            dict con info del cliente o None si no existe
        """
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
    
    def set_client_time(self, client_id, time_value, time_unit='minutes'):
        """
        Establece el tiempo de uso para un cliente.
        
        Args:
            client_id: ID del cliente
            time_value: Cantidad de tiempo
            time_unit: 'minutes' o 'hours'
            
        Returns:
            dict con success, message, session
        """
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
            'message': f'Tiempo establecido: {time_value} {time_unit}',
            'session': {
                'time_limit_seconds': total_seconds,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat()
            }
        }
    
    def stop_client_session(self, client_id):
        """
        Detiene la sesión de un cliente.
        
        Returns:
            dict con success, message
        """
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
        """
        Elimina un cliente del sistema.
        
        Returns:
            dict con success, message
        """
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        if client_id in self.client_sessions:
            del self.client_sessions[client_id]
        if client_id in self.client_configs:
            del self.client_configs[client_id]
        del self.clients_db[client_id]
        
        return {'success': True, 'message': 'Cliente eliminado'}
    
    # ==================== CLIENT CONFIG ====================
    
    def get_client_config(self, client_id):
        """Obtiene la configuración de un cliente."""
        if client_id not in self.clients_db:
            return None
        return self.client_configs.get(client_id, self.DEFAULT_CONFIG.copy())
    
    def set_client_config(self, client_id, sync_interval=None, alert_thresholds=None,
                          custom_name=None, max_server_timeouts=None):
        """
        Modifica la configuración de un cliente.
        
        Returns:
            dict con success, message, config
        """
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        current_config = self.client_configs.get(client_id, self.DEFAULT_CONFIG.copy())
        
        if sync_interval is not None:
            sync_interval = int(sync_interval)
            if sync_interval < 5:
                return {'success': False, 'message': 'El intervalo de sincronización mínimo es 5 segundos'}
            current_config['sync_interval'] = sync_interval
        
        if alert_thresholds is not None:
            if isinstance(alert_thresholds, list) and all(isinstance(t, int) and t > 0 for t in alert_thresholds):
                current_config['alert_thresholds'] = sorted(alert_thresholds, reverse=True)
            else:
                return {'success': False, 'message': 'Los umbrales de alerta deben ser una lista de números positivos'}
        
        if custom_name is not None:
            if custom_name:
                custom_name = str(custom_name).strip()[:50]
                current_config['custom_name'] = custom_name
                self.clients_db[client_id]['name'] = custom_name
            else:
                current_config['custom_name'] = None
        
        if max_server_timeouts is not None:
            max_server_timeouts = int(max_server_timeouts)
            if max_server_timeouts < 1:
                return {'success': False, 'message': 'Los reintentos antes de eliminar servidor deben ser al menos 1'}
            if max_server_timeouts > 100:
                return {'success': False, 'message': 'Los reintentos antes de eliminar servidor no deben ser mayor a 100'}
            current_config['max_server_timeouts'] = max_server_timeouts
        
        self.client_configs[client_id] = current_config
        
        print(f"[Config] Cliente {client_id[:8]}... configuración actualizada: {current_config}")
        
        return {
            'success': True,
            'message': 'Configuración actualizada',
            'config': current_config
        }
    
    # ==================== SESSION REPORTING ====================
    
    def report_session(self, client_id, remaining_seconds, time_limit_seconds=None):
        """
        Permite a un cliente reportar su sesión activa.
        
        Returns:
            dict con success, message, session
        """
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
        
        return {
            'success': True,
            'message': f'Sesión reportada: {remaining_seconds}s restantes',
            'session': {
                'time_limit_seconds': time_limit,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'remaining_seconds': remaining_seconds
            }
        }
    
    # ==================== SERVER MANAGEMENT ====================
    
    def register_server(self, server_url, server_ip=None, server_port=None):
        """
        Registra o actualiza un servidor conocido.
        
        Returns:
            dict con success, server_id
        """
        server_id = hashlib.md5(server_url.encode()).hexdigest()[:16]
        
        # Parsear URL si no se proporcionan IP y puerto
        if not server_ip or not server_port:
            try:
                parsed = urlparse(server_url)
                server_ip = server_ip or parsed.hostname or "unknown"
                server_port = server_port or parsed.port or 5000
            except Exception:
                server_ip = server_ip or "unknown"
                server_port = server_port or 5000
        
        self.servers_db[server_id] = {
            'id': server_id,
            'url': server_url,
            'ip': server_ip,
            'port': server_port,
            'last_seen': datetime.now().isoformat(),
            'is_active': True
        }
        
        return {'success': True, 'server_id': server_id}
    
    def get_servers(self):
        """Obtiene la lista de servidores conocidos."""
        servers_list = []
        for server_id, server_data in self.servers_db.items():
            servers_list.append(server_data.copy())
        return servers_list
    
    def sync_servers(self, servers_list):
        """
        Sincroniza la lista de servidores con otros servidores.
        
        Args:
            servers_list: Lista de servidores recibida de otro servidor/cliente
            
        Returns:
            Lista combinada de servidores conocidos
        """
        for server_data in servers_list:
            server_url = server_data.get('url')
            if server_url:
                self.register_server(
                    server_url,
                    server_data.get('ip'),
                    server_data.get('port')
                )
        
        self._sync_with_other_servers()
        return self.get_servers()
    
    def sync_clients_from_remote(self, clients_list):
        """
        Registra clientes recibidos de otros servidores si no existen localmente.
        
        Args:
            clients_list: Lista de clientes de otro servidor
        """
        for client_data in clients_list:
            client_id = client_data.get('id')
            if client_id and client_id not in self.clients_db:
                self.clients_db[client_id] = {
                    'id': client_id,
                    'name': client_data.get('name', 'Cliente Remoto'),
                    'registered_at': datetime.now().isoformat(),
                    'total_time_used': 0,
                    'is_active': False
                }
                if client_id not in self.client_configs:
                    self.client_configs[client_id] = self.DEFAULT_CONFIG.copy()
    
    def _sync_with_other_servers(self):
        """Sincroniza información con otros servidores conocidos."""
        my_url = self.local_server_url
        if not my_url:
            return
        
        sync_data = {
            'servers': self.get_servers(),
            'clients': self.get_clients()
        }
        
        for server_id, server_data in list(self.servers_db.items()):
            server_url = server_data.get('url')
            if not server_url or server_url == my_url:
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
                        if response_data.get('known_servers'):
                            for other_server in response_data['known_servers']:
                                if other_server.get('url') != my_url:
                                    self.register_server(
                                        other_server.get('url'),
                                        other_server.get('ip'),
                                        other_server.get('port')
                                    )
            except Exception:
                pass
    
    # ==================== SERVER CONFIG ====================
    
    def get_server_config(self):
        """Obtiene la configuración del servidor."""
        return self.server_config.copy()
    
    def set_server_config(self, broadcast_interval=None):
        """
        Actualiza la configuración del servidor.
        
        Returns:
            dict con success, config, message
        """
        if broadcast_interval is not None:
            broadcast_interval = int(broadcast_interval)
            if broadcast_interval < 1:
                return {
                    'success': False,
                    'message': 'El intervalo de broadcast debe ser al menos 1 segundo'
                }
            self.server_config['broadcast_interval'] = broadcast_interval
            print(f"[Config] Intervalo de broadcast actualizado a {broadcast_interval} segundos")
        
        return {
            'success': True,
            'config': self.server_config.copy(),
            'message': 'Configuración actualizada correctamente'
        }
    
    # ==================== UTILITIES ====================
    
    def get_stats(self):
        """Obtiene estadísticas generales."""
        return {
            'total_clients': len(self.clients_db),
            'active_clients': len(self.client_sessions)
        }
    
    @staticmethod
    def get_local_ip():
        """Obtiene la IP local."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "127.0.0.1"
    
    @staticmethod
    def get_broadcast_address(ip_address=None):
        """
        Obtiene la dirección de broadcast de la red local.
        Si se proporciona ip_address, calcula el broadcast basado en esa IP.
        Si no, usa get_local_ip() para determinarlo automáticamente.
        Esto es importante en Docker donde get_local_ip() retorna la IP del container,
        pero queremos calcular el broadcast basado en la IP del host (HOST_IP).
        """
        try:
            if ip_address is None:
                ip_address = ClientManager.get_local_ip()
            if ip_address == "127.0.0.1":
                return "255.255.255.255"
            parts = ip_address.split('.')
            if len(parts) == 4:
                parts[3] = '255'
                return '.'.join(parts)
        except Exception:
            pass
        return "255.255.255.255"
    
    # ==================== SERIALIZATION ====================
    
    def to_json(self):
        """Serializa el estado a JSON."""
        return json.dumps({
            'clients_db': self.clients_db,
            'client_sessions': self.client_sessions,
            'client_configs': self.client_configs,
            'servers_db': self.servers_db,
            'server_config': self.server_config
        })
    
    def from_json(self, json_str):
        """Restaura el estado desde JSON."""
        data = json.loads(json_str)
        self.clients_db = data.get('clients_db', {})
        self.client_sessions = data.get('client_sessions', {})
        self.client_configs = data.get('client_configs', {})
        self.servers_db = data.get('servers_db', {})
        self.server_config = data.get('server_config', {'broadcast_interval': 1})
