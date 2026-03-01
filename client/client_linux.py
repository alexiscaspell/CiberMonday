"""
CiberMonday Client - Implementación Linux.
Usa archivos JSON para almacenamiento y loginctl/notify-send para operaciones de escritorio.
Compatible con X11 y Wayland via systemd-logind.
"""

import json
import os
import subprocess
import threading
from datetime import datetime, timedelta

from client_base import CiberMondayClient


class LinuxClient(CiberMondayClient):

    CONFIG_DIR_ROOT = '/etc/cibermonday'
    CONFIG_DIR_USER = os.path.expanduser('~/.config/cibermonday')

    def __init__(self):
        self._config_dir = self.CONFIG_DIR_ROOT if os.geteuid() == 0 else self.CONFIG_DIR_USER
        os.makedirs(self._config_dir, exist_ok=True)
        super().__init__()

    # ==================== JSON file helpers ====================

    def _json_path(self, name):
        return os.path.join(self._config_dir, name)

    def _read_json(self, name):
        path = self._json_path(name)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r') as f:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
                return data
        except (json.JSONDecodeError, IOError):
            return None

    def _write_json(self, name, data):
        path = self._json_path(name)
        try:
            with open(path, 'w') as f:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX)
                json.dump(data, f, indent=2)
                fcntl.flock(f, fcntl.LOCK_UN)
            return True
        except IOError as e:
            print(f"[Storage] Error al escribir {name}: {e}")
            return False

    # ==================== Platform operations ====================

    def lock_workstation(self):
        sessions = self._get_graphical_sessions()
        for sid in sessions:
            try:
                r = subprocess.run(['loginctl', 'lock-session', sid],
                                   capture_output=True, timeout=5)
                if r.returncode == 0:
                    print(f"[Lock] Sesión {sid} bloqueada (loginctl lock-session)", flush=True)
                    return True
            except Exception as e:
                print(f"[Lock] Error en loginctl lock-session {sid}: {e}", flush=True)

        try:
            r = subprocess.run(['xdg-screensaver', 'lock'], capture_output=True, timeout=5)
            if r.returncode == 0:
                print("[Lock] Pantalla bloqueada (xdg-screensaver)", flush=True)
                return True
        except Exception:
            pass

        for sid in sessions:
            try:
                r = subprocess.run(['loginctl', 'terminate-session', sid],
                                   capture_output=True, timeout=5)
                if r.returncode == 0:
                    print(f"[Lock] Sesión {sid} terminada (loginctl terminate-session)", flush=True)
                    return True
            except Exception:
                pass

        print("[Lock] ERROR: No se pudo bloquear", flush=True)
        return False

    def is_user_session_active(self):
        sessions = self._get_graphical_sessions()
        for sid in sessions:
            try:
                r = subprocess.run(
                    ['loginctl', 'show-session', sid, '-p', 'State'],
                    capture_output=True, text=True, timeout=5
                )
                for line in r.stdout.strip().split('\n'):
                    if line.startswith('State=') and line.split('=', 1)[1] == 'active':
                        return True
            except Exception:
                continue
        return False

    def _get_graphical_sessions(self):
        """Obtiene IDs de sesiones gráficas (x11/wayland/tty)."""
        sessions = []
        try:
            r = subprocess.run(
                ['loginctl', 'list-sessions', '--no-legend'],
                capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.strip().split('\n'):
                parts = line.split()
                if not parts:
                    continue
                sid = parts[0]
                try:
                    show = subprocess.run(
                        ['loginctl', 'show-session', sid, '-p', 'Type'],
                        capture_output=True, text=True, timeout=5
                    )
                    for prop in show.stdout.strip().split('\n'):
                        if prop.startswith('Type='):
                            stype = prop.split('=', 1)[1]
                            if stype in ('x11', 'wayland', 'tty'):
                                sessions.append(sid)
                except Exception:
                    sessions.append(sid)
        except Exception as e:
            print(f"[Session] Error al listar sesiones: {e}")
        return sessions

    def _get_active_user_env(self):
        """Detecta el usuario logueado y su entorno para enviar notificaciones."""
        try:
            r = subprocess.run(
                ['loginctl', 'list-sessions', '--no-legend'],
                capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) < 3:
                    continue
                sid = parts[0]
                user = parts[2] if len(parts) >= 3 else None

                try:
                    show = subprocess.run(
                        ['loginctl', 'show-session', sid,
                         '-p', 'Type', '-p', 'Display', '-p', 'State'],
                        capture_output=True, text=True, timeout=5
                    )
                    props = {}
                    for prop_line in show.stdout.strip().split('\n'):
                        if '=' in prop_line:
                            k, v = prop_line.split('=', 1)
                            props[k] = v

                    if props.get('Type') in ('x11', 'wayland') and props.get('State') == 'active':
                        display = props.get('Display', ':0')
                        uid = None
                        try:
                            import pwd
                            uid = pwd.getpwnam(user).pw_uid
                        except Exception:
                            pass
                        bus = f"unix:path=/run/user/{uid}/bus" if uid else ""
                        return user, display, bus
                except Exception:
                    continue
        except Exception:
            pass
        return None, ':0', ''

    def show_alert(self, title, message, is_warning=False):
        def _show():
            user, display, bus = self._get_active_user_env()
            urgency = 'critical' if is_warning else 'normal'

            if user:
                env = dict(os.environ)
                env['DISPLAY'] = display
                if bus:
                    env['DBUS_SESSION_BUS_ADDRESS'] = bus

                try:
                    subprocess.run(
                        ['sudo', '-u', user, 'notify-send', '-u', urgency, title, message],
                        env=env, capture_output=True, timeout=5
                    )
                    return
                except Exception:
                    pass

            try:
                subprocess.run(
                    ['notify-send', '-u', urgency, title, message],
                    capture_output=True, timeout=5
                )
            except Exception:
                print(f"[Alert] No se pudo mostrar notificación: {title}: {message}")

        threading.Thread(target=_show, daemon=True).start()

    def is_admin(self):
        return os.geteuid() == 0

    def apply_protections(self):
        return []

    def setup_firewall(self):
        print("\n[Firewall] Verificando configuración del firewall...")

        ufw_available = False
        try:
            r = subprocess.run(['ufw', 'status'], capture_output=True, text=True, timeout=5)
            ufw_available = r.returncode == 0
        except Exception:
            pass

        if ufw_available and self.is_admin():
            try:
                subprocess.run(['ufw', 'allow', '5001/udp'],
                               capture_output=True, timeout=5)
                subprocess.run(['ufw', 'allow', '5002/tcp'],
                               capture_output=True, timeout=5)
                print("[Firewall] [OK] Reglas ufw configuradas (UDP 5001, TCP 5002)\n")
            except Exception as e:
                print(f"[Firewall] [WARN] Error al configurar ufw: {e}\n")
        elif ufw_available:
            print("[Firewall] [WARN] Se requiere root para configurar ufw")
            print("[Firewall] Ejecuta: sudo ufw allow 5001/udp && sudo ufw allow 5002/tcp\n")
        else:
            print("[Firewall] [INFO] ufw no disponible. Verifica manualmente que los puertos 5001/udp y 5002/tcp estén abiertos.\n")

    # ==================== Storage (JSON files) ====================

    def save_session(self, time_limit_seconds, start_time_iso, end_time_iso):
        data = {
            'time_limit_seconds': time_limit_seconds,
            'start_time': start_time_iso,
            'end_time': end_time_iso
        }
        return self._write_json('session.json', data)

    def get_session(self):
        return self._read_json('session.json')

    def clear_session(self):
        path = self._json_path('session.json')
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def get_remaining_seconds(self):
        data = self.get_session()
        if not data:
            return 0
        try:
            end_time = datetime.fromisoformat(data['end_time'])
            remaining = int((end_time - datetime.now()).total_seconds())
            return max(0, remaining)
        except Exception:
            return 0

    def is_session_expired(self):
        return self.get_remaining_seconds() <= 0 and self.get_session() is not None

    def get_session_info(self):
        data = self.get_session()
        if not data:
            return None
        try:
            end_time = datetime.fromisoformat(data['end_time'])
            start_time = datetime.fromisoformat(data['start_time'])
            remaining = int((end_time - datetime.now()).total_seconds())
            remaining = max(0, remaining)
            time_limit = data.get('time_limit_seconds', 0)

            return {
                'time_limit_seconds': time_limit,
                'start_time': data['start_time'],
                'end_time': data['end_time'],
                'remaining_seconds': remaining,
                'is_expired': remaining <= 0,
                'elapsed_seconds': int((datetime.now() - start_time).total_seconds()),
                'total_seconds': time_limit
            }
        except Exception:
            return None

    def save_client_id(self, client_id):
        self._write_json('client_id.json', {'client_id': client_id})

    def load_client_id(self):
        data = self._read_json('client_id.json')
        if data:
            return data.get('client_id')
        return None

    def save_config(self, config):
        self._write_json('config.json', config)

    def load_config(self):
        return self._read_json('config.json')

    def save_servers(self, servers_list):
        self._write_json('servers.json', servers_list)

    def load_servers(self):
        data = self._read_json('servers.json')
        if isinstance(data, list):
            return data
        return []

    def increment_server_timeouts(self, server_urls):
        servers = self.load_servers()
        max_timeouts = 10
        try:
            cfg = self.load_config()
            if cfg and 'max_server_timeouts' in cfg:
                max_timeouts = int(cfg['max_server_timeouts'])
        except Exception:
            pass

        changed = False
        to_remove = []
        for s in servers:
            url = s.get('url')
            if url in server_urls:
                s['timeout_count'] = s.get('timeout_count', 0) + 1
                changed = True
                if s['timeout_count'] >= max_timeouts:
                    to_remove.append(url)
                    print(f"[Servers] Servidor {url} eliminado ({max_timeouts} timeouts)")

        if to_remove:
            servers = [s for s in servers if s.get('url') not in to_remove]
            changed = True

        if changed:
            self.save_servers(servers)

    def reset_server_timeout_count(self, server_url):
        servers = self.load_servers()
        for s in servers:
            if s.get('url') == server_url:
                if s.get('timeout_count', 0) != 0:
                    s['timeout_count'] = 0
                    self.save_servers(servers)
                return
