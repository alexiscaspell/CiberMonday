"""
DNS forwarder local: aprende IPs de nombres allowlist y notifica al callback.
Upstream fijo (1.1.1.1) para evitar bucles con redirect nft dport 53.
"""

from __future__ import annotations

import select
import socket
import struct
import threading
from typing import Callable, Iterable, Optional

from domain_match import name_is_allowed

UPSTREAM = ("1.1.1.1", 53)
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 5353


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
        labels.append(data[offset : offset + length].decode("idna", errors="ignore"))
        offset += length
    name = ".".join(labels).lower()
    return name, end


def _extract_a_records(packet: bytes) -> tuple[str, list[str]]:
    if len(packet) < 12:
        return "", []
    flags = struct.unpack("!H", packet[2:4])[0]
    if not (flags & 0x8000):
        return "", []
    qdcount = struct.unpack("!H", packet[4:6])[0]
    ancount = struct.unpack("!H", packet[6:8])[0]
    offset = 12
    qname = ""
    for _ in range(qdcount):
        qname, offset = _parse_qname(packet, offset)
        offset += 4
    ips: list[str] = []
    for _ in range(ancount):
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
    ):
        self._on_ips = on_ips
        self._on_denied = on_denied
        self._listen_port = listen_port
        self._upstream = upstream
        self._allowlist: list = []
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self, allowlist) -> bool:
        self.stop()
        self._allowlist = list(allowlist or [])
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((LISTEN_HOST, self._listen_port))
        except OSError as e:
            print(f"[DnsLearner] No se pudo bind {LISTEN_HOST}:{self._listen_port}: {e}")
            sock.close()
            return False
        sock.setblocking(False)
        self._sock = sock
        self._thread = threading.Thread(target=self._loop, name="cm-dns-learn", daemon=True)
        self._thread.start()
        print(f"[DnsLearner] Escuchando {LISTEN_HOST}:{self._listen_port} → {self._upstream}")
        return True

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

    def update_allowlist(self, allowlist):
        self._allowlist = list(allowlist or [])

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
        try:
            up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            up.settimeout(3)
            up.sendto(data, self._upstream)
            resp, _ = up.recvfrom(4096)
            up.close()
        except Exception as e:
            print(f"[DnsLearner] upstream: {e}")
            return
        try:
            if self._sock:
                self._sock.sendto(resp, addr)
        except Exception:
            return
        qname, ips = _extract_a_records(resp)
        if not ips:
            return
        if name_is_allowed(qname, self._allowlist):
            try:
                self._on_ips(ips)
                print(f"[DnsLearner] allow {qname} → {', '.join(ips)}")
            except Exception as e:
                print(f"[DnsLearner] on_ips: {e}")
        elif self._on_denied and qname:
            try:
                self._on_denied(qname)
            except Exception as e:
                print(f"[DnsLearner] on_denied: {e}")
