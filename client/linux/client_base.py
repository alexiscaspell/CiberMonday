"""
CiberMonday Client - Clase base cross-platform.
Define la interfaz abstracta para operaciones de plataforma (bloqueo, alertas, storage)
y contiene toda la lógica compartida (monitoreo, sincronización, discovery, diagnóstico).
"""

import requests
import time
import sys
import os
import errno
from datetime import datetime, timedelta
import threading
import socket
import json
from abc import ABC, abstractmethod
from http.server import HTTPServer, BaseHTTPRequestHandler

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')


class CiberMondayClient(ABC):

    DEFAULT_SERVER_URL = "http://localhost:5000"
    DEFAULT_CHECK_INTERVAL = 5
    DEFAULT_SYNC_INTERVAL = 30
    DEFAULT_ALERT_THRESHOLDS = [600, 300, 120, 60]
    DEFAULT_LOCK_RECHECK_INTERVAL = 1

    def __init__(self):
        self.base_path = self._get_base_path()
        self.is_service = self._detect_service_mode()
        self.configure_only = '--configure' in sys.argv
        if self.configure_only:
            self.is_service = False

        self.server_url = self.DEFAULT_SERVER_URL
        self.check_interval = self.DEFAULT_CHECK_INTERVAL
        self.sync_interval = self.DEFAULT_SYNC_INTERVAL
        self.lock_recheck_interval = self.DEFAULT_LOCK_RECHECK_INTERVAL
        self.client_id_file = os.path.join(self.base_path, "client_id.txt")

        self.alert_thresholds = sorted(self.DEFAULT_ALERT_THRESHOLDS, reverse=True)
        self.alerts_shown = {t: False for t in self.alert_thresholds}
        self.last_known_remaining = None

        self._discovery_stats = {
            'broadcast_count': 0,
            'last_broadcast_time': None,
            'last_broadcast_from': None,
            'servers_discovered': set(),
            'listener_started': False
        }
        self._diagnostic_server = None
        self._sync_manager = None

    # ==================== HELPERS ====================

    @staticmethod
    def _get_base_path():
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    @staticmethod
    def _detect_service_mode():
        if '--service' in sys.argv:
            return True
        try:
            if getattr(sys, 'frozen', False):
                name = os.path.basename(sys.argv[0]).lower() if sys.argv else os.path.basename(sys.executable).lower()
            else:
                name = os.path.basename(sys.argv[0]).lower() if sys.argv else ''
            if 'cibermondayservice' in name or name in ('service.exe', 'service.py'):
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def format_time(seconds):
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    # ==================== ABSTRACT - Platform ====================

    @abstractmethod
    def lock_workstation(self):
        """Bloquea la pantalla del equipo."""
        ...

    @abstractmethod
    def is_user_session_active(self):
        """Retorna True si hay una sesión gráfica activa."""
        ...

    @abstractmethod
    def show_alert(self, title, message, is_warning=False):
        """Muestra una alerta visual al usuario."""
        ...

    @abstractmethod
    def is_admin(self):
        """Retorna True si corre con privilegios elevados."""
        ...

    @abstractmethod
    def apply_protections(self):
        """Aplica protecciones anti-tampering. Retorna lista de protecciones aplicadas."""
        ...

    @abstractmethod
    def setup_firewall(self):
        """Configura reglas de firewall para discovery (UDP 5001) y diagnóstico (TCP 5002)."""
        ...

    # ==================== ABSTRACT - Storage ====================

    @abstractmethod
    def save_session(self, time_limit_seconds, start_time_iso, end_time_iso):
        ...

    @abstractmethod
    def get_session(self):
        """Retorna dict con datos de sesión o None."""
        ...

    @abstractmethod
    def clear_session(self):
        ...

    @abstractmethod
    def get_remaining_seconds(self):
        """Retorna segundos restantes o 0."""
        ...

    @abstractmethod
    def is_session_expired(self):
        ...

    @abstractmethod
    def get_session_info(self):
        """Retorna dict con is_expired, remaining_seconds, time_limit_seconds, etc. o None."""
        ...

    @abstractmethod
    def save_client_id(self, client_id):
        ...

    @abstractmethod
    def load_client_id(self):
        """Retorna client ID o None."""
        ...

    @abstractmethod
    def save_config(self, config):
        ...

    @abstractmethod
    def load_config(self):
        """Retorna dict de config o None."""
        ...

    @abstractmethod
    def save_servers(self, servers_list):
        ...

    @abstractmethod
    def load_servers(self):
        """Retorna lista de dicts de servidores."""
        ...

    @abstractmethod
    def increment_server_timeouts(self, server_urls):
        ...

    @abstractmethod
    def reset_server_timeout_count(self, server_url):
        ...

    # ==================== RUN ====================

    def run(self):
        self._load_configuration()

        if self.configure_only:
            print("[Config] Configuración completada. Saliendo...")
            sys.exit(0)

        try:
            protections = self.apply_protections()
            if protections:
                print("Protecciones aplicadas:", ", ".join(protections))
        except Exception as e:
            print(f"Advertencia: No se pudieron aplicar todas las protecciones: {e}")

        if not self.is_service:
            try:
                if not self.is_admin():
                    print("ADVERTENCIA: No se ejecuta como administrador/root.")
                    print("El bloqueo y las protecciones pueden no funcionar correctamente.")
                    print("Presiona Enter para continuar o Ctrl+C para salir...")
                    input()
            except Exception:
                pass

        client_id = self.get_client_id()
        print(f"[Inicio] Cliente ID: {client_id}")

        try:
            self.monitor_time(client_id)
        except Exception as e:
            print(f"Error fatal: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def _load_configuration(self):
        config_data = self.load_config()

        if not config_data or not config_data.get('server_url'):
            if self.is_service:
                print("ERROR: No hay configuración guardada.")
                print("Ejecuta el cliente manualmente primero para configurar.")
            else:
                try:
                    from config_gui import show_config_window
                    print("No se encontró configuración. Abriendo ventana de configuración...")
                    config_data = show_config_window(client=self)
                    if not config_data:
                        print("Configuración cancelada. Saliendo...")
                        sys.exit(1)
                except Exception as e:
                    import traceback
                    print(f"Error al mostrar GUI de configuración: {e}")
                    traceback.print_exc()
                    print(f"Usando valores por defecto: {self.DEFAULT_SERVER_URL}")
        else:
            if not self.is_service:
                try:
                    from config_gui import show_config_window
                    updated = show_config_window(client=self)
                    if updated:
                        config_data = updated
                except Exception as e:
                    print(f"Advertencia: No se pudo mostrar GUI de configuración: {e}")

        if config_data:
            self.server_url = config_data.get('server_url', self.DEFAULT_SERVER_URL)
            self.check_interval = config_data.get('check_interval', self.DEFAULT_CHECK_INTERVAL)
            self.sync_interval = config_data.get('sync_interval', self.DEFAULT_SYNC_INTERVAL)

        known = self.load_servers()
        if known:
            print(f"[Inicio] Servidores conocidos: {len(known)}")
            print(f"[Inicio] Servidores: {', '.join([s.get('url', '?') for s in known])}")

    # ==================== ALERTS ====================

    def _load_alert_thresholds(self):
        try:
            config = self.load_config()
            if config and 'alert_thresholds' in config:
                t = config['alert_thresholds']
                if isinstance(t, list) and len(t) > 0:
                    return sorted(t, reverse=True)
        except Exception:
            pass
        return sorted(self.DEFAULT_ALERT_THRESHOLDS, reverse=True)

    def update_alert_thresholds(self, new_thresholds):
        if isinstance(new_thresholds, list) and len(new_thresholds) > 0:
            new_thresholds = sorted(new_thresholds, reverse=True)
            if new_thresholds != self.alert_thresholds:
                print(f"[Config] Umbrales de alerta actualizados: {self.alert_thresholds} -> {new_thresholds}")
                self.alert_thresholds = new_thresholds
                self.alerts_shown = {t: False for t in self.alert_thresholds}

    def reset_alerts_for_new_session(self, remaining_seconds):
        for threshold in self.alert_thresholds:
            self.alerts_shown[threshold] = remaining_seconds <= threshold
        self.last_known_remaining = remaining_seconds

    def check_and_show_alerts(self, remaining_seconds, previous_remaining=None):
        if previous_remaining is not None and previous_remaining - remaining_seconds > 120:
            self.reset_alerts_for_new_session(remaining_seconds)

        for threshold in sorted(self.alert_thresholds, reverse=True):
            if remaining_seconds <= threshold and not self.alerts_shown.get(threshold, False):
                self._show_time_alert(threshold, remaining_seconds)
                self.alerts_shown[threshold] = True
                break

        self.last_known_remaining = remaining_seconds

    @staticmethod
    def _get_alert_message(threshold, remaining_seconds):
        if threshold == 600:
            return "[WARN] AVISO: Te quedan 10 minutos de tiempo.\n\nGuarda tu trabajo."
        elif threshold == 300:
            return "[WARN] ATENCIÓN: Te quedan 5 minutos de tiempo.\n\nPrepárate para terminar."
        elif threshold == 120:
            return "[WARN] ADVERTENCIA: Te quedan solo 2 minutos.\n\n¡Guarda todo ahora!"
        elif threshold == 60:
            return "[ALERTA] ¡ULTIMO MINUTO!\n\nLa PC se bloqueara en 1 minuto.\n¡Guarda tu trabajo inmediatamente!"
        return f"Quedan {threshold // 60} minutos."

    def _show_time_alert(self, threshold, remaining_seconds):
        try:
            message = self._get_alert_message(threshold, remaining_seconds)
            is_warning = threshold <= 120
            if threshold <= 60:
                title = "[WARN] ¡TIEMPO CASI AGOTADO!"
            elif threshold <= 120:
                title = "[WARN] Advertencia de Tiempo"
            else:
                title = "Aviso de Tiempo"

            self.show_alert(title, message, is_warning=is_warning)
            print(f"\n[ALERTA] {title}: {threshold // 60} minuto(s) restante(s)")
        except Exception as e:
            print(f"Error al mostrar alerta: {e}")

    # ==================== CLIENT ID ====================

    def get_client_id(self):
        client_id = self.load_client_id()
        if client_id:
            return client_id

        if os.path.exists(self.client_id_file):
            with open(self.client_id_file, 'r') as f:
                client_id = f.read().strip()
                if client_id:
                    self.save_client_id(client_id)
                    return client_id

        client_id = self.register_new_client()
        if client_id:
            return client_id

        import uuid
        client_id = str(uuid.uuid4())
        print(f"[Inicio] No se pudo contactar ningún servidor. Generando ID local: {client_id}")

        try:
            with open(self.client_id_file, 'w') as f:
                f.write(client_id)
        except Exception as e:
            print(f"[Inicio] Advertencia: No se pudo guardar ID en archivo: {e}")

        self.save_client_id(client_id)
        return client_id

    # ==================== SERVERS ====================

    def get_available_servers(self):
        servers = []
        seen_urls = set()

        known_servers = self.load_servers()
        known_sorted = sorted(known_servers, key=lambda s: s.get('last_seen', ''), reverse=True)
        for srv in known_sorted:
            url = srv.get('url')
            if url:
                servers.append({'url': url, 'priority': 0, 'last_seen': srv.get('last_seen', ''), 'source': 'discovered'})
                seen_urls.add(url)

        if self.server_url and self.server_url not in seen_urls:
            servers.append({'url': self.server_url, 'priority': 0, 'source': 'configured'})

        return servers

    def find_available_server(self, servers_list=None):
        if servers_list is None:
            servers_list = self.get_available_servers()

        servers_list.sort(key=lambda x: (x.get('priority', 1), x.get('last_seen', '')), reverse=True)

        failed = []
        for srv in servers_list:
            url = srv.get('url')
            if not url:
                continue
            try:
                r = requests.get(f"{url}/api/health", timeout=3)
                if r.status_code == 200:
                    self.reset_server_timeout_count(url)
                    return url
                else:
                    failed.append(url)
            except Exception:
                failed.append(url)

        if failed:
            self.increment_server_timeouts(failed)
        return None

    # ==================== REGISTER ====================

    def register_new_client(self, existing_client_id=None):
        try:
            client_name = socket.gethostname()
            custom_name = None
            config_data = self.load_config()
            if config_data:
                custom_name = config_data.get('custom_name')

            data = {'name': custom_name if custom_name else client_name}
            if existing_client_id:
                data['client_id'] = existing_client_id

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                data['client_ip'] = s.getsockname()[0]
                s.close()
                data['diagnostic_port'] = 5002
            except Exception:
                pass

            session_info = self.get_session_info()
            if session_info:
                session_data = self.get_session()
                if session_data:
                    remaining = max(0, session_info['remaining_seconds'])
                    data['session'] = {
                        'remaining_seconds': remaining,
                        'time_limit_seconds': session_data.get('time_limit_seconds', remaining or 0)
                    }

            if config_data:
                data['config'] = {
                    'sync_interval': config_data.get('sync_interval', 30),
                    'alert_thresholds': config_data.get('alert_thresholds', [600, 300, 120, 60]),
                    'custom_name': custom_name
                }

            data['known_servers'] = self.load_servers()

            servers_list = self.get_available_servers()
            available = self.find_available_server(servers_list)
            if not available:
                print("[Registro] No hay servidores disponibles para registrar el cliente")
                return None

            response = requests.post(f"{available}/api/register", json=data, timeout=10)

            if response.status_code == 201:
                resp = response.json()
                client_id = resp['client_id']
                known_servers_resp = resp.get('known_servers', [])

                if known_servers_resp:
                    self._merge_servers(known_servers_resp)

                try:
                    with open(self.client_id_file, 'w') as f:
                        f.write(client_id)
                except Exception:
                    pass

                self.save_client_id(client_id)

                server_config = resp.get('config')
                if server_config:
                    self.apply_server_config(server_config)

                print(f"[Registro] Cliente {'re-' if existing_client_id else ''}registrado: {client_id[:8]}...")
                return client_id
            else:
                print(f"Error al registrar cliente: {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión al servidor: {e}")
            return None

    def _merge_servers(self, received_servers):
        current = self.load_servers()
        current_urls = {s.get('url') for s in current}
        for srv in received_servers:
            url = srv.get('url')
            if not url:
                continue
            if url in current_urls:
                for s in current:
                    if s.get('url') == url:
                        s['last_seen'] = datetime.now().isoformat()
                        s['timeout_count'] = 0
                        break
            else:
                srv.setdefault('timeout_count', 0)
                srv.setdefault('last_seen', datetime.now().isoformat())
                current.append(srv)
        self.save_servers(current)

    # ==================== SERVER CONFIG ====================

    def apply_server_config(self, server_config):
        if not server_config:
            return
        try:
            current = self.load_config() or {}

            if 'sync_interval' in server_config:
                val = server_config['sync_interval']
                if val != current.get('sync_interval'):
                    print(f"[Config] Intervalo de sincronización: {current.get('sync_interval', 30)} -> {val}")
                    current['sync_interval'] = val
                    self.sync_interval = val

            if 'alert_thresholds' in server_config:
                val = server_config['alert_thresholds']
                self.update_alert_thresholds(val)
                current['alert_thresholds'] = val

            if 'custom_name' in server_config:
                val = server_config['custom_name']
                old = current.get('custom_name')
                if val != old:
                    print(f"[Config] Nombre personalizado: {old or '(ninguno)'} -> {val or '(equipo)'}")
                    current['custom_name'] = val

            if 'max_server_timeouts' in server_config:
                val = server_config['max_server_timeouts']
                if isinstance(val, int) and val > 0:
                    old = current.get('max_server_timeouts', 10)
                    if val != old:
                        print(f"[Config] Reintentos máx.: {old} -> {val}")
                        current['max_server_timeouts'] = val

            if 'lock_recheck_interval' in server_config:
                val = server_config['lock_recheck_interval']
                if isinstance(val, int) and 1 <= val <= 60:
                    old = current.get('lock_recheck_interval', 1)
                    if val != old:
                        print(f"[Config] Intervalo de re-bloqueo: {old} -> {val}s")
                        current['lock_recheck_interval'] = val
                    self.lock_recheck_interval = val

            current['server_url'] = current.get('server_url', self.server_url)
            self.save_config(current)
        except Exception as e:
            print(f"[Config] Error al aplicar configuración del servidor: {e}")

    # ==================== SESSION REPORTING ====================

    def report_session_to_server(self, client_id, server_url=None):
        session_info = self.get_session_info()
        if not session_info or session_info['is_expired'] or session_info['remaining_seconds'] <= 0:
            return False

        session_data = self.get_session()
        if not session_data:
            return False

        if not server_url:
            available = self.find_available_server()
            if not available:
                return False
            server_url = available

        try:
            r = requests.post(
                f"{server_url}/api/client/{client_id}/report-session",
                json={
                    'remaining_seconds': session_info['remaining_seconds'],
                    'time_limit_seconds': session_data.get('time_limit_seconds', session_info['remaining_seconds'])
                },
                timeout=10
            )
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def check_server_status(self, client_id):
        available = self.find_available_server()
        if not available:
            print("[Status] No hay servidores disponibles")
            return None
        try:
            r = requests.get(f"{available}/api/client/{client_id}/status", timeout=10)
            if r.status_code == 200:
                return r.json().get('client', {})
            elif r.status_code == 404:
                print("Cliente no encontrado en el servidor (404).")
                return None
            else:
                print(f"Error al obtener estado: {r.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión: {e}")
            return None

    # ==================== SYNC (ALL SERVERS) ====================

    def sync_with_all_servers(self, client_id):
        servers_list = self.get_available_servers()
        if not servers_list:
            return False

        known_servers = self.load_servers()
        success_count = 0
        failed_servers = []

        for server_info in servers_list:
            server_url = server_info.get('url')
            if not server_url:
                continue
            try:
                health = requests.get(f"{server_url}/api/health", timeout=3)
                if health.status_code != 200:
                    failed_servers.append(server_url)
                    continue

                r = requests.get(f"{server_url}/api/client/{client_id}/status", timeout=10)

                if r.status_code == 404:
                    new_id = self.register_new_client(existing_client_id=client_id)
                    if new_id:
                        client_id = new_id
                        success_count += 1
                        self.reset_server_timeout_count(server_url)
                    else:
                        failed_servers.append(server_url)
                    continue

                if r.status_code != 200:
                    failed_servers.append(server_url)
                    continue

                self.reset_server_timeout_count(server_url)
                data = r.json()
                client_data = data.get('client', {})

                if 'known_servers' in data:
                    self._merge_servers(data.get('known_servers', []))

                server_config = client_data.get('config')
                if server_config:
                    self.apply_server_config(server_config)

                session = client_data.get('session')
                if session and success_count == 0:
                    tl = session.get('time_limit_seconds', 0)
                    st = session.get('start_time')
                    et = session.get('end_time')
                    rem = session.get('remaining_seconds', 0)
                    if all([tl, st, et]):
                        now = datetime.now()
                        end_local = now + timedelta(seconds=rem)
                        start_local = now - timedelta(seconds=tl - rem)
                        self.save_session(tl, start_local.isoformat(), end_local.isoformat())
                        self.last_known_remaining = rem

                if known_servers:
                    try:
                        sr = requests.post(f"{server_url}/api/sync-servers", json={'servers': known_servers}, timeout=5)
                        if sr.status_code == 200:
                            updated = sr.json().get('known_servers', [])
                            if updated:
                                self.save_servers(updated)
                    except Exception:
                        pass

                success_count += 1
            except requests.exceptions.RequestException:
                failed_servers.append(server_url)
            except Exception:
                failed_servers.append(server_url)

        if failed_servers:
            self.increment_server_timeouts(failed_servers)
        return client_id if success_count > 0 else False

    # ==================== DISCOVERY ====================

    def start_server_discovery_listener(self):
        def listener_thread():
            DISCOVERY_PORT = 5001
            broadcast_count = 0

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                except Exception:
                    pass
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

                try:
                    sock.bind(('0.0.0.0', DISCOVERY_PORT))
                    print(f"[Discovery] [OK] Socket vinculado a 0.0.0.0:{DISCOVERY_PORT}")
                except OSError as e:
                    if e.errno in (10048, errno.EADDRINUSE):
                        print(f"[Discovery] [ERROR] Puerto {DISCOVERY_PORT} ya en uso")
                        return
                    raise

                sock.settimeout(1.0)
                print(f"[Discovery] [OK] Escuchando broadcasts en puerto {DISCOVERY_PORT}...")
                self._discovery_stats['listener_started'] = True

                last_status_log = time.time()
                known_urls = set()

                while True:
                    try:
                        data, addr = sock.recvfrom(1024)
                        broadcast_count += 1
                        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        self._update_discovery_stats(
                            broadcast_count=broadcast_count,
                            last_broadcast_time=now_str,
                            last_broadcast_from=addr[0]
                        )

                        try:
                            info = json.loads(data.decode('utf-8'))
                        except json.JSONDecodeError:
                            continue

                        srv_url = info.get('url')
                        srv_ip = info.get('ip', addr[0])
                        srv_port = info.get('port', 5000)

                        if srv_url:
                            self._update_discovery_stats(server_url=srv_url)

                        if srv_url:
                            is_new = srv_url not in known_urls

                            servers = self.load_servers()
                            exists = False
                            for s in servers:
                                if s.get('url') == srv_url:
                                    s['last_seen'] = datetime.now().isoformat()
                                    if srv_ip:
                                        s['ip'] = srv_ip
                                    if srv_port:
                                        s['port'] = srv_port
                                    self.save_servers(servers)
                                    exists = True
                                    break

                            if not exists:
                                servers.append({
                                    'url': srv_url, 'ip': srv_ip, 'port': srv_port,
                                    'last_seen': datetime.now().isoformat()
                                })
                                self.save_servers(servers)
                                print(f"[Discovery] Nuevo servidor registrado: {srv_url}")

                            if is_new:
                                known_urls.add(srv_url)
                                print(f"[Discovery] Servidor detectado: {srv_url} ({srv_ip}:{srv_port})")
                                try:
                                    requests.post(
                                        f"{srv_url}/api/register-server",
                                        json={'url': srv_url, 'ip': srv_ip, 'port': srv_port},
                                        timeout=2
                                    )
                                except Exception:
                                    pass

                    except socket.timeout:
                        now = time.time()
                        if now - last_status_log >= 60:
                            if broadcast_count == 0:
                                print("[Discovery] Sin broadcasts recibidos aún")
                            last_status_log = now
                    except Exception as e:
                        print(f"[Discovery] Error: {e}")

            except OSError as e:
                if e.errno in (10048, errno.EADDRINUSE):
                    print(f"[Discovery] [ERROR] Puerto {DISCOVERY_PORT} ya en uso (crítico)")
                else:
                    print(f"[Discovery] [ERROR] {e}")
                time.sleep(10)
                self.start_server_discovery_listener()
            except Exception as e:
                print(f"[Discovery] [ERROR] {e}")
                time.sleep(5)
                self.start_server_discovery_listener()

        thread = threading.Thread(target=listener_thread, daemon=True)
        thread.start()
        print(f"[Discovery] Thread de descubrimiento iniciado")

    def _update_discovery_stats(self, broadcast_count=None, last_broadcast_time=None,
                                last_broadcast_from=None, server_url=None):
        if broadcast_count is not None:
            self._discovery_stats['broadcast_count'] = broadcast_count
        if last_broadcast_time is not None:
            self._discovery_stats['last_broadcast_time'] = last_broadcast_time
        if last_broadcast_from is not None:
            self._discovery_stats['last_broadcast_from'] = last_broadcast_from
        if server_url is not None:
            self._discovery_stats['servers_discovered'].add(server_url)

    # ==================== DIAGNOSTIC SERVER ====================

    def start_diagnostic_server(self, port=5002):
        handler_class = _make_diagnostic_handler(self)

        def server_thread():
            try:
                server = HTTPServer(('0.0.0.0', port), handler_class)
                self._diagnostic_server = server

                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    s.close()
                except Exception:
                    local_ip = "0.0.0.0"

                print(f"[Diagnóstico] Servidor iniciado en http://{local_ip}:{port}")
                server.serve_forever()
            except OSError as e:
                if e.errno in (10048, errno.EADDRINUSE):
                    print(f"[Diagnóstico] [WARN] Puerto {port} ya en uso")
                else:
                    print(f"[Diagnóstico] [ERROR] {e}")
            except Exception as e:
                print(f"[Diagnóstico] [ERROR] {e}")

        threading.Thread(target=server_thread, daemon=True).start()

    # ==================== MONITOR ====================

    def monitor_time(self, client_id):
        print("=" * 50)
        print("Cliente CiberMonday iniciado")
        print("=" * 50)
        print(f"ID del cliente: {client_id}")
        print(f"Servidor configurado: {self.server_url}")
        print("Esperando asignación de tiempo...")
        print("=" * 50)

        self.setup_firewall()
        self.start_server_discovery_listener()
        self.start_diagnostic_server(port=5002)

        try:
            cfg = self.load_config()
            if cfg and 'lock_recheck_interval' in cfg:
                self.lock_recheck_interval = int(cfg['lock_recheck_interval'])
                print(f"[Config] Intervalo de re-bloqueo: {self.lock_recheck_interval}s")
        except Exception:
            pass

        self._sync_manager = SyncManager(self, client_id, self.sync_interval)
        self._sync_manager.start()

        last_remaining = None
        print(f"Intervalo de sincronización: {self.sync_interval} segundos")

        while True:
            try:
                client_id = self._sync_manager.client_id

                session_info = self.get_session_info()

                if session_info is None:
                    if last_remaining is not None:
                        print("\rEsperando asignación de tiempo...", end='', flush=True)
                        self.alerts_shown = {t: False for t in self.alert_thresholds}
                        last_remaining = None
                    time.sleep(1)
                    continue

                remaining = session_info['remaining_seconds']
                expired = session_info['is_expired']

                if last_remaining is None:
                    self.reset_alerts_for_new_session(remaining)

                if expired or remaining <= 0:
                    first_expiry = last_remaining is None or last_remaining > 0
                    if first_expiry:
                        print("\n" + "=" * 50, flush=True)
                        print("[EXPIRACION] TIEMPO AGOTADO!", flush=True)
                        print("[EXPIRACION] Bloqueando PC.", flush=True)
                        print("=" * 50, flush=True)
                        result = self.lock_workstation()
                        if not result:
                            print("[EXPIRACION] FALLO: No se pudo bloquear", flush=True)
                    else:
                        if self.is_user_session_active():
                            print("[EXPIRACION] Usuario reconecto. Bloqueando de nuevo...", flush=True)
                            self.lock_workstation()

                    last_remaining = remaining
                    time.sleep(self.lock_recheck_interval)
                    continue

                self.check_and_show_alerts(remaining, last_remaining)

                if last_remaining != remaining:
                    print(f"\rTiempo restante: {self.format_time(remaining)}", end='', flush=True)
                    last_remaining = remaining

                time.sleep(1)

            except KeyboardInterrupt:
                print("\n\nCliente detenido por el usuario.")
                self._sync_manager.stop()
                break
            except Exception as e:
                print(f"\nError inesperado: {e}")
                time.sleep(1)


# ==================== SYNC MANAGER ====================

class SyncManager:

    def __init__(self, client, client_id, sync_interval):
        self._client = client
        self._client_id = client_id
        self._sync_interval = sync_interval
        self._client_registered = False
        self._consecutive_failures = 0
        self._last_successful_server = None
        self._running = True
        self._thread = None
        self._lock = threading.Lock()

    @property
    def client_id(self):
        with self._lock:
            return self._client_id

    @client_id.setter
    def client_id(self, value):
        with self._lock:
            self._client_id = value

    @property
    def client_registered(self):
        with self._lock:
            return self._client_registered

    @property
    def consecutive_failures(self):
        with self._lock:
            return self._consecutive_failures

    @property
    def last_successful_server(self):
        with self._lock:
            return self._last_successful_server

    def start(self):
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        print(f"[SyncManager] Hilo iniciado (intervalo: {self._sync_interval}s)")

    def stop(self):
        self._running = False

    def _sync_loop(self):
        self._do_sync()
        while self._running:
            for _ in range(int(self._sync_interval)):
                if not self._running:
                    return
                time.sleep(1)
            self._do_sync()

    def _do_sync(self):
        try:
            cid = self.client_id
            servers_list = self._client.get_available_servers()

            if not servers_list:
                with self._lock:
                    self._consecutive_failures += 1
                if self._consecutive_failures == 1:
                    print("[SyncManager] No hay servidores conocidos.")
                elif self._consecutive_failures % 5 == 0:
                    print(f"[SyncManager] {self._consecutive_failures} ciclos sin servidores.")
                return

            urls = [s.get('url', '?') for s in servers_list]
            print(f"[SyncManager] Sincronizando con {len(servers_list)} servidor(es): {', '.join(urls)}")

            any_success = False
            all_failed = True

            for srv_info in servers_list:
                srv_url = srv_info.get('url')
                if not srv_url:
                    continue
                try:
                    print(f"[SyncManager]   -> Verificando {srv_url} ...", flush=True)
                    h = requests.get(f"{srv_url}/api/health", timeout=3)
                    if h.status_code != 200:
                        print(f"[SyncManager] {srv_url} - health check falló ({h.status_code})")
                        continue
                except requests.exceptions.RequestException as e:
                    print(f"[SyncManager] {srv_url} - health check falló ({type(e).__name__})")
                    continue

                all_failed = False
                success = self._sync_with_server(cid, srv_url)
                if success:
                    print(f"[SyncManager] [OK] Sync exitoso con {srv_url}")
                    any_success = True
                    self._client.reset_server_timeout_count(srv_url)
                else:
                    print(f"[SyncManager] [ERROR] Sync fallido con {srv_url}")
                    self._client.increment_server_timeouts([srv_url])

            if all_failed:
                with self._lock:
                    self._consecutive_failures += 1
                if self._consecutive_failures == 1:
                    print(f"[SyncManager] Ningún servidor respondió.")
                elif self._consecutive_failures % 5 == 0:
                    print(f"[SyncManager] {self._consecutive_failures} intentos fallidos.")
                if not self._client_registered:
                    self._try_register(cid)
                return

            if any_success:
                with self._lock:
                    self._consecutive_failures = 0
                    self._client_registered = True
            else:
                with self._lock:
                    self._consecutive_failures += 1

        except Exception as e:
            with self._lock:
                self._consecutive_failures += 1
            print(f"[SyncManager] Error: {e}")

    def _try_register(self, cid):
        try:
            print("[SyncManager] Intentando registrar...")
            new_id = self._client.register_new_client(existing_client_id=cid)
            if new_id:
                self.client_id = new_id
                with self._lock:
                    self._client_registered = True
                    self._consecutive_failures = 0
                print(f"[SyncManager] [OK] Registrado: {new_id}")
        except Exception as e:
            print(f"[SyncManager] Error al registrar: {e}")

    def _sync_with_server(self, cid, server_url):
        try:
            r = requests.get(f"{server_url}/api/client/{cid}/status", timeout=10)

            if r.status_code == 404:
                print(f"[SyncManager] Registrando en {server_url}...")
                return self._register_on_server(cid, server_url)

            if r.status_code != 200:
                return False

            self._client.reset_server_timeout_count(server_url)
            data = r.json()

            if 'known_servers' in data:
                self._client._merge_servers(data.get('known_servers', []))

            self._report_state(cid, server_url)

            known = self._client.load_servers()
            if known:
                self._send_servers(known, server_url)

            return True

        except requests.exceptions.RequestException as e:
            print(f"[SyncManager] Error de conexión con {server_url}: {e}")
            self._client.increment_server_timeouts([server_url])
            return False
        except Exception as e:
            print(f"[SyncManager] Error con {server_url}: {e}")
            return False

    def _report_state(self, cid, server_url):
        session_info = self._client.get_session_info()
        if session_info and not session_info['is_expired'] and session_info['remaining_seconds'] > 0:
            self._client.report_session_to_server(cid, server_url=server_url)
        else:
            try:
                time_limit = 0
                if session_info:
                    sd = self._client.get_session()
                    if sd:
                        time_limit = sd.get('time_limit_seconds', 0)
                requests.post(
                    f"{server_url}/api/client/{cid}/report-session",
                    json={'remaining_seconds': 0, 'time_limit_seconds': time_limit},
                    timeout=5
                )
            except Exception:
                pass

        try:
            cfg = self._client.load_config()
            if cfg:
                payload = {}
                for key in ('custom_name', 'sync_interval', 'alert_thresholds',
                            'max_server_timeouts', 'lock_recheck_interval'):
                    if cfg.get(key):
                        payload[key] = cfg[key]
                if payload:
                    payload['from_client'] = True
                    requests.post(f"{server_url}/api/client/{cid}/config", json=payload, timeout=5)
        except Exception:
            pass

    def _register_on_server(self, cid, server_url):
        try:
            client_name = socket.gethostname()
            custom_name = None
            config_data = self._client.load_config()
            if config_data:
                custom_name = config_data.get('custom_name')

            data = {'name': custom_name or client_name, 'client_id': cid}

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                data['client_ip'] = s.getsockname()[0]
                s.close()
                data['diagnostic_port'] = 5002
            except Exception:
                pass

            session_info = self._client.get_session_info()
            if session_info:
                sd = self._client.get_session()
                if sd:
                    remaining = max(0, session_info['remaining_seconds'])
                    data['session'] = {
                        'remaining_seconds': remaining,
                        'time_limit_seconds': sd.get('time_limit_seconds', remaining or 0)
                    }

            if config_data:
                data['config'] = {
                    'sync_interval': config_data.get('sync_interval', 30),
                    'alert_thresholds': config_data.get('alert_thresholds', [600, 300, 120, 60]),
                    'custom_name': custom_name
                }

            data['known_servers'] = self._client.load_servers()

            r = requests.post(f"{server_url}/api/register", json=data, timeout=10)
            if r.status_code == 201:
                resp = r.json()
                known_resp = resp.get('known_servers', [])
                if known_resp:
                    self._client._merge_servers(known_resp)
                print(f"[SyncManager] Registrado en {server_url}")
                return True
            else:
                print(f"[SyncManager] Error al registrar en {server_url}: {r.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"[SyncManager] Error de conexión al registrar en {server_url}: {e}")
            return False
        except Exception as e:
            print(f"[SyncManager] Error al registrar en {server_url}: {e}")
            return False

    def _send_servers(self, known_servers, server_url):
        try:
            r = requests.post(f"{server_url}/api/sync-servers", json={'servers': known_servers}, timeout=5)
            if r.status_code == 200:
                updated = r.json().get('known_servers', [])
                if updated:
                    self._client.save_servers(updated)
        except Exception:
            pass


# ==================== DIAGNOSTIC HANDLER (factory) ====================

def _make_diagnostic_handler(client):
    """Crea la clase DiagnosticHandler con referencia al client."""

    class DiagnosticHandler(BaseHTTPRequestHandler):

        def log_message(self, format, *args):
            pass

        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/api/diagnostic':
                self._send_diagnostic()
            elif path == '/api/servers':
                self._send_servers()
            elif path == '/api/status':
                self._send_status()
            elif path == '/api/discovery':
                self._send_discovery()
            elif path == '/api/test-connectivity':
                self._send_connectivity()
            elif path == '/':
                self._send_dashboard()
            else:
                self._json({'error': 'Not found'}, 404)

        def do_POST(self):
            path = self.path.split('?')[0]
            if path == '/api/add-server':
                self._handle_add_server()
            elif path == '/api/push/session':
                self._handle_push_session()
            elif path == '/api/push/config':
                self._handle_push_config()
            elif path == '/api/push/stop':
                self._handle_push_stop()
            else:
                self._json({'error': 'Not found'}, 404)

        def _read_body(self):
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                return None
            return json.loads(self.rfile.read(length).decode('utf-8'))

        def _json(self, data, status=200):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))

        def _handle_push_session(self):
            try:
                data = self._read_body()
                if not data:
                    self._json({'success': False, 'message': 'No data'}, 400)
                    return

                tl = data.get('time_limit_seconds', 0)
                rem = data.get('remaining_seconds', 0)
                if not all([tl, rem]):
                    self._json({'success': False, 'message': 'Datos incompletos'}, 400)
                    return

                now = datetime.now()
                end_local = now + timedelta(seconds=rem)
                start_local = now - timedelta(seconds=tl - rem)

                client.save_session(tl, start_local.isoformat(), end_local.isoformat())
                client.reset_alerts_for_new_session(rem)
                client.last_known_remaining = rem

                print(f"[Push] Sesión recibida: {rem}s restantes ({tl}s total)")
                self._trigger_propagation()
                self._json({'success': True, 'message': f'Sesión actualizada: {rem}s restantes'})
            except json.JSONDecodeError:
                self._json({'success': False, 'message': 'Invalid JSON'}, 400)
            except Exception as e:
                print(f"[Push] Error: {e}")
                self._json({'success': False, 'message': str(e)}, 500)

        def _handle_push_config(self):
            try:
                data = self._read_body()
                if not data:
                    self._json({'success': False, 'message': 'No data'}, 400)
                    return
                client.apply_server_config(data)
                print(f"[Push] Config recibida: {data}")
                self._trigger_propagation()
                self._json({'success': True, 'message': 'Configuración actualizada'})
            except json.JSONDecodeError:
                self._json({'success': False, 'message': 'Invalid JSON'}, 400)
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        def _handle_push_stop(self):
            try:
                client.clear_session()
                print("[Push] Sesión detenida por el servidor")
                self._trigger_propagation()
                self._json({'success': True, 'message': 'Sesión detenida'})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        def _trigger_propagation(self):
            def _propagate():
                try:
                    cid = client.get_client_id()
                    if not cid:
                        return
                    servers_list = client.get_available_servers()
                    session_info = client.get_session_info()

                    for srv_info in servers_list:
                        srv_url = srv_info.get('url')
                        if not srv_url:
                            continue
                        try:
                            h = requests.get(f"{srv_url}/api/health", timeout=3)
                            if h.status_code != 200:
                                continue
                            if session_info and not session_info['is_expired'] and session_info['remaining_seconds'] > 0:
                                client.report_session_to_server(cid, server_url=srv_url)
                            else:
                                tl = 0
                                if session_info:
                                    sd = client.get_session()
                                    if sd:
                                        tl = sd.get('time_limit_seconds', 0)
                                requests.post(
                                    f"{srv_url}/api/client/{cid}/report-session",
                                    json={'remaining_seconds': 0, 'time_limit_seconds': tl},
                                    timeout=5
                                )
                        except Exception:
                            pass
                except Exception:
                    pass
            threading.Thread(target=_propagate, daemon=True).start()

        def _handle_add_server(self):
            try:
                data = self._read_body()
                if not data:
                    self._json({'success': False, 'message': 'No data'}, 400)
                    return
                srv_url = data.get('url')
                srv_ip = data.get('ip')
                srv_port = data.get('port', 5000)
                if not srv_url:
                    self._json({'success': False, 'message': 'URL required'}, 400)
                    return

                servers = client.load_servers()
                current_urls = {s.get('url') for s in servers}

                if srv_url not in current_urls:
                    servers.append({
                        'url': srv_url, 'ip': srv_ip, 'port': srv_port,
                        'last_seen': datetime.now().isoformat(), 'timeout_count': 0
                    })
                    client.save_servers(servers)
                    print(f"[Notificación] Nuevo servidor: {srv_url}")
                    self._json({'success': True, 'message': f'Servidor {srv_url} agregado'})
                else:
                    for s in servers:
                        if s.get('url') == srv_url:
                            s['last_seen'] = datetime.now().isoformat()
                            s['timeout_count'] = 0
                            if srv_ip:
                                s['ip'] = srv_ip
                            if srv_port:
                                s['port'] = srv_port
                            break
                    client.save_servers(servers)
                    self._json({'success': True, 'message': f'Servidor {srv_url} actualizado'})
            except json.JSONDecodeError:
                self._json({'success': False, 'message': 'Invalid JSON'}, 400)
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        def _send_status(self):
            cid = client.load_client_id()
            si = client.get_session_info()
            self._json({
                'success': True, 'client_id': cid,
                'server_url': client.server_url,
                'registry_available': True,
                'has_session': si is not None and not si.get('is_expired', True),
                'remaining_seconds': si.get('remaining_seconds', 0) if si else 0
            })

        def _send_discovery(self):
            ds = client._discovery_stats
            self._json({
                'success': True,
                'listener_active': ds['listener_started'],
                'broadcast_count': ds['broadcast_count'],
                'last_broadcast_time': ds['last_broadcast_time'],
                'last_broadcast_from': ds['last_broadcast_from'],
                'servers_discovered_count': len(ds['servers_discovered']),
                'servers_discovered': list(ds['servers_discovered'])
            })

        def _send_servers(self):
            servers = client.load_servers()
            for s in servers:
                url = s.get('url')
                if url:
                    try:
                        r = requests.get(f"{url}/api/health", timeout=2)
                        s['available'] = r.status_code == 200
                    except Exception:
                        s['available'] = False
            self._json({'success': True, 'servers': servers, 'count': len(servers)})

        def _send_diagnostic(self):
            cid = client.load_client_id()
            si = client.get_session_info()
            servers = client.load_servers()
            for s in servers:
                url = s.get('url')
                if url:
                    try:
                        r = requests.get(f"{url}/api/health", timeout=2)
                        s['available'] = r.status_code == 200
                    except Exception:
                        s['available'] = False
            ds = client._discovery_stats
            self._json({
                'success': True, 'client_id': cid,
                'server_url': client.server_url,
                'registry_available': True,
                'session': si, 'known_servers': servers,
                'discovery': {
                    'listener_active': ds['listener_started'],
                    'broadcast_count': ds['broadcast_count'],
                    'last_broadcast_time': ds['last_broadcast_time'],
                    'last_broadcast_from': ds['last_broadcast_from'],
                    'servers_discovered': list(ds['servers_discovered'])
                }
            })

        def _send_connectivity(self):
            results = []
            servers = client.load_servers()
            known_urls = {s.get('url') for s in servers}
            if client.server_url and client.server_url not in known_urls:
                servers.append({'url': client.server_url, 'source': 'configured'})
            for srv in servers:
                url = srv.get('url')
                if not url:
                    continue
                result = {'url': url, 'ip': srv.get('ip', '?'), 'timeout_count': srv.get('timeout_count', 0)}
                try:
                    t0 = time.time()
                    r = requests.get(f"{url}/api/health", timeout=5)
                    elapsed = round((time.time() - t0) * 1000)
                    result['health'] = {'status': r.status_code, 'ok': r.status_code == 200, 'elapsed_ms': elapsed}
                except requests.exceptions.ConnectTimeout:
                    result['health'] = {'ok': False, 'error': 'ConnectTimeout'}
                except requests.exceptions.ConnectionError as e:
                    result['health'] = {'ok': False, 'error': f'ConnectionError: {str(e)[:200]}'}
                except Exception as e:
                    result['health'] = {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:200]}'}
                if result['health'].get('ok'):
                    try:
                        cid = client.load_client_id()
                        if cid:
                            t0 = time.time()
                            r = requests.get(f"{url}/api/client/{cid}/status", timeout=5)
                            elapsed = round((time.time() - t0) * 1000)
                            result['status_check'] = {
                                'http_status': r.status_code, 'elapsed_ms': elapsed,
                                'registered': r.status_code == 200
                            }
                    except Exception as e:
                        result['status_check'] = {'error': str(e)[:200]}
                results.append(result)
            self._json({
                'success': True, 'tests': results,
                'client_ip': socket.gethostbyname(socket.gethostname()),
                'timestamp': datetime.now().isoformat()
            })

        def _send_dashboard(self):
            html = """<!DOCTYPE html>
<html>
<head>
    <title>CiberMonday - Diagnóstico del Cliente</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .card { background: white; padding: 20px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #333; } h2 { color: #667eea; border-bottom: 2px solid #667eea; padding-bottom: 5px; }
        .status { padding: 5px 10px; border-radius: 3px; display: inline-block; }
        .status.ok { background: #4CAF50; color: white; }
        .status.error { background: #f44336; color: white; }
        .status.warning { background: #ff9800; color: white; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f5f5f5; }
        .refresh-btn { background: #667eea; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="container">
        <h1>CiberMonday - Diagnóstico del Cliente</h1>
        <button class="refresh-btn" onclick="location.reload()">Actualizar</button>
        <div class="card"><h2>Estado General</h2><div id="status-info">Cargando...</div></div>
        <div class="card"><h2>Descubrimiento de Servidores</h2><div id="discovery-info">Cargando...</div></div>
        <div class="card"><h2>Servidores Conocidos</h2><div id="servers-info">Cargando...</div></div>
        <div class="card"><h2>Información Completa</h2><pre id="full-info">Cargando...</pre></div>
    </div>
    <script>
        async function loadData() {
            try {
                const [status, discovery, servers, diagnostic] = await Promise.all([
                    fetch('/api/status').then(r => r.json()),
                    fetch('/api/discovery').then(r => r.json()),
                    fetch('/api/servers').then(r => r.json()),
                    fetch('/api/diagnostic').then(r => r.json())
                ]);
                document.getElementById('status-info').innerHTML = `
                    <p><strong>Cliente ID:</strong> ${status.client_id || 'N/A'}</p>
                    <p><strong>Servidor Principal:</strong> ${status.server_url || 'N/A'}</p>
                    <p><strong>Sesión Activa:</strong> <span class="status ${status.has_session ? 'ok' : 'warning'}">${status.has_session ? 'Sí' : 'No'}</span></p>
                    ${status.has_session ? `<p><strong>Tiempo Restante:</strong> ${status.remaining_seconds || 0}s</p>` : ''}`;
                document.getElementById('discovery-info').innerHTML = `
                    <p><strong>Listener:</strong> <span class="status ${discovery.listener_active ? 'ok' : 'error'}">${discovery.listener_active ? 'Activo' : 'Inactivo'}</span></p>
                    <p><strong>Broadcasts:</strong> ${discovery.broadcast_count || 0}</p>
                    <p><strong>Último:</strong> ${discovery.last_broadcast_time || 'Nunca'} desde ${discovery.last_broadcast_from || 'N/A'}</p>`;
                if (servers.servers && servers.servers.length > 0) {
                    let t = '<table><tr><th>URL</th><th>IP</th><th>Puerto</th><th>Estado</th></tr>';
                    servers.servers.forEach(s => {
                        t += `<tr><td>${s.url}</td><td>${s.ip||'N/A'}</td><td>${s.port||'N/A'}</td><td><span class="status ${s.available?'ok':'error'}">${s.available?'OK':'No'}</span></td></tr>`;
                    });
                    document.getElementById('servers-info').innerHTML = t + '</table>';
                } else { document.getElementById('servers-info').innerHTML = '<p>Sin servidores</p>'; }
                document.getElementById('full-info').textContent = JSON.stringify(diagnostic, null, 2);
            } catch(e) { console.error(e); }
        }
        loadData(); setInterval(loadData, 5000);
    </script>
</body>
</html>"""
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

    return DiagnosticHandler
