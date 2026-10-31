"""
Proxy local por hostname (CONNECT + SNI transparente) con MITM opcional.

- Destinos ya allowlist/learned: túnel TCP (rápido).
- Destinos desconocidos: MITM TLS (ALPN http/1.1), lee Referer/Origin,
  permite y aprende si el origen es un sitio allowlist/learned.
"""

from __future__ import annotations

import select
import socket
import struct
import threading
from typing import Callable, Optional

LISTEN_CONNECT = ("127.0.0.1", 18080)
LISTEN_SNI = ("127.0.0.1", 18443)
SO_MARK = 36  # Linux
PROXY_MARK = 0xC1BE00D1

SOL_IP = 0
SO_ORIGINAL_DST = 80


def extract_sni(data: bytes) -> Optional[str]:
    """Extrae SNI de un TLS ClientHello (record + handshake)."""
    try:
        if len(data) < 5 or data[0] != 0x16:
            return None
        hs = 5
        if hs >= len(data) or data[hs] != 0x01:
            return None
        p = hs + 4
        if p + 2 + 32 >= len(data):
            return None
        p += 2 + 32
        if p >= len(data):
            return None
        sid_len = data[p]
        p += 1 + sid_len
        if p + 2 > len(data):
            return None
        cs_len = (data[p] << 8) | data[p + 1]
        p += 2 + cs_len
        if p >= len(data):
            return None
        comp_len = data[p]
        p += 1 + comp_len
        if p + 2 > len(data):
            return None
        ext_len = (data[p] << 8) | data[p + 1]
        p += 2
        end = min(len(data), p + ext_len)
        while p + 4 <= end:
            typ = (data[p] << 8) | data[p + 1]
            ln = (data[p + 2] << 8) | data[p + 3]
            p += 4
            if p + ln > end:
                break
            if typ == 0 and ln >= 5:
                q = p + 2
                if q >= p + ln:
                    break
                name_type = data[q]
                q += 1
                if name_type != 0 or q + 2 > p + ln:
                    break
                name_len = (data[q] << 8) | data[q + 1]
                q += 2
                if q + name_len > p + ln:
                    break
                return data[q : q + name_len].decode("ascii", errors="ignore").lower()
            p += ln
    except Exception:
        return None
    return None


def _splice(a: socket.socket, b: socket.socket, timeout: float = 300.0):
    a.setblocking(False)
    b.setblocking(False)
    sockets = [a, b]
    try:
        while True:
            r, _, x = select.select(sockets, [], sockets, timeout)
            if x or not r:
                break
            for src in r:
                dst = b if src is a else a
                try:
                    data = src.recv(65536)
                except Exception:
                    return
                if not data:
                    return
                try:
                    dst.sendall(data)
                except Exception:
                    return
    finally:
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


def _set_mark(sock: socket.socket):
    try:
        sock.setsockopt(socket.SOL_SOCKET, SO_MARK, PROXY_MARK)
    except Exception:
        try:
            sock.setsockopt(socket.SOL_IP, SO_MARK, PROXY_MARK)
        except Exception:
            pass


def _original_dst(conn: socket.socket) -> Optional[tuple[str, int]]:
    try:
        raw = conn.getsockopt(SOL_IP, SO_ORIGINAL_DST, 16)
        port = struct.unpack("!H", raw[2:4])[0]
        ip = socket.inet_ntoa(raw[4:8])
        return ip, port
    except Exception:
        return None


class HostnameProxy:
    """CONNECT (:18080) + transparent SNI (:18443), MITM para Referer."""

    def __init__(
        self,
        is_allowed: Callable[[str], bool],
        on_allowed: Optional[Callable[[str], None]] = None,
        on_denied: Optional[Callable[[str], None]] = None,
        authorize_referer: Optional[Callable[[str, Optional[str], Optional[str]], bool]] = None,
        sticky_authorize: Optional[Callable[[str], bool]] = None,
        mitm_enabled: bool = True,
    ):
        self._is_allowed = is_allowed
        self._on_allowed = on_allowed
        self._on_denied = on_denied
        self._authorize_referer = authorize_referer
        self._sticky_authorize = sticky_authorize
        self._mitm_enabled = mitm_enabled
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._socks: list[socket.socket] = []

    def start(self) -> bool:
        self.stop()
        self._stop.clear()
        connect_ok = False
        for label, addr, handler in (
            ("connect", LISTEN_CONNECT, self._serve_connect),
            ("sni", LISTEN_SNI, self._serve_sni),
        ):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(addr)
                sock.listen(128)
                sock.settimeout(1.0)
                self._socks.append(sock)
                t = threading.Thread(
                    target=handler, args=(sock,), name=f"cm-hostproxy-{label}", daemon=True
                )
                t.start()
                self._threads.append(t)
                print(f"[HostProxy] listening {addr[0]}:{addr[1]} ({label})")
                if label == "connect":
                    connect_ok = True
            except OSError as e:
                print(f"[HostProxy] bind {addr}: {e}")
                # CONNECT es obligatorio; SNI (redirect transparente) es best-effort.
                if label == "connect":
                    self.stop()
                    return False
        return connect_ok

    def stop(self):
        self._stop.set()
        for s in self._socks:
            try:
                s.close()
            except Exception:
                pass
        self._socks = []
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []

    def update_callbacks(
        self,
        is_allowed: Optional[Callable[[str], bool]] = None,
        on_allowed: Optional[Callable[[str], None]] = None,
        on_denied: Optional[Callable[[str], None]] = None,
        authorize_referer: Optional[Callable[[str, Optional[str], Optional[str]], bool]] = None,
        sticky_authorize: Optional[Callable[[str], bool]] = None,
        mitm_enabled: Optional[bool] = None,
    ):
        if is_allowed is not None:
            self._is_allowed = is_allowed
        if on_allowed is not None:
            self._on_allowed = on_allowed
        if on_denied is not None:
            self._on_denied = on_denied
        if authorize_referer is not None:
            self._authorize_referer = authorize_referer
        if sticky_authorize is not None:
            self._sticky_authorize = sticky_authorize
        if mitm_enabled is not None:
            self._mitm_enabled = mitm_enabled

    def _notify_allowed(self, name: str):
        if self._on_allowed:
            try:
                self._on_allowed(name)
            except Exception:
                pass

    def _notify_denied(self, name: str):
        print(f"[HostProxy] DENY {name}")
        if self._on_denied:
            try:
                self._on_denied(name)
            except Exception:
                pass

    def _pre_allowed(self, host: str) -> bool:
        name = (host or "").strip().lower().rstrip(".")
        if not name:
            return False
        try:
            return bool(self._is_allowed(name))
        except Exception as e:
            print(f"[HostProxy] is_allowed: {e}")
            return False

    def _dial(self, host: str, port: int) -> Optional[socket.socket]:
        try:
            remote = socket.create_connection((host, port), timeout=10)
            _set_mark(remote)
            return remote
        except Exception as e:
            print(f"[HostProxy] dial {host}:{port}: {e}")
            return None

    def _serve_connect(self, sock: socket.socket):
        while not self._stop.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except Exception:
                if self._stop.is_set():
                    break
                continue
            threading.Thread(
                target=self._handle_connect, args=(conn,), daemon=True
            ).start()

    def _handle_connect(self, conn: socket.socket):
        remote = None
        browser_tls = None
        origin_tls = None
        try:
            conn.settimeout(15)
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
            head = buf.split(b"\r\n\r\n", 1)[0].decode("latin-1", errors="ignore")
            line = head.split("\r\n", 1)[0]
            parts = line.split()
            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                return
            target = parts[1]
            if ":" in target:
                host, port_s = target.rsplit(":", 1)
                try:
                    port = int(port_s)
                except ValueError:
                    port = 443
            else:
                host, port = target, 443
            host = host.strip("[]").lower()

            if self._pre_allowed(host):
                remote = self._dial(host, port)
                if not remote:
                    conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                    return
                conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._notify_allowed(host)
                conn.settimeout(None)
                remote.settimeout(None)
                _splice(conn, remote)
                conn = None
                remote = None
                return

                        # Sin MITM: ventana sticky tras visitar un apex allowlist (CDNs de video).
            if (not self._mitm_enabled or self._authorize_referer is None) and self._sticky_authorize:
                try:
                    sticky_ok = bool(self._sticky_authorize(host))
                except Exception as e:
                    print(f"[HostProxy] sticky_authorize: {e}")
                    sticky_ok = False
                if sticky_ok:
                    remote = self._dial(host, port)
                    if not remote:
                        conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                        return
                    conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    self._notify_allowed(host)
                    conn.settimeout(None)
                    remote.settimeout(None)
                    _splice(conn, remote)
                    conn = None
                    remote = None
                    return

if not self._mitm_enabled or self._authorize_referer is None:
                self._notify_denied(host)
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return

            try:
                import mitm_tls
            except ImportError as e:
                print(f"[HostProxy] mitm_tls no disponible: {e}")
                self._notify_denied(host)
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return

            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            ctx_c = mitm_tls.client_facing_ssl_context(host)
            conn.settimeout(20)
            browser_tls = ctx_c.wrap_socket(conn, server_side=True)
            conn = None

            req = b""
            while b"\r\n\r\n" not in req and len(req) < 65536:
                chunk = browser_tls.recv(4096)
                if not chunk:
                    return
                req += chunk
            headers, _rest = mitm_tls.parse_http11_request_head(req)
            if not headers.get(":method_line"):
                self._notify_denied(host)
                try:
                    browser_tls.sendall(
                        b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    )
                except Exception:
                    pass
                return

            ref_h = mitm_tls.host_from_header_value(headers.get("referer"))
            ori_h = mitm_tls.host_from_header_value(headers.get("origin"))
            try:
                allowed = bool(self._authorize_referer(host, ref_h, ori_h))
            except Exception as e:
                print(f"[HostProxy] authorize_referer: {e}")
                allowed = False
            if not allowed:
                self._notify_denied(host)
                try:
                    browser_tls.sendall(
                        b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    )
                except Exception:
                    pass
                return

            self._notify_allowed(host)
            raw = self._dial(host, port)
            if not raw:
                try:
                    browser_tls.sendall(
                        b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    )
                except Exception:
                    pass
                return
            ctx_s = mitm_tls.server_facing_ssl_context()
            origin_tls = ctx_s.wrap_socket(raw, server_hostname=host)
            origin_tls.sendall(req)
            browser_tls.settimeout(None)
            origin_tls.settimeout(None)
            _splice(browser_tls, origin_tls)
            browser_tls = None
            origin_tls = None
        except Exception as e:
            print(f"[HostProxy] connect handler: {e}")
        finally:
            for s in (conn, remote, browser_tls, origin_tls):
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass

    def _serve_sni(self, sock: socket.socket):
        while not self._stop.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except Exception:
                if self._stop.is_set():
                    break
                continue
            threading.Thread(
                target=self._handle_sni, args=(conn,), daemon=True
            ).start()

    def _handle_sni(self, conn: socket.socket):
        """Transparent SNI: solo túnel si ya está allowlist (sin MITM en v1)."""
        remote = None
        try:
            conn.settimeout(15)
            buf = b""
            sni = None
            while len(buf) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
                sni = extract_sni(buf)
                if sni or (len(buf) >= 5 and buf[0] != 0x16):
                    break
                if len(buf) >= 5:
                    need = 5 + ((buf[3] << 8) | buf[4])
                    if len(buf) >= need:
                        sni = extract_sni(buf)
                        break

            orig = _original_dst(conn)
            dest_port = 443
            dest_ip = None
            if orig:
                dest_ip, dest_port = orig

            if not sni:
                print("[HostProxy] DENY (no SNI)")
                return
            if not self._pre_allowed(sni):
                self._notify_denied(sni)
                return

            remote = self._dial(sni, dest_port) or (
                self._dial(dest_ip, dest_port) if dest_ip else None
            )
            if not remote:
                return
            self._notify_allowed(sni)
            remote.sendall(buf)
            conn.settimeout(None)
            remote.settimeout(None)
            _splice(conn, remote)
            conn = None
            remote = None
        except Exception as e:
            print(f"[HostProxy] sni handler: {e}")
        finally:
            for s in (conn, remote):
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
