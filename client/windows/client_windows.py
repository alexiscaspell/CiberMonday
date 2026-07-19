"""
CiberMonday Client - Implementación Windows.
Usa el registro de Windows para almacenamiento y APIs WTS/user32 para bloqueo.
"""

import ctypes
import threading
import sys
import os

from client_base import CiberMondayClient


class WindowsClient(CiberMondayClient):

    def __init__(self):
        # Inicializar Windows APIs antes de super().__init__() porque
        # _load_alert_thresholds() en el constructor base llama a load_config()
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._WTS_CURRENT_SERVER_HANDLE = 0

        self._registry_available = False
        self._init_registry()

        super().__init__()

    def _init_registry(self):
        try:
            from registry_manager import get_config_from_registry
            self._registry_available = True
        except ImportError:
            self._registry_available = False

    # ==================== Platform operations ====================

    def lock_workstation(self):
        try:
            result = self._user32.LockWorkStation()
            if result:
                print("[Lock] PC bloqueada (LockWorkStation)", flush=True)
                return True
            else:
                print("[Lock] LockWorkStation() falló, intentando WTSDisconnectSession...", flush=True)
        except Exception as e:
            print(f"[Lock] Error en LockWorkStation: {e}", flush=True)

        try:
            wtsapi32 = ctypes.windll.wtsapi32
            session_id = self._kernel32.WTSGetActiveConsoleSessionId()
            if session_id != 0xFFFFFFFF:
                result = wtsapi32.WTSDisconnectSession(
                    self._WTS_CURRENT_SERVER_HANDLE, session_id, False
                )
                if result:
                    print(f"[Lock] Sesión {session_id} desconectada (WTSDisconnectSession)", flush=True)
                    return True
                else:
                    error_code = self._kernel32.GetLastError()
                    print(f"[Lock] WTSDisconnectSession falló (error: {error_code})", flush=True)
            else:
                print("[Lock] No se encontró sesión activa", flush=True)
        except Exception as e:
            print(f"[Lock] Error en WTSDisconnectSession: {e}", flush=True)

        print("[Lock] ERROR: No se pudo bloquear la PC", flush=True)
        return False

    def is_user_session_active(self):
        try:
            wtsapi32 = ctypes.windll.wtsapi32
            session_id = self._kernel32.WTSGetActiveConsoleSessionId()
            if session_id == 0xFFFFFFFF:
                return False

            WTSConnectState = 8
            buffer = ctypes.c_void_p()
            bytes_returned = ctypes.c_ulong()

            result = wtsapi32.WTSQuerySessionInformationW(
                self._WTS_CURRENT_SERVER_HANDLE, session_id,
                WTSConnectState, ctypes.byref(buffer), ctypes.byref(bytes_returned)
            )

            if result and buffer.value is not None:
                state = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int)).contents.value
                wtsapi32.WTSFreeMemory(buffer)
                return state == 0  # WTSActive
            return True
        except Exception:
            return True

    def show_alert(self, title, message, is_warning=False):
        try:
            icon = 0x30 if is_warning else 0x40
            flags = 0x0 | 0x40000 | 0x10000 | icon

            def _show():
                self._user32.MessageBoxW(0, message, title, flags)

            threading.Thread(target=_show, daemon=True).start()
        except Exception as e:
            print(f"Error al mostrar alerta: {e}")

    def is_admin(self):
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def apply_protections(self):
        try:
            from protection import apply_protections
            return apply_protections() or []
        except ImportError:
            return []
        except Exception:
            return []

    def setup_firewall(self):
        try:
            from firewall_manager import check_firewall_rule, add_firewall_rule, is_admin

            print("\n[Firewall] Verificando configuración del firewall...")

            if not check_firewall_rule():
                print("[Firewall] [WARN] La regla del firewall no está configurada")
                if is_admin():
                    print("[Firewall] Intentando agregar regla automáticamente...")
                    if add_firewall_rule():
                        print("[Firewall] [OK] Regla agregada\n")
                    else:
                        print("[Firewall] [ERROR] No se pudo agregar la regla")
                        print("[Firewall] Ejecuta como administrador: python firewall_manager.py add\n")
                else:
                    print("[Firewall] [WARN] Se requieren privilegios de administrador")
                    print("[Firewall] Ejecuta como administrador: python firewall_manager.py add\n")
            else:
                print("[Firewall] [OK] Regla configurada correctamente\n")
        except ImportError:
            print("[Firewall] [WARN] Módulo firewall_manager no disponible\n")
        except Exception as e:
            print(f"[Firewall] [WARN] Error: {e}\n")

    # ==================== Storage (delegates to registry_manager.py) ====================

    def save_session(self, time_limit_seconds, start_time_iso, end_time_iso):
        if not self._registry_available:
            return False
        from registry_manager import save_session_to_registry
        return save_session_to_registry(time_limit_seconds, start_time_iso, end_time_iso)

    def get_session(self):
        if not self._registry_available:
            return None
        from registry_manager import get_session_from_registry
        return get_session_from_registry()

    def clear_session(self):
        if not self._registry_available:
            return
        from registry_manager import clear_session_from_registry
        clear_session_from_registry()

    def get_remaining_seconds(self):
        if not self._registry_available:
            return 0
        from registry_manager import get_remaining_seconds
        return get_remaining_seconds()

    def is_session_expired(self):
        if not self._registry_available:
            return False
        from registry_manager import is_session_expired
        return is_session_expired()

    def get_session_info(self):
        if not self._registry_available:
            return None
        from registry_manager import get_session_info
        return get_session_info()

    def save_client_id(self, client_id):
        if not self._registry_available:
            return
        from registry_manager import save_client_id_to_registry
        save_client_id_to_registry(client_id)

    def load_client_id(self):
        if not self._registry_available:
            return None
        from registry_manager import get_client_id_from_registry
        return get_client_id_from_registry()

    def save_config(self, config):
        if not self._registry_available:
            return
        from registry_manager import save_config_to_registry
        save_config_to_registry(config)

    def load_config(self):
        if not self._registry_available:
            return None
        from registry_manager import get_config_from_registry
        return get_config_from_registry()

    def save_servers(self, servers_list):
        if not self._registry_available:
            return
        from registry_manager import save_servers_to_registry
        save_servers_to_registry(servers_list)

    def load_servers(self):
        if not self._registry_available:
            return []
        from registry_manager import get_servers_from_registry
        return get_servers_from_registry()

    def increment_server_timeouts(self, server_urls):
        if not self._registry_available:
            return
        from registry_manager import increment_server_timeouts
        increment_server_timeouts(server_urls)

    def reset_server_timeout_count(self, server_url):
        if not self._registry_available:
            return
        from registry_manager import reset_server_timeout_count
        reset_server_timeout_count(server_url)
