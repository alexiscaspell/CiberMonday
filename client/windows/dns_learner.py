"""
DNS forwarder local: aprende IPs allowlist + hosts relacionados del tráfico.

Si un nombre denegado aparece poco después de un resolve de un sitio de la
allowlist explícita, se agrega el apex a allowlist_learned (implícito) y se
abren sus IPs — sin pedido de acceso. Los denegados sin ese contexto sí
disparan on_denied (pedir acceso).
"""

from __future__ import annotations

import select
import socket
import struct
import threading
import time
from typing import Callable, Iterable, Optional

from domain_match import (
    COMPANION_WINDOW_SEC,
    dns_apex,
    name_is_allowed,
    name_matches_explicit,
)

UPSTREAM = ("1.1.1.1", 53)
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 53
FALLBACK_PORT = 5353


def _parse_qname(data: bytes, offset: int) -> tuple[str, int]:
    labels = []
    jumped = False
    end = offset
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset += 1
            if not jumped:
                end = offset
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                break
            ptr = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                end = offset + 2
            offset = ptr
            jumped = True
            continue
        offset += 1
        try:
            labels.append(data[offset : offset + length].decode("idna"))
        except Exception:
            labels.append(data[offset : offset + length].decode("ascii", errors="ignore"))
        offset += length
    name = ".".join(labels).lower()
    return name, end


def _question_end(packet: bytes) -> tuple[str, int, int]:
    if len(packet) < 12:
        return "", 0, 0
    qdcount = struct.unpack("!H", packet[4:6])[0]
    offset = 12
    qname = ""
    qtype = 0
    for _ in range(qdcount):
        qname, offset = _parse_qname(packet, offset)
        if offset + 4 > len(packet):
            return qname, 0, offset
        qtype, _qclass = struct.unpack("!HH", packet[offset : offset + 4])
        offset += 4
    return qname, qtype, offset


def _nodata_response(query: bytes) -> bytes:
    if len(query) < 12:
        return query
    _qname, _qtype, qend = _question_end(query)
    if qend < 12:
        return query
    qdcount = struct.unpack("!H", query[4:6])[0]
    header = struct.pack(
        "!HHHHHH",
        struct.unpack("!H", query[0:2])[0],
        0x8180,
        qdcount,
        0,
        0,
        0,
    )
    return header + query[12:qend]


def _extract_a_records(packet: bytes) -> tuple[str, list[str]]:
    if len(packet) < 12:
        return "", []
    flags = struct.unpack("!H", packet[2:4])[0]
    if not (flags & 0x8000):
        return "", []
    qdcount = struct.unpack("!H", packet[4:6])[0]
    ancount = struct.unpack("!H", packet[6:8])[0]
    nscount = struct.unpack("!H", packet[8:10])[0]
    arcount = struct.unpack("!H", packet[10:12])[0]
    offset = 12
    qname = ""
    for _ in range(qdcount):
        qname, offset = _parse_qname(packet, offset)
        offset += 4
    ips: list[str] = []
    for _ in range(ancount + nscount + arcount):
        if offset >= len(packet):
            break
        _, offset = _parse_qname(packet, offset)
        if offset + 10 > len(packet):
            break
        rtype, _rclass, _ttl, rdlen = struct.unpack("!HHIH", packet[offset : offset + 10])
        offset += 10
        rdata = packet[offset : offset + rdlen]
        offset += rdlen
        if rtype == 1 and rdlen == 4:
            ips.append(socket.inet_ntoa(rdata))
    return qname, ips


class DnsLearner:
    def __init__(
        self,
        on_ips: Callable[[Iterable[str]], None],
        listen_port: int = LISTEN_PORT,
        upstream: tuple[str, int] = UPSTREAM,
        on_denied: Optional[Callable[[str], None]] = None,
        on_learned: Optional[Callable[[str], None]] = None,
    ):
        self._on_ips = on_ips
        self._on_denied = on_denied
        self._on_learned = on_learned
        self._listen_port = listen_port
        self._upstream = upstream
        self._allowlist: list = []
        self._learned: list = []
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_explicit_allow_at = 0.0
        self._lock = threading.Lock()
        self.listen_port_used = listen_port

    def start(self, allowlist, learned=None) -> bool:
        self.stop()
        self._allowlist = list(allowlist or [])
        self._learned = list(learned or [])
        self._stop.clear()
        self.listen_port_used = self._listen_port
        for port in (self._listen_port, FALLBACK_PORT):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((LISTEN_HOST, port))
            except OSError as e:
                print(f"[DnsLearner] bind {LISTEN_HOST}:{port} falló: {e}")
                sock.close()
                continue
            sock.setblocking(False)
            self._sock = sock
            self.listen_port_used = port
            self._thread = threading.Thread(target=self._loop, name="cm-dns-learn", daemon=True)
            self._thread.start()
            print(f"[DnsLearner] Escuchando {LISTEN_HOST}:{port} → {self._upstream}")
            return True
        return False

    def stop(self):
        self._stop.set()
        sock = self._sock
        self._sock = None
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        t = self._thread
        self._thread = None
        if t and t.is_alive():
            t.join(timeout=2)

    def update_allowlist(self, allowlist, learned=None):
        self._allowlist = list(allowlist or [])
        if learned is not None:
            self._learned = list(learned or [])

    def _companion_active(self) -> bool:
        return (time.time() - self._last_explicit_allow_at) <= COMPANION_WINDOW_SEC

    def _loop(self):
        while not self._stop.is_set() and self._sock:
            try:
                r, _, _ = select.select([self._sock], [], [], 0.5)
                if not r:
                    continue
                data, addr = self._sock.recvfrom(4096)
                if not data:
                    continue
                self._handle(data, addr)
            except Exception as e:
                if not self._stop.is_set():
                    print(f"[DnsLearner] loop: {e}")

    def _handle(self, data: bytes, addr):
        qname, qtype, _ = _question_end(data)
        if qtype == 28:  # AAAA — firewall solo IPv4
            try:
                if self._sock:
                    self._sock.sendto(_nodata_response(data), addr)
            except Exception:
                pass
            return
        try:
            up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            up.settimeout(3)
            up.sendto(data, self._upstream)
            resp, _ = up.recvfrom(4096)
            up.close()
        except Exception as e:
            print(f"[DnsLearner] upstream: {e}")
            return

        resp_qname, ips = _extract_a_records(resp)
        name = resp_qname or qname
        if not name:
            try:
                if self._sock:
                    self._sock.sendto(resp, addr)
            except Exception:
                pass
            return

        explicit = name_matches_explicit(name, self._allowlist)
        allowed = explicit or name_is_allowed(name, self._allowlist, self._learned)

        if not allowed and self._companion_active():
            apex = dns_apex(name)
            if apex and apex not in ("localhost",):
                with self._lock:
                    if apex not in self._learned:
                        self._learned.append(apex)
                        learned_new = True
                    else:
                        learned_new = False
                allowed = True
                if learned_new:
                    print(f"[DnsLearner] related {apex} (from {name})")
                    if self._on_learned:
                        try:
                            self._on_learned(apex)
                        except Exception as e:
                            print(f"[DnsLearner] on_learned: {e}")

        if explicit:
            self._last_explicit_allow_at = time.time()

        if allowed and ips:
            try:
                self._on_ips(ips)
                print(f"[DnsLearner] allow {name} → {', '.join(ips)}")
            except Exception as e:
                print(f"[DnsLearner] on_ips: {e}")
        elif not allowed and self._on_denied:
            try:
                self._on_denied(name)
            except Exception as e:
                print(f"[DnsLearner] on_denied: {e}")

        try:
            if self._sock:
                self._sock.sendto(resp, addr)
        except Exception:
            return
