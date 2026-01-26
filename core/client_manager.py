"""
CiberMonday - Gestor de Clientes
Lógica de negocio pura, sin dependencias de Flask/HTTP.
Reutilizable por el servidor web y la app Android.
"""

from datetime import datetime, timedelta
import uuid
import json
import socket


class ClientManager:
    """Gestiona los clientes del ciber y sus sesiones de tiempo."""
    
    DEFAULT_CONFIG = {
        'sync_interval': 30,
        'alert_thresholds': [600, 300, 120, 60],
        'custom_name': None,
    }
    
    def __init__(self):
        self.clients_db = {}
        self.client_sessions = {}
        self.client_configs = {}
    
    def _generate_client_id(self):
        """Genera un ID único para cada cliente."""
        return str(uuid.uuid4())
    
    def register_client(self, name='Cliente Sin Nombre', client_id=None, 
                        session_data=None, config=None):
        """
        Registra un nuevo cliente o re-registra uno existente.
        
        Args:
            name: Nombre del cliente
            client_id: ID existente para re-registro (opcional)
            session_data: Datos de sesión activa para restaurar (opcional)
            config: Configuración del cliente (opcional)
            
        Returns:
            dict con success, client_id, message, session_restored, config
        """
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
        
        # Configuración
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
        
        return {
            'success': True,
            'client_id': client_id,
            'message': 'Cliente re-registrado' if is_reregister else 'Cliente registrado',
            'session_restored': session_restored,
            'config': self.client_configs.get(client_id, self.DEFAULT_CONFIG)
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
    
    def get_client_config(self, client_id):
        """Obtiene la configuración de un cliente."""
        if client_id not in self.clients_db:
            return None
        return self.client_configs.get(client_id, self.DEFAULT_CONFIG.copy())
    
    def set_client_config(self, client_id, sync_interval=None, alert_thresholds=None, custom_name=None):
        """
        Modifica la configuración de un cliente.
        
        Returns:
            dict con success, message, config
        """
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        current_config = self.client_configs.get(client_id, self.DEFAULT_CONFIG.copy())
        
        if sync_interval is not None:
            if sync_interval < 5:
                return {'success': False, 'message': 'El intervalo mínimo es 5 segundos'}
            current_config['sync_interval'] = sync_interval
        
        if alert_thresholds is not None:
            if isinstance(alert_thresholds, list) and all(isinstance(t, int) and t > 0 for t in alert_thresholds):
                current_config['alert_thresholds'] = sorted(alert_thresholds, reverse=True)
        
        if custom_name is not None:
            if custom_name:
                custom_name = str(custom_name).strip()[:50]
                current_config['custom_name'] = custom_name
                self.clients_db[client_id]['name'] = custom_name
            else:
                current_config['custom_name'] = None
        
        self.client_configs[client_id] = current_config
        
        return {
            'success': True,
            'message': 'Configuración actualizada',
            'config': current_config
        }
    
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
    
    # Métodos para serialización (útil para persistencia)
    def to_json(self):
        """Serializa el estado a JSON."""
        return json.dumps({
            'clients_db': self.clients_db,
            'client_sessions': self.client_sessions,
            'client_configs': self.client_configs
        })
    
    def from_json(self, json_str):
        """Restaura el estado desde JSON."""
        data = json.loads(json_str)
        self.clients_db = data.get('clients_db', {})
        self.client_sessions = data.get('client_sessions', {})
        self.client_configs = data.get('client_configs', {})
