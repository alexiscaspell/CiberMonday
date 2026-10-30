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
import threading
import time
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
        'lock_recheck_interval': 1,
        'network_filter_enabled': False,
        'internet_request_enabled': False,
        'allowlist': [],
        # Hosts related descubiertos por tráfico (ocultos en UI admin)
        'allowlist_learned': [],
    }

    @staticmethod
    def _merge_learned(a, b):
        """Unión ordenada de allowlist_learned."""
        out = []
        seen = set()
        for raw in list(a or []) + list(b or []):
            e = str(raw or '').strip().lower().rstrip('.')
            if not e or e.startswith('#') or e in seen:
                continue
            seen.add(e)
            out.append(e)
        return out[:500]
    
    # Segundos durante los cuales un reporte del cliente es ignorado
    # después de un cambio de admin (para dar tiempo al push de llegar)
    ADMIN_CHANGE_GRACE_SECONDS = 90

    # Segundos sin contacto para considerar un cliente desconectado
    # (sync default 30s; tras lock puede haber huecos — margen amplio)
    CLIENT_OFFLINE_TIMEOUT = 120
    
    def __init__(self, server_port=5000):
        self.clients_db = {}
        self.client_sessions = {}
        self.internet_sessions = {}
        self.client_configs = {}
        self.servers_db = {}
        self.server_config = {
            'broadcast_interval': 1
        }
        self.server_port = server_port
        self._local_server_url = None
        # Trackea cambios de admin pendientes para evitar que el sync del
        # cliente sobreescriba antes de que el push llegue
        self._pending_admin_changes = {}  # client_id -> datetime
        # Pedidos de acceso a dominios fuera de allowlist
        self.access_requests = {}  # request_id -> dict

    # Ya no hay familias CDN hardcoded: el cliente solo permite lo listado
    # (y subdominios). Los hosts relacionados se descubren del tráfico vía
    # pedidos de acceso. Este mapa vacío mantiene el helper de colapso www/m.
    ALLOWLIST_FAMILIES = {}

    @staticmethod
    def _looks_like_allowlist_rule(item: str) -> bool:
        """True si el token parece dominio, *.wildcard, IP o CIDR."""
        if not item:
            return False
        if '/' in item:
            # CIDR IPv4
            host, _, prefix = item.partition('/')
            if not prefix.isdigit() or not (0 <= int(prefix) <= 32):
                return False
            item = host
        if item.startswith('*.') and len(item) > 2:
            item = item[2:]
        if item.replace('.', '').isdigit():
            parts = item.split('.')
            return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
        # dominio / hostname
        if '.' not in item and item not in ('localhost',):
            return False
        if item.startswith('.') or item.endswith('.'):
            return False
        allowed = set('abcdefghijklmnopqrstuvwxyz0123456789-.*')
        return all(c in allowed for c in item)

    @staticmethod
    def _entry_domain(entry: str):
        """Dominio de una entrada normalizada (`# foo` → foo), o None si es sección."""
        e = (entry or '').strip()
        if not e:
            return None
        if e.startswith('# ===') or (e.startswith('#') and not e.startswith('# ')):
            # sección u otro comentario no-regla
            rest = e[1:].strip()
            if not ClientManager._looks_like_allowlist_rule(
                rest.lower().split()[0] if rest else ''
            ):
                return None
        if e.startswith('# '):
            return e[2:].strip().lower() or None
        if e.startswith('#'):
            return e[1:].strip().lower() or None
        return e.lower()

    @classmethod
    def _collapse_implicit_family_domains(cls, entries):
        """Saca de la lista CDNs/www/m implícitos si el apex ya está (p.ej. github.com)."""
        if not entries:
            return entries
        enabled = set()
        for raw in entries:
            dom = cls._entry_domain(raw)
            if dom and not str(raw).strip().startswith('#'):
                enabled.add(dom)

        implied = set()
        for apex, members in cls.ALLOWLIST_FAMILIES.items():
            if apex not in enabled:
                continue
            for m in members:
                if m != apex:
                    implied.add(m)
                implied.add(f'www.{m}')
                implied.add(f'm.{m}')
            implied.add(f'www.{apex}')
            implied.add(f'm.{apex}')

        # www./m. de cualquier dominio explícito (no solo familias)
        for dom in list(enabled):
            if dom.startswith('www.') or dom.startswith('m.'):
                continue
            implied.add(f'www.{dom}')
            implied.add(f'm.{dom}')

        out = []
        seen = set()
        for raw in entries:
            dom = cls._entry_domain(raw)
            if dom is None:
                # comentario de sección
                if raw not in out:
                    out.append(raw)
                continue
            if dom in implied:
                continue
            key = dom
            if key in seen:
                continue
            seen.add(key)
            out.append(raw)
        return out

    @staticmethod
    def _normalize_allowlist(entries):
        """Normaliza allowlist: dominios, *.wildcards, IPs/CIDR.

        Formato estilo hosts:
        - dominio activo
        - ``# dominio`` = regla deshabilitada (se conserva)
        - ``# === sección ===`` = comentario (se conserva)
        - líneas en blanco se omiten
        - miembros de familias CDN (youtube/github/…) no se guardan si el apex ya está
        """
        if entries is None:
            return None
        if not isinstance(entries, list):
            raise ValueError('allowlist debe ser una lista de strings')
        looks = ClientManager._looks_like_allowlist_rule
        normalized = []
        seen_domains = set()
        for raw in entries:
            if raw is None:
                continue
            item = str(raw).strip()
            if not item:
                continue

            disabled = False
            if item.startswith('#'):
                rest = item[1:].strip()
                token = rest.lower().split()[0] if rest else ''
                if looks(token):
                    # "# drive.google.com" o "#drive.google.com" → deshabilitada
                    disabled = True
                    item = rest
                else:
                    # Comentario / encabezado de sección
                    if item not in normalized:
                        normalized.append(item)
                    continue

            # Cola de comentario en línea activa: "educ.ar # nota"
            if not disabled and '#' in item:
                item = item.split('#', 1)[0].strip()
            item = item.lower()
            if not item:
                continue
            if item.startswith('https://'):
                item = item[8:]
            elif item.startswith('http://'):
                item = item[7:]
            item = item.split('/')[0].split(':')[0].strip()
            # *youtube.com → *.youtube.com
            if item.startswith('*') and not item.startswith('*.') and len(item) > 1:
                item = '*.' + item[1:]
            if not item or not looks(item):
                continue
            if item.startswith('.') or item.endswith('*.'):
                continue
            stored = f'# {item}' if disabled else item
            if item in seen_domains:
                for i, prev in enumerate(normalized):
                    prev_dom = prev[2:] if prev.startswith('# ') else prev
                    if prev_dom == item:
                        normalized[i] = stored
                        break
                continue
            seen_domains.add(item)
            normalized.append(stored)
        return ClientManager._collapse_implicit_family_domains(normalized)

    @staticmethod
    def active_allowlist(entries):
        """Solo reglas habilitadas (sin #), para aplicar en clientes."""
        out = []
        for raw in entries or []:
            item = str(raw).strip()
            if not item or item.startswith('#'):
                continue
            if '#' in item:
                item = item.split('#', 1)[0].strip()
            if item:
                out.append(item)
        return out

    def _internet_session_info(self, client_id):
        """Info de sesión de internet para respuestas API, o None."""
        if client_id not in self.internet_sessions:
            return None
        session = self.internet_sessions[client_id]
        end_time = datetime.fromisoformat(session['end_time'])
        remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
        return {
            'time_limit': session['time_limit'],
            'time_limit_seconds': session['time_limit'],
            'start_time': session['start_time'],
            'end_time': session['end_time'],
            'remaining_seconds': remaining_seconds,
            'is_expired': remaining_seconds == 0,
        }

    def _clear_internet_session(self, client_id, notify=False):
        """Elimina la sesión de internet del cliente."""
        if client_id in self.internet_sessions:
            del self.internet_sessions[client_id]
        if notify:
            self._notify_client(client_id, 'internet', {'cleared': True})
    
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
                        client_ip=None, diagnostic_port=None,
                        internet_session_data=None):
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
            internet_session_data: Sesión de internet a restaurar (opcional)
            
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
            'last_seen': datetime.now().isoformat(),
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
        # LWW por config_updated_at: el stamp del cliente (último push admin) gana
        # si es >= al local. Nunca pisar con now() — eso hacía que un re-registro
        # stale bloqueara el sync peer de allowlist/filter.
        existing_cfg = self.client_configs.get(client_id) or {}
        if config:
            existing_stamp = existing_cfg.get('config_updated_at') or ''
            client_stamp = str(config.get('config_updated_at') or '')
            admin_grace = self._has_pending_admin_change(client_id)
            take_client_policy = (
                not admin_grace
                and (
                    not existing_stamp
                    or (bool(client_stamp) and client_stamp >= existing_stamp)
                )
            )

            try:
                client_allowlist = self._normalize_allowlist(
                    config.get('allowlist', self.DEFAULT_CONFIG['allowlist'])
                ) or []
            except ValueError:
                client_allowlist = []

            if take_client_policy:
                allowlist = client_allowlist
                network_filter = bool(
                    config.get(
                        'network_filter_enabled',
                        self.DEFAULT_CONFIG['network_filter_enabled'],
                    )
                )
                internet_request = bool(
                    config.get(
                        'internet_request_enabled',
                        self.DEFAULT_CONFIG['internet_request_enabled'],
                    )
                )
            else:
                allowlist = list(
                    existing_cfg.get('allowlist', self.DEFAULT_CONFIG['allowlist']) or []
                )
                network_filter = bool(
                    existing_cfg.get(
                        'network_filter_enabled',
                        self.DEFAULT_CONFIG['network_filter_enabled'],
                    )
                )
                internet_request = bool(
                    existing_cfg.get(
                        'internet_request_enabled',
                        self.DEFAULT_CONFIG['internet_request_enabled'],
                    )
                )

            # Campos “suaves”: adoptar del cliente solo si también ganó la policy
            # o no hay config local aún; si no, conservar local (mismo LWW).
            if take_client_policy or not existing_cfg:
                soft = {
                    'sync_interval': config.get(
                        'sync_interval', self.DEFAULT_CONFIG['sync_interval']
                    ),
                    'alert_thresholds': config.get(
                        'alert_thresholds', self.DEFAULT_CONFIG['alert_thresholds']
                    ),
                    'custom_name': config.get('custom_name'),
                    'max_server_timeouts': config.get(
                        'max_server_timeouts', self.DEFAULT_CONFIG['max_server_timeouts']
                    ),
                    'lock_recheck_interval': config.get(
                        'lock_recheck_interval',
                        self.DEFAULT_CONFIG['lock_recheck_interval'],
                    ),
                }
            else:
                soft = {
                    'sync_interval': existing_cfg.get(
                        'sync_interval', self.DEFAULT_CONFIG['sync_interval']
                    ),
                    'alert_thresholds': existing_cfg.get(
                        'alert_thresholds', self.DEFAULT_CONFIG['alert_thresholds']
                    ),
                    'custom_name': existing_cfg.get('custom_name'),
                    'max_server_timeouts': existing_cfg.get(
                        'max_server_timeouts', self.DEFAULT_CONFIG['max_server_timeouts']
                    ),
                    'lock_recheck_interval': existing_cfg.get(
                        'lock_recheck_interval',
                        self.DEFAULT_CONFIG['lock_recheck_interval'],
                    ),
                }

            new_stamp = existing_stamp
            if take_client_policy and client_stamp:
                new_stamp = client_stamp
            elif not new_stamp and client_stamp:
                new_stamp = client_stamp

            client_learned = config.get('allowlist_learned') or []
            existing_learned = existing_cfg.get('allowlist_learned') or []
            learned = self._merge_learned(existing_learned, client_learned)

            self.client_configs[client_id] = {
                **soft,
                'network_filter_enabled': network_filter,
                'internet_request_enabled': internet_request,
                'allowlist': allowlist,
                'allowlist_learned': learned,
                'config_updated_at': new_stamp or existing_stamp or None,
            }
            if self.client_configs[client_id]['custom_name']:
                self.clients_db[client_id]['name'] = self.client_configs[client_id]['custom_name']
        elif client_id not in self.client_configs:
            cfg = self.DEFAULT_CONFIG.copy()
            cfg['allowlist'] = list(self.DEFAULT_CONFIG['allowlist'])
            cfg['allowlist_learned'] = list(self.DEFAULT_CONFIG['allowlist_learned'])
            self.client_configs[client_id] = cfg
        
        # Restaurar sesión si se proporcionó (activa o expirada)
        session_restored = False
        if session_data:
            remaining_seconds = session_data.get('remaining_seconds', 0)
            time_limit = session_data.get('time_limit_seconds', remaining_seconds)
            
            if remaining_seconds > 0:
                # Sesión activa
                end_time = datetime.now() + timedelta(seconds=remaining_seconds)
                start_time = end_time - timedelta(seconds=time_limit)
                
                self.client_sessions[client_id] = {
                    'time_limit': time_limit,
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat()
                }
                self.clients_db[client_id]['is_active'] = True
                session_restored = True
            elif time_limit > 0 and client_id not in self.client_sessions:
                # Sesión expirada que el servidor no conocía (ej: server recién arrancó).
                # Crear entrada expirada para que el panel muestre "EXPIRADO".
                now = datetime.now()
                self.client_sessions[client_id] = {
                    'time_limit': time_limit,
                    'start_time': (now - timedelta(seconds=time_limit)).isoformat(),
                    'end_time': now.isoformat(),
                    'expired_at': now.isoformat()
                }
                self.clients_db[client_id]['is_active'] = False

        # Restaurar sesión de internet (solo con sesión de dispositivo activa)
        inet = internet_session_data
        if inet is None and session_data:
            inet = session_data.get('internet')
        if inet and client_id in self.client_sessions and self.clients_db[client_id].get('is_active'):
            inet_remaining = inet.get('remaining_seconds', 0)
            inet_limit = inet.get('time_limit_seconds', inet_remaining)
            if inet_remaining > 0 and inet_limit > 0:
                inet_end = datetime.now() + timedelta(seconds=inet_remaining)
                inet_start = inet_end - timedelta(seconds=inet_limit)
                self.internet_sessions[client_id] = {
                    'time_limit': inet_limit,
                    'start_time': inet_start.isoformat(),
                    'end_time': inet_end.isoformat()
                }
        
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
    
    def _touch_client(self, client_id):
        """Actualiza last_seen del cliente. Llamar en cada interacción."""
        if client_id in self.clients_db:
            self.clients_db[client_id]['last_seen'] = datetime.now().isoformat()
    
    def _is_client_connected(self, client_id):
        """Verifica si el cliente se ha reportado recientemente."""
        if client_id not in self.clients_db:
            return False
        last_seen = self.clients_db[client_id].get('last_seen')
        if not last_seen:
            return False
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last_seen)).total_seconds()
            return elapsed < self.CLIENT_OFFLINE_TIMEOUT
        except Exception:
            return False
    
    def get_clients(self):
        """
        Obtiene la lista de todos los clientes con sus sesiones y configuración.
        
        Returns:
            list de diccionarios con info de cada cliente
        """
        clients_list = []
        for client_id, client_data in self.clients_db.items():
            client_info = client_data.copy()
            client_info['id'] = client_id  # garantizar id para el panel web
            
            # Detectar si el cliente está conectado basado en last_seen
            connected = self._is_client_connected(client_id)
            client_info['connected'] = connected
            
            if client_id in self.client_sessions:
                session = self.client_sessions[client_id]
                end_time = datetime.fromisoformat(session['end_time'])
                remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
                
                # Si la sesión expiró, marcar inactiva y limpiar internet
                if remaining_seconds == 0:
                    self.clients_db[client_id]['is_active'] = False
                    self._clear_internet_session(client_id)
                
                client_info['current_session'] = {
                    'time_limit': session['time_limit'],
                    'start_time': session['start_time'],
                    'end_time': session['end_time'],
                    'remaining_seconds': remaining_seconds
                }
            else:
                client_info['current_session'] = None
                self._clear_internet_session(client_id)

            client_info['internet_session'] = self._internet_session_info(client_id)
            client_info['config'] = self.get_client_config(client_id)
            client_info['pending_access_requests'] = self.get_pending_access_requests(client_id)
            clients_list.append(client_info)
        
        return clients_list
    
    def get_client_status(self, client_id):
        """
        Obtiene el estado de un cliente específico.
        También actualiza last_seen ya que el cliente está haciendo una consulta.
        
        Returns:
            dict con info del cliente o None si no existe
        """
        if client_id not in self.clients_db:
            return None
        
        # El cliente está consultando, actualizar last_seen
        self._touch_client(client_id)
        
        client_data = self.clients_db[client_id].copy()
        client_data['connected'] = self._is_client_connected(client_id)
        
        if client_id in self.client_sessions:
            session = self.client_sessions[client_id]
            end_time = datetime.fromisoformat(session['end_time'])
            remaining_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
            
            if remaining_seconds == 0:
                self._clear_internet_session(client_id)

            client_data['session'] = {
                'time_limit_seconds': session['time_limit'],
                'start_time': session['start_time'],
                'end_time': session['end_time'],
                'remaining_seconds': remaining_seconds,
                'is_expired': remaining_seconds == 0
            }
        else:
            client_data['session'] = None
            self._clear_internet_session(client_id)

        client_data['internet_session'] = self._internet_session_info(client_id)
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
        
        session_info = {
            'time_limit_seconds': total_seconds,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'remaining_seconds': total_seconds
        }
        
        # Notificar al cliente del cambio de sesión
        self._notify_client(client_id, 'session', session_info)
        
        return {
            'success': True,
            'message': f'Tiempo establecido: {time_value} {time_unit}',
            'session': session_info
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

        self._clear_internet_session(client_id)
        
        self.clients_db[client_id]['is_active'] = False
        # Marcar desconectado de inmediato (no esperar el timeout de last_seen).
        # El cliente se apaga al recibir el stop y deja de mandar heartbeats.
        self.clients_db[client_id]['last_seen'] = (
            datetime.now() - timedelta(seconds=self.CLIENT_OFFLINE_TIMEOUT + 5)
        ).isoformat()
        
        # Notificar al cliente que su sesión fue detenida
        self._notify_client(client_id, 'stop', {'message': 'Sesión detenida por el administrador'})
        
        return {'success': True, 'message': 'Sesión detenida'}

    def set_client_internet_time(self, client_id, time_value, time_unit='minutes'):
        """
        Establece el tiempo de internet (wall-clock) para un cliente.
        Requiere una sesión de dispositivo activa.
        """
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}

        if client_id not in self.client_sessions:
            return {'success': False, 'message': 'Se requiere una sesión de dispositivo activa'}

        try:
            end_time = datetime.fromisoformat(self.client_sessions[client_id]['end_time'])
            device_remaining = max(0, int((end_time - datetime.now()).total_seconds()))
        except Exception:
            device_remaining = 0

        if device_remaining <= 0:
            self._clear_internet_session(client_id)
            return {'success': False, 'message': 'Se requiere una sesión de dispositivo activa'}

        if time_unit == 'hours':
            total_seconds = time_value * 3600
        else:
            total_seconds = time_value * 60

        if total_seconds <= 0:
            return {'success': False, 'message': 'El tiempo debe ser mayor a 0'}

        # Internet no puede superar el tiempo restante de la sesión de dispositivo
        total_seconds = min(int(total_seconds), device_remaining)

        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=total_seconds)

        self.internet_sessions[client_id] = {
            'time_limit': total_seconds,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat()
        }

        session_info = {
            'time_limit_seconds': total_seconds,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'remaining_seconds': total_seconds,
            'is_expired': False,
        }

        self._notify_client(client_id, 'internet', session_info)

        return {
            'success': True,
            'message': f'Tiempo de internet establecido: {time_value} {time_unit}',
            'internet_session': session_info
        }

    def stop_client_internet_session(self, client_id):
        """Detiene el reloj de internet (igual que Detener sesión: limpia, no bloquea).

        Al borrar la sesión de internet el cliente vuelve a allowlist / unrestricted
        según el filtro. El corte hard (always_allowed_only) solo ocurre cuando el
        timer de internet llega a 0 por sí solo.
        """
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}

        had = client_id in self.internet_sessions
        self._clear_internet_session(client_id, notify=True)
        return {
            'success': True,
            'message': 'Sesión de internet detenida' if had else 'No había sesión de internet',
        }
    
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
        if client_id in self.internet_sessions:
            del self.internet_sessions[client_id]
        if client_id in self.client_configs:
            del self.client_configs[client_id]
        del self.clients_db[client_id]
        
        return {'success': True, 'message': 'Cliente eliminado'}
    
    # ==================== CLIENT CONFIG ====================
    
    def get_client_config(self, client_id):
        """Obtiene la configuración de un cliente."""
        if client_id not in self.clients_db:
            return None
        cfg = self.client_configs.get(client_id, self.DEFAULT_CONFIG.copy())
        # Asegurar claves nuevas en configs antiguas en memoria
        if 'network_filter_enabled' not in cfg:
            cfg['network_filter_enabled'] = self.DEFAULT_CONFIG['network_filter_enabled']
        if 'internet_request_enabled' not in cfg:
            cfg['internet_request_enabled'] = self.DEFAULT_CONFIG['internet_request_enabled']
        if 'allowlist' not in cfg:
            cfg['allowlist'] = list(self.DEFAULT_CONFIG['allowlist'])
        if 'allowlist_learned' not in cfg:
            cfg['allowlist_learned'] = list(self.DEFAULT_CONFIG['allowlist_learned'])
        return cfg
    
    def set_client_config(self, client_id, sync_interval=None, alert_thresholds=None,
                          custom_name=None, max_server_timeouts=None,
                          lock_recheck_interval=None,
                          network_filter_enabled=None, internet_request_enabled=None,
                          allowlist=None, allowlist_learned=None,
                          notify_client=True):
        """
        Modifica la configuración de un cliente.
        
        Args:
            notify_client: Si True, envía push al cliente (acción de admin).
                          Si False, es un reporte del propio cliente, no notificar.
        
        Returns:
            dict con success, message, config
        """
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        # Si es reporte del cliente y hay un cambio de admin pendiente, ignorar
        if not notify_client and self._has_pending_admin_change(client_id):
            current_config = self.get_client_config(client_id)
            return {'success': True, 'message': 'Cambio de admin pendiente', 'config': current_config}
        
        current_config = self.get_client_config(client_id).copy()
        
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
        
        if lock_recheck_interval is not None:
            lock_recheck_interval = int(lock_recheck_interval)
            if lock_recheck_interval < 1:
                return {'success': False, 'message': 'El intervalo de re-bloqueo debe ser al menos 1 segundo'}
            if lock_recheck_interval > 60:
                return {'success': False, 'message': 'El intervalo de re-bloqueo no debe ser mayor a 60 segundos'}
            current_config['lock_recheck_interval'] = lock_recheck_interval

        if network_filter_enabled is not None:
            current_config['network_filter_enabled'] = bool(network_filter_enabled)

        if internet_request_enabled is not None:
            current_config['internet_request_enabled'] = bool(internet_request_enabled)

        if allowlist is not None:
            # Admin/UI: solo allowlist explícita (learned no se edita ni se muestra).
            try:
                current_config['allowlist'] = self._normalize_allowlist(allowlist) or []
            except ValueError as e:
                return {'success': False, 'message': str(e)}

        if allowlist_learned is not None:
            # Cliente reporta related descubiertos → unión (nunca borrar por admin save).
            current_config['allowlist_learned'] = self._merge_learned(
                current_config.get('allowlist_learned'),
                allowlist_learned,
            )

        if notify_client:
            current_config['config_updated_at'] = datetime.now().isoformat()
        
        self.client_configs[client_id] = current_config
        
        print(f"[Config] Cliente {client_id[:8]}... configuración actualizada: {current_config}")
        
        # Solo notificar al cliente si es acción del admin (no si el cliente reportó)
        if notify_client:
            self._notify_client(client_id, 'config', current_config)
            # Propagar a otros servers (web ↔ móvil) sin esperar al cliente
            try:
                threading.Thread(
                    target=self._sync_with_other_servers,
                    name='cm-config-sync',
                    daemon=True,
                ).start()
            except Exception as e:
                print(f"[Config] sync peers falló: {e}")
        
        return {
            'success': True,
            'message': 'Configuración actualizada',
            'config': current_config
        }

    # ==================== ACCESS REQUESTS (allowlist) ====================

    @staticmethod
    def _normalize_access_domain(raw: str):
        """Normaliza un dominio pedido; None si inválido / ruido."""
        if raw is None:
            return None
        item = str(raw).strip().lower().rstrip('.')
        if not item or item.startswith('#'):
            return None
        if '#' in item:
            item = item.split('#', 1)[0].strip()
        if item.startswith('https://'):
            item = item[8:]
        elif item.startswith('http://'):
            item = item[7:]
        item = item.split('/')[0].split(':')[0].strip()
        if item.startswith('*') and not item.startswith('*.') and len(item) > 1:
            item = '*.' + item[1:]
        if not item or len(item) > 253:
            return None
        if item in ('localhost',) or item.endswith('.local') or item.endswith('.lan'):
            return None
        if not ClientManager._looks_like_allowlist_rule(item):
            return None
        return item

    def get_pending_access_requests(self, client_id=None):
        """Lista pedidos pending (opcionalmente filtrados por cliente)."""
        out = []
        for req in self.access_requests.values():
            if req.get('status') != 'pending':
                continue
            if client_id and req.get('client_id') != client_id:
                continue
            out.append(dict(req))
        out.sort(key=lambda r: r.get('created_at') or '')
        return out

    def create_access_request(self, client_id, domain):
        """Cliente reporta dominio bloqueado. Dedup por (client, domain) pending."""
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        domain = self._normalize_access_domain(domain)
        if not domain:
            return {'success': False, 'message': 'Dominio inválido'}

        for req in self.access_requests.values():
            if (
                req.get('client_id') == client_id
                and req.get('domain') == domain
                and req.get('status') == 'pending'
            ):
                return {
                    'success': True,
                    'message': 'Pedido ya pendiente',
                    'request': dict(req),
                    'created': False,
                }

        request_id = str(uuid.uuid4())
        req = {
            'id': request_id,
            'client_id': client_id,
            'domain': domain,
            'created_at': datetime.now().isoformat(),
            'status': 'pending',
        }
        self.access_requests[request_id] = req
        self._touch_client(client_id)
        print(f"[AccessReq] Nuevo {client_id[:8]}... → {domain}")
        try:
            self._sync_with_other_servers()
        except Exception:
            pass
        return {
            'success': True,
            'message': 'Pedido registrado',
            'request': dict(req),
            'created': True,
        }

    def approve_access_request(self, client_id, request_id):
        """Aprueba: agrega dominio a allowlist (permanente) y push config."""
        req = self.access_requests.get(request_id)
        if not req or req.get('client_id') != client_id:
            return {'success': False, 'message': 'Pedido no encontrado'}
        if req.get('status') != 'pending':
            return {
                'success': False,
                'message': f"Pedido ya {req.get('status')}",
                'request': dict(req),
            }

        domain = req.get('domain')
        cfg = self.get_client_config(client_id)
        allow = list(cfg.get('allowlist') or [])
        # Reactivar si estaba como # domain
        updated = False
        for i, entry in enumerate(allow):
            e = str(entry).strip()
            if e == f'# {domain}' or e == f'#{domain}':
                allow[i] = domain
                updated = True
                break
            if e == domain:
                updated = True
                break
        if not updated:
            allow.append(domain)

        result = self.set_client_config(
            client_id, allowlist=allow, notify_client=True
        )
        if not result.get('success'):
            return result

        req['status'] = 'approved'
        req['resolved_at'] = datetime.now().isoformat()
        self.access_requests[request_id] = req
        # Cerrar otros pending del mismo dominio
        for other in self.access_requests.values():
            if (
                other.get('client_id') == client_id
                and other.get('domain') == domain
                and other.get('status') == 'pending'
                and other.get('id') != request_id
            ):
                other['status'] = 'approved'
                other['resolved_at'] = req['resolved_at']
        try:
            self._sync_with_other_servers()
        except Exception:
            pass
        return {
            'success': True,
            'message': f'Dominio {domain} agregado a allowlist',
            'request': dict(req),
            'config': result.get('config'),
        }

    def deny_access_request(self, client_id, request_id):
        """Rechaza pedido sin tocar allowlist."""
        req = self.access_requests.get(request_id)
        if not req or req.get('client_id') != client_id:
            return {'success': False, 'message': 'Pedido no encontrado'}
        if req.get('status') != 'pending':
            return {
                'success': False,
                'message': f"Pedido ya {req.get('status')}",
                'request': dict(req),
            }
        req['status'] = 'denied'
        req['resolved_at'] = datetime.now().isoformat()
        self.access_requests[request_id] = req
        try:
            self._sync_with_other_servers()
        except Exception:
            pass
        return {
            'success': True,
            'message': 'Pedido rechazado',
            'request': dict(req),
        }

    def _merge_access_requests_from_remote(self, clients_list):
        """Fusiona pedidos de acceso recibidos vía sync entre servidores."""
        for client_data in clients_list or []:
            client_id = client_data.get('id')
            if not client_id:
                continue
            for remote in client_data.get('pending_access_requests') or []:
                rid = remote.get('id')
                domain = self._normalize_access_domain(remote.get('domain') or '')
                if not rid or not domain:
                    continue
                status = remote.get('status') or 'pending'
                local = self.access_requests.get(rid)
                if local is None:
                    # Evitar duplicar pending mismo dominio
                    if status == 'pending':
                        dup = False
                        for existing in self.access_requests.values():
                            if (
                                existing.get('client_id') == client_id
                                and existing.get('domain') == domain
                                and existing.get('status') == 'pending'
                            ):
                                dup = True
                                break
                        if dup:
                            continue
                    self.access_requests[rid] = {
                        'id': rid,
                        'client_id': client_id,
                        'domain': domain,
                        'created_at': remote.get('created_at') or datetime.now().isoformat(),
                        'status': status,
                        'resolved_at': remote.get('resolved_at'),
                    }
                else:
                    # Preferir estado terminal sobre pending
                    if local.get('status') == 'pending' and status in ('approved', 'denied'):
                        local['status'] = status
                        local['resolved_at'] = remote.get('resolved_at') or datetime.now().isoformat()
    
    # ==================== CLIENT PUSH NOTIFICATIONS ====================
    
    def _notify_client(self, client_id, event_type, event_data):
        """
        Envía una notificación HTTP push al cliente cuando el admin hace un cambio.
        El cliente es la fuente de verdad y propagará el cambio a los demás servers.
        
        Incluye reintentos automáticos y marca un grace period para que el sync
        del cliente no sobreescriba el cambio antes de que el push llegue.
        
        Args:
            client_id: ID del cliente
            event_type: Tipo de evento ('session', 'config', 'stop')
            event_data: Datos del evento a enviar
        """
        if client_id not in self.clients_db:
            return
        
        # Grace siempre: evita que un re-registro stale pise el cambio de admin
        # aunque aún no haya IP / el push falle.
        self._pending_admin_changes[client_id] = datetime.now()

        client = self.clients_db[client_id]
        client_ip = client.get('client_ip')
        diagnostic_port = client.get('diagnostic_port', 5002)
        
        if not client_ip:
            print(f"[Push] Cliente {client_id[:8]}... no tiene IP registrada, no se puede notificar")
            return
        
        import time as _time
        
        def _do_notify():
            url = f"http://{client_ip}:{diagnostic_port}/api/push/{event_type}"
            payload = json.dumps(event_data).encode('utf-8')
            
            max_retries = 5
            retry_delays = [0, 2, 3, 5, 5]  # segundos entre reintentos
            
            for attempt in range(max_retries):
                if attempt > 0:
                    _time.sleep(retry_delays[attempt])
                
                try:
                    req = urllib.request.Request(
                        url,
                        data=payload,
                        headers={'Content-Type': 'application/json'}
                    )
                    
                    with urllib.request.urlopen(req, timeout=5) as response:
                        if response.status == 200:
                            print(f"[Push] '{event_type}' enviado a cliente {client_id[:8]}..." + 
                                  (f" (intento {attempt + 1})" if attempt > 0 else ""))
                            # Push exitoso, limpiar pending
                            self._pending_admin_changes.pop(client_id, None)
                            return
                        else:
                            print(f"[Push] Cliente respondió {response.status} (intento {attempt + 1}/{max_retries})")
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"[Push] Reintentando '{event_type}' a {client_id[:8]}... ({attempt + 1}/{max_retries}): {e}")
                    else:
                        print(f"[Push] Falló '{event_type}' a {client_id[:8]}... después de {max_retries} intentos: {e}")
                        # No limpiar pending - se limpiará por timeout en report_session
        
        # Enviar en un thread para no bloquear la respuesta al admin
        threading.Thread(target=_do_notify, daemon=True).start()
    
    # ==================== SESSION REPORTING ====================
    
    def _has_pending_admin_change(self, client_id):
        """
        Verifica si hay un cambio de admin pendiente para este cliente.
        Si el grace period expiró, lo limpia automáticamente.
        """
        if client_id not in self._pending_admin_changes:
            return False
        
        elapsed = (datetime.now() - self._pending_admin_changes[client_id]).total_seconds()
        if elapsed > self.ADMIN_CHANGE_GRACE_SECONDS:
            # Grace period expirado, limpiar
            del self._pending_admin_changes[client_id]
            return False
        
        return True
    
    def report_session(self, client_id, remaining_seconds, time_limit_seconds=None):
        """
        Permite a un cliente reportar su sesión activa.
        Si remaining_seconds <= 0, marca la sesión como expirada pero la mantiene
        para que el panel siga mostrando "EXPIRADO". La sesión solo se elimina
        cuando el admin asigna nuevo tiempo o hace "Detener".
        
        Si hay un cambio de admin pendiente (grace period), el reporte se ignora
        para evitar que el sync del cliente sobreescriba el cambio del admin.
        
        Returns:
            dict con success, message, session
        """
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}
        
        # El cliente está reportando, actualizar last_seen
        self._touch_client(client_id)
        
        # Verificar si hay un cambio de admin pendiente
        if self._has_pending_admin_change(client_id):
            return {
                'success': True,
                'message': 'Cambio de admin pendiente, reporte ignorado',
                'session': None
            }
        
        # remaining_seconds <= 0: el cliente cree que expiró.
        # Si el admin ya asignó tiempo nuevo (end_time futuro), NO pisar esa sesión.
        if remaining_seconds <= 0:
            if client_id in self.client_sessions:
                session = self.client_sessions[client_id]
                try:
                    end_time = datetime.fromisoformat(session['end_time'])
                    server_remaining = max(0, int((end_time - datetime.now()).total_seconds()))
                except Exception:
                    server_remaining = 0
                if server_remaining > 0:
                    return {
                        'success': True,
                        'message': 'Sesión activa en servidor (cliente desactualizado)',
                        'session': {
                            'time_limit_seconds': session['time_limit'],
                            'start_time': session['start_time'],
                            'end_time': session['end_time'],
                            'remaining_seconds': server_remaining
                        }
                    }
                if 'expired_at' not in session:
                    # Primera vez que se reporta expirada: acumular tiempo usado
                    session['expired_at'] = datetime.now().isoformat()
                    self.clients_db[client_id]['total_time_used'] += session['time_limit']
            elif time_limit_seconds and time_limit_seconds > 0:
                # El servidor no conocía esta sesión (ej: server recién arrancó) pero
                # el cliente tiene una sesión expirada. Crear entrada expirada para
                # que el panel muestre "EXPIRADO".
                now = datetime.now()
                self.client_sessions[client_id] = {
                    'time_limit': time_limit_seconds,
                    'start_time': (now - timedelta(seconds=time_limit_seconds)).isoformat(),
                    'end_time': now.isoformat(),
                    'expired_at': now.isoformat()
                }
                self.clients_db[client_id]['total_time_used'] += time_limit_seconds
            self.clients_db[client_id]['is_active'] = False
            self._clear_internet_session(client_id)
            return {
                'success': True,
                'message': 'Sesión expirada',
                'session': None,
                'internet_session': None
            }
        
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
            },
            'internet_session': self._internet_session_info(client_id)
        }

    def report_internet_session(self, client_id, remaining_seconds, time_limit_seconds=None):
        """
        Permite al cliente reportar su sesión de internet.
        Si remaining <= 0, marca expirada pero mantiene entrada (remaining 0).
        """
        if client_id not in self.clients_db:
            return {'success': False, 'message': 'Cliente no encontrado'}

        self._touch_client(client_id)

        if self._has_pending_admin_change(client_id):
            return {
                'success': True,
                'message': 'Cambio de admin pendiente, reporte ignorado',
                'internet_session': self._internet_session_info(client_id)
            }

        # Sin sesión de dispositivo activa no hay internet timer
        if client_id not in self.client_sessions:
            self._clear_internet_session(client_id)
            return {'success': True, 'message': 'Sin sesión de dispositivo', 'internet_session': None}

        try:
            device_end = datetime.fromisoformat(self.client_sessions[client_id]['end_time'])
            device_remaining = max(0, int((device_end - datetime.now()).total_seconds()))
        except Exception:
            device_remaining = 0

        if device_remaining <= 0:
            self._clear_internet_session(client_id)
            return {'success': True, 'message': 'Sesión de dispositivo expirada', 'internet_session': None}

        if remaining_seconds <= 0:
            # Mantener sesión de internet expirada (remaining 0) para política always-allowed
            limit = time_limit_seconds or (
                self.internet_sessions.get(client_id, {}).get('time_limit') or 0
            )
            now = datetime.now()
            self.internet_sessions[client_id] = {
                'time_limit': limit,
                'start_time': (now - timedelta(seconds=limit)).isoformat() if limit else now.isoformat(),
                'end_time': now.isoformat()
            }
            return {
                'success': True,
                'message': 'Sesión de internet expirada',
                'internet_session': self._internet_session_info(client_id)
            }

        time_limit = time_limit_seconds or remaining_seconds
        remaining_seconds = min(int(remaining_seconds), device_remaining)
        end_time = datetime.now() + timedelta(seconds=remaining_seconds)
        start_time = end_time - timedelta(seconds=time_limit)

        self.internet_sessions[client_id] = {
            'time_limit': time_limit,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat()
        }

        return {
            'success': True,
            'message': f'Sesión de internet reportada: {remaining_seconds}s restantes',
            'internet_session': self._internet_session_info(client_id)
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
        
        NOTA: No llama _sync_with_other_servers() para evitar loops infinitos.
        Si A recibe sync de B y luego A sincroniza con B, se crea un ping-pong.
        La sincronización activa debe ser disparada solo por register-server o acciones explícitas.
        
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
        
        return self.get_servers()
    
    def sync_clients_from_remote(self, clients_list):
        """
        Fusiona clientes recibidos de otros servidores (registro + sesión activa).
        """
        if not clients_list:
            return

        self._merge_access_requests_from_remote(clients_list)

        for client_data in clients_list:
            client_id = client_data.get('id')
            if not client_id:
                continue

            name = client_data.get('name') or 'Cliente Remoto'
            if client_id not in self.clients_db:
                self.clients_db[client_id] = {
                    'id': client_id,
                    'name': name,
                    'registered_at': client_data.get('registered_at', datetime.now().isoformat()),
                    'total_time_used': client_data.get('total_time_used', 0),
                    'is_active': False,
                    'last_seen': client_data.get('last_seen', datetime.now().isoformat()),
                }
            else:
                if name:
                    self.clients_db[client_id]['name'] = name
                remote_seen = client_data.get('last_seen')
                if remote_seen:
                    local_seen = self.clients_db[client_id].get('last_seen') or ''
                    if remote_seen > local_seen:
                        self.clients_db[client_id]['last_seen'] = remote_seen
                if client_data.get('client_ip'):
                    self.clients_db[client_id]['client_ip'] = client_data['client_ip']
                if client_data.get('diagnostic_port'):
                    self.clients_db[client_id]['diagnostic_port'] = client_data['diagnostic_port']

            remote_config = client_data.get('config')
            if isinstance(remote_config, dict):
                if client_id not in self.client_configs:
                    self.client_configs[client_id] = self.DEFAULT_CONFIG.copy()
                    self.client_configs[client_id]['allowlist'] = list(
                        self.DEFAULT_CONFIG['allowlist']
                    )
                local_updated = self.client_configs[client_id].get('config_updated_at') or ''
                remote_updated = remote_config.get('config_updated_at') or ''
                # Misma regla para TODOS los campos (antes alerts siempre pisaban
                # y allowlist/filter solo si el stamp remoto era más nuevo → UI
                # “sincronizada” en sync/alerts pero allowlist desfasada).
                take_remote = (not local_updated) or (
                    bool(remote_updated) and remote_updated >= local_updated
                )

                if take_remote:
                    for key in (
                        'sync_interval',
                        'alert_thresholds',
                        'custom_name',
                        'max_server_timeouts',
                        'lock_recheck_interval',
                    ):
                        if key in remote_config and remote_config[key] is not None:
                            self.client_configs[client_id][key] = remote_config[key]

                    if 'network_filter_enabled' in remote_config and remote_config['network_filter_enabled'] is not None:
                        self.client_configs[client_id]['network_filter_enabled'] = bool(
                            remote_config['network_filter_enabled']
                        )
                    if 'internet_request_enabled' in remote_config and remote_config['internet_request_enabled'] is not None:
                        self.client_configs[client_id]['internet_request_enabled'] = bool(
                            remote_config['internet_request_enabled']
                        )
                    if 'allowlist' in remote_config and remote_config['allowlist'] is not None:
                        try:
                            self.client_configs[client_id]['allowlist'] = (
                                self._normalize_allowlist(remote_config['allowlist']) or []
                            )
                        except ValueError:
                            pass
                    if remote_updated:
                        self.client_configs[client_id]['config_updated_at'] = remote_updated
                elif 'allowlist' in self.client_configs[client_id]:
                    # Colapsar basura CDN local aunque no adoptemos remoto
                    try:
                        self.client_configs[client_id]['allowlist'] = (
                            self._normalize_allowlist(
                                self.client_configs[client_id].get('allowlist') or []
                            ) or []
                        )
                    except ValueError:
                        pass

                # Learned always unions (related traffic hosts; hidden in UI)
                self.client_configs[client_id]['allowlist_learned'] = self._merge_learned(
                    self.client_configs[client_id].get('allowlist_learned'),
                    remote_config.get('allowlist_learned'),
                )

            session = client_data.get('current_session') or client_data.get('session')
            if not session:
                continue

            remaining = int(session.get('remaining_seconds') or 0)
            time_limit = int(session.get('time_limit') or session.get('time_limit_seconds') or remaining)
            # Sesión expirada remota: crear entrada EXPIRADO en este servidor
            if remaining <= 0:
                if time_limit > 0 and client_id not in self.client_sessions:
                    now = datetime.now()
                    self.client_sessions[client_id] = {
                        'time_limit': time_limit,
                        'start_time': session.get('start_time') or (now - timedelta(seconds=time_limit)).isoformat(),
                        'end_time': session.get('end_time') or now.isoformat(),
                        'expired_at': now.isoformat(),
                    }
                    self.clients_db[client_id]['is_active'] = False
                continue

            local_remaining = 0
            if client_id in self.client_sessions:
                try:
                    end_time = datetime.fromisoformat(self.client_sessions[client_id]['end_time'])
                    local_remaining = max(0, int((end_time - datetime.now()).total_seconds()))
                except Exception:
                    local_remaining = 0

            # Adoptar sesión remota si es más nueva / tiene más tiempo
            if remaining >= local_remaining:
                end_time = datetime.now() + timedelta(seconds=remaining)
                start_time = end_time - timedelta(seconds=max(time_limit, remaining))
                self.client_sessions[client_id] = {
                    'time_limit': time_limit if time_limit > 0 else remaining,
                    'start_time': session.get('start_time') or start_time.isoformat(),
                    'end_time': end_time.isoformat(),
                }
                self.clients_db[client_id]['is_active'] = True

    def get_clients_sync_payload(self):
        """Clientes + config para sync entre servidores."""
        payload = []
        for client in self.get_clients():
            entry = client.copy()
            entry['config'] = self.get_client_config(client['id']) or self.DEFAULT_CONFIG.copy()
            payload.append(entry)
        return payload

    def _sync_with_other_servers(self):
        """
        Sincroniza servidores conocidos y clientes con otros servidores.
        """
        my_url = self.local_server_url
        if not my_url:
            return

        sync_data = {
            'servers': self.get_servers(),
            'clients': self.get_clients_sync_payload(),
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

                with urllib.request.urlopen(req, timeout=5) as response:
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
                        remote_clients = response_data.get('known_clients') or response_data.get('clients')
                        if remote_clients:
                            self.sync_clients_from_remote(remote_clients)
            except Exception as e:
                print(f"[Sync] Error con {server_url}: {e}")

    def probe_client_live(self, client_id):
        """
        Consulta el diagnóstico del cliente en la LAN y adopta sesión/internet.
        Returns: dict {ok, reason?}
        """
        if client_id not in self.clients_db:
            return {'ok': False, 'reason': 'unknown'}
        client = self.clients_db[client_id]
        client_ip = client.get('client_ip')
        port = int(client.get('diagnostic_port') or 5002)
        if not client_ip:
            return {'ok': False, 'reason': 'no_ip'}

        url = f"http://{client_ip}:{port}/api/diagnostic"
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            # Fallback mínimo
            try:
                url2 = f"http://{client_ip}:{port}/api/status"
                req = urllib.request.Request(url2, headers={'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
            except Exception as e2:
                return {'ok': False, 'reason': str(e2) or str(e)}

        self._touch_client(client_id)
        if client.get('client_ip') != client_ip:
            self.clients_db[client_id]['client_ip'] = client_ip

        session = data.get('session')
        if isinstance(session, dict) and session.get('remaining_seconds') is not None:
            rem = int(session.get('remaining_seconds') or 0)
            tl = int(session.get('time_limit_seconds') or session.get('time_limit') or rem or 0)
            self.report_session(client_id, rem, tl if tl > 0 else None)
        elif data.get('has_session') and data.get('remaining_seconds') is not None:
            rem = int(data.get('remaining_seconds') or 0)
            self.report_session(client_id, rem, None)

        inet = data.get('internet_session')
        if isinstance(inet, dict) and inet.get('remaining_seconds') is not None:
            rem = int(inet.get('remaining_seconds') or 0)
            tl = int(inet.get('time_limit_seconds') or inet.get('time_limit') or rem or 0)
            self.report_internet_session(client_id, rem, tl if tl > 0 else None)

        return {'ok': True}

    def force_refresh(self):
        """
        Sync con otros servidores + sondeo en vivo de cada cliente.
        Usado por el botón Actualizar del panel.
        """
        self._sync_with_other_servers()

        reached = 0
        failed = 0
        skipped = 0
        details = []

        def _probe(cid):
            return cid, self.probe_client_live(cid)

        client_ids = list(self.clients_db.keys())
        if client_ids:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(8, len(client_ids))) as pool:
                futs = [pool.submit(_probe, cid) for cid in client_ids]
                for fut in as_completed(futs):
                    try:
                        cid, res = fut.result()
                    except Exception as e:
                        failed += 1
                        details.append({'id': '?', 'ok': False, 'reason': str(e)})
                        continue
                    if res.get('ok'):
                        reached += 1
                    elif res.get('reason') == 'no_ip':
                        skipped += 1
                    else:
                        failed += 1
                    details.append({'id': cid[:8], **res})

        total = len(client_ids)
        if total == 0:
            message = 'Sin clientes — sync de servidores completado'
        else:
            message = (
                f'Actualizado: {reached}/{total} clientes en vivo'
                + (f', {failed} sin respuesta' if failed else '')
                + (f', {skipped} sin IP' if skipped else '')
            )

        return {
            'success': True,
            'message': message,
            'reached': reached,
            'failed': failed,
            'skipped': skipped,
            'total': total,
            'details': details,
            'known_servers': self.get_servers(),
            'known_clients': self.get_clients_sync_payload(),
        }

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
        Intenta obtener la máscara de subred real del sistema para calcular
        correctamente (ej: /22 → 192.168.71.255, no 192.168.68.255).
        Si se proporciona ip_address, calcula el broadcast basado en esa IP.
        Si no, usa get_local_ip() para determinarlo automáticamente.
        """
        try:
            if ip_address is None:
                ip_address = ClientManager.get_local_ip()
            if ip_address == "127.0.0.1":
                return "255.255.255.255"
            
            # Intentar obtener la máscara de subred real desde las interfaces de red
            broadcast_addr = ClientManager._get_broadcast_from_interfaces(ip_address)
            if broadcast_addr:
                return broadcast_addr
            
            # Fallback: asumir /24 si no pudimos obtener la máscara real
            parts = ip_address.split('.')
            if len(parts) == 4:
                parts[3] = '255'
                return '.'.join(parts)
        except Exception:
            pass
        return "255.255.255.255"
    
    @staticmethod
    def _get_broadcast_from_interfaces(ip_address):
        """
        Obtiene la dirección de broadcast real consultando las interfaces de red del sistema.
        Funciona en Linux, macOS y Android.
        """
        import struct
        
        # Método 1: usar netifaces si está disponible
        try:
            import netifaces
            for iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs:
                    for addr_info in addrs[netifaces.AF_INET]:
                        if addr_info.get('addr') == ip_address:
                            broadcast = addr_info.get('broadcast')
                            if broadcast:
                                return broadcast
        except ImportError:
            pass
        
        # Método 2: usar fcntl/ioctl en Linux/Android
        try:
            import fcntl
            import array
            
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Obtener lista de interfaces
            max_interfaces = 32
            buf_size = max_interfaces * 40  # struct ifreq size
            buf = array.array('B', b'\0' * buf_size)
            
            # SIOCGIFCONF
            result = fcntl.ioctl(s.fileno(), 0x8912, struct.pack('iL', buf_size, buf.buffer_info()[0]))
            result_size = struct.unpack('iL', result)[0]
            
            for i in range(0, result_size, 40):
                iface_name = buf[i:i+16].tobytes().split(b'\0', 1)[0].decode('utf-8', errors='ignore')
                iface_ip = socket.inet_ntoa(buf[i+20:i+24].tobytes())
                
                if iface_ip == ip_address:
                    # Obtener netmask con SIOCGIFNETMASK
                    try:
                        netmask_result = fcntl.ioctl(
                            s.fileno(),
                            0x891b,  # SIOCGIFNETMASK
                            struct.pack('256s', iface_name.encode('utf-8'))
                        )
                        netmask = socket.inet_ntoa(netmask_result[20:24])
                        
                        # Calcular broadcast: IP | ~netmask
                        ip_int = struct.unpack('!I', socket.inet_aton(ip_address))[0]
                        mask_int = struct.unpack('!I', socket.inet_aton(netmask))[0]
                        broadcast_int = ip_int | (~mask_int & 0xFFFFFFFF)
                        broadcast = socket.inet_ntoa(struct.pack('!I', broadcast_int))
                        s.close()
                        return broadcast
                    except Exception:
                        pass
            s.close()
        except (ImportError, OSError):
            pass
        
        # Método 3: parsear ifconfig/ip addr (macOS y Linux)
        try:
            import subprocess
            import platform
            
            if platform.system() == 'Darwin':
                # macOS: ifconfig
                output = subprocess.check_output(['ifconfig'], timeout=3).decode('utf-8', errors='ignore')
                current_broadcast = None
                found_ip = False
                for line in output.split('\n'):
                    line = line.strip()
                    if 'inet ' in line and ip_address in line:
                        # Buscar broadcast en la misma línea
                        parts = line.split()
                        for j, part in enumerate(parts):
                            if part == 'broadcast' and j + 1 < len(parts):
                                return parts[j + 1]
            else:
                # Linux: ip addr
                output = subprocess.check_output(['ip', 'addr'], timeout=3).decode('utf-8', errors='ignore')
                for line in output.split('\n'):
                    line = line.strip()
                    if f'inet {ip_address}/' in line:
                        # Formato: inet 192.168.68.100/22 brd 192.168.71.255
                        parts = line.split()
                        for j, part in enumerate(parts):
                            if part == 'brd' and j + 1 < len(parts):
                                return parts[j + 1]
        except Exception:
            pass
        
        return None
    
    # ==================== BROADCAST ====================
    
    def start_broadcast(self, host_ip_override=None, stop_check=None):
        """
        Inicia un thread de broadcast UDP para anunciar la presencia del servidor.
        Los clientes escuchan en el puerto 5001 y se registran automáticamente.
        
        Args:
            host_ip_override: IP explícita (ej: Docker HOST_IP). Si None, se auto-detecta.
            stop_check: Callable que retorna True cuando se debe detener el broadcast.
                         Si None, corre indefinidamente.
        """
        def broadcast_thread():
            DISCOVERY_PORT = 5001
            
            try:
                local_ip = host_ip_override or self.get_local_ip()
                if local_ip == "127.0.0.1" or not local_ip:
                    print(f"[Broadcast] IP no valida para broadcast: {local_ip}")
                    return
                
                server_url = f"http://{local_ip}:{self.server_port}"
                server_info_data = {
                    'url': server_url,
                    'ip': local_ip,
                    'port': self.server_port
                }
                
                broadcast_addr = self.get_broadcast_address(local_ip)
                
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                try:
                    sock.bind(('', 0))
                except Exception as bind_error:
                    print(f"[Broadcast] Advertencia al hacer bind: {bind_error}")
                
                config = self.get_server_config()
                print(f"[Broadcast] Iniciando anuncios en {local_ip}:{self.server_port}")
                print(f"[Broadcast] Direccion de broadcast: {broadcast_addr}:{DISCOVERY_PORT}")
                print(f"[Broadcast] Intervalo: {config['broadcast_interval']}s")
                
                broadcast_targets = [broadcast_addr]
                if broadcast_addr != "255.255.255.255":
                    broadcast_targets.append("255.255.255.255")
                
                last_client_count = 0
                broadcasts_paused = False
                last_error_logged = 0
                
                should_run = lambda: (stop_check is None or not stop_check())
                
                while should_run():
                    try:
                        config = self.get_server_config()
                        num_clients = len(self.clients_db)
                        
                        if num_clients > 0:
                            if not broadcasts_paused:
                                print(f"[Broadcast] {num_clients} cliente(s) conectado(s). Broadcasts pausados.")
                                broadcasts_paused = True
                            elif num_clients != last_client_count:
                                print(f"[Broadcast] {num_clients} cliente(s) conectado(s).")
                            last_client_count = num_clients
                            time.sleep(config['broadcast_interval'])
                            continue
                        else:
                            if broadcasts_paused:
                                print(f"[Broadcast] Sin clientes. Reanudando broadcasts UDP.")
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
                            try:
                                sock.close()
                            except Exception:
                                pass
                            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                            sock.bind(('', 0))
                            try:
                                sock.sendto(message, ('255.255.255.255', DISCOVERY_PORT))
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
                            print(f"[Broadcast] Error: {e}")
                            last_error_logged = now
                        time.sleep(config.get('broadcast_interval', 1))
            except Exception as e:
                print(f"[Broadcast] Error en thread de broadcast: {e}")
                import traceback
                traceback.print_exc()
        
        thread = threading.Thread(target=broadcast_thread, daemon=True)
        thread.start()
        return thread
    
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
