"""
DNS forwarder local: aprende IPs allowlist + refinamientos bajo apexes conocidos.

Hosts related nuevos (CDN de otro apex) vienen del scan HTML (allowlist_discover)
o del live-learn en DNS/CONNECT — no de una ventana temporal.
"""

from __future__ import annotations

import select
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Optional

from domain_match import (
    live_learn_target,
    name_is_allowed,
)

UPSTREAM = ("1.1.1.1", 53)
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 53
LISTEN_PORT_FALLBACK = 5353
_CACHE_TTL = 30.0
_POOL_WORKERS = 32


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


def _nxdomain_response(query: bytes) -> bytes:
    """NXDOMAIN: no filtrar IPs reales de hosts denegados (IP sharing Google)."""
    if len(query) < 12:
        return query
    _qname, _qtype, qend = _question_end(query)
    if qend < 12:
        return query
    qdcount = struct.unpack("!H", query[4:6])[0]
    header = struct.pack(
        "!HHHHHH",
        struct.unpack("!H", query[0:2])[0],
        0x8183,  # QR|RD|RA + RCODE=3 NXDOMAIN
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


def _with_txid(resp: bytes, query: bytes) -> bytes:
    if len(resp) < 2 or len(query) < 2:
        return resp
    out = bytearray(resp)
    out[0:2] = query[0:2]
    return bytes(out)


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
        self.listen_port_used = listen_port
        self._allowlist: list = []
        self._learned: list = []
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._pool: Optional[ThreadPoolExecutor] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._cache_lock = threading.Lock()

    def start(self, allowlist, learned=None) -> bool:
        self.stop()
        self._allowlist = list(allowlist or [])
        self._learned = list(learned or [])
        self._stop.clear()
        with self._cache_lock:
            self._cache.clear()
        ports = [self._listen_port]
        if self._listen_port != LISTEN_PORT_FALLBACK:
            ports.append(LISTEN_PORT_FALLBACK)
        sock = None
        bound = None
        last_err = None
        for port in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((LISTEN_HOST, port))
                sock = s
                bound = port
                break
            except OSError as e:
                last_err = e
                try:
                    s.close()
                except Exception:
                    pass
        if sock is None or bound is None:
            print(f"[DnsLearner] No se pudo bind {LISTEN_HOST}:{ports}: {last_err}")
            return False
        self._listen_port = bound
        self.listen_port_used = bound
        sock.setblocking(False)
        self._sock = sock
        self._pool = ThreadPoolExecutor(max_workers=_POOL_WORKERS, thread_name_prefix="cm-dns")
        self._thread = threading.Thread(target=self._loop, name="cm-dns-learn", daemon=True)
        self._thread.start()
        print(f"[DnsLearner] Escuchando {LISTEN_HOST}:{bound} → {self._upstream} (parallel)")
        return True

    def stop(self):
        self._stop.set()
        pool = self._pool
        self._pool = None
        if pool:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                pool.shutdown(wait=False)
            except Exception:
                pass
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
        with self._cache_lock:
            self._cache.clear()

    def update_allowlist(self, allowlist, learned=None):
        with self._lock:
            self._allowlist = list(allowlist or [])
            if learned is not None:
                self._learned = list(learned or [])
        # Allowlist cambió: no servir respuestas cacheadas de otro modo
        with self._cache_lock:
            self._cache.clear()

    def _send(self, payload: bytes, addr) -> None:
        try:
            sock = self._sock
            if sock:
                sock.sendto(payload, addr)
        except Exception:
            pass

    def _emit_learned(self, target: str) -> None:
        cb = self._on_learned
        if not cb:
            return

        def _run():
            try:
                cb(target)
            except Exception as e:
                print(f"[DnsLearner] on_learned: {e}")

        threading.Thread(target=_run, name="cm-dns-learned", daemon=True).start()

    def _loop(self):
        while not self._stop.is_set() and self._sock:
            try:
                r, _, _ = select.select([self._sock], [], [], 0.5)
                if not r:
                    continue
                data, addr = self._sock.recvfrom(4096)
                if not data:
                    continue
                pool = self._pool
                if pool is not None:
                    pool.submit(self._handle, data, addr)
                else:
                    self._handle(data, addr)
            except Exception as e:
                if not self._stop.is_set():
                    print(f"[DnsLearner] loop: {e}")

    def _handle(self, data: bytes, addr):
        qname, qtype, _ = _question_end(data)
        if qtype == 28:  # AAAA — firewall/proxy solo IPv4
            self._send(_nodata_response(data), addr)
            return

        name = (qname or "").strip().lower().rstrip(".")
        with self._lock:
            allowlist = list(self._allowlist)
            learned = list(self._learned)

        allowed = bool(name) and name_is_allowed(name, allowlist, learned)
        target = live_learn_target(name, allowlist, learned) if name else None
        if target:
            with self._lock:
                if target not in self._learned:
                    self._learned.append(target)
                    learned_new = True
                else:
                    learned_new = False
            allowed = True
            if learned_new:
                print(f"[DnsLearner] related {target} (from {name})")
                self._emit_learned(target)

        if not allowed:
            if name and self._on_denied:
                try:
                    self._on_denied(name)
                except Exception as e:
                    print(f"[DnsLearner] on_denied: {e}")
            # Sin round-trip al upstream: no saturar la cola con denegados
            self._send(_nxdomain_response(data), addr)
            return

        now = time.time()
        with self._cache_lock:
            ent = self._cache.get(name)
            if ent and ent[0] > now:
                self._send(_with_txid(ent[1], data), addr)
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

        _resp_qname, ips = _extract_a_records(resp)
        if ips:
            try:
                self._on_ips(ips)
                print(f"[DnsLearner] allow {name} → {', '.join(ips)}")
            except Exception as e:
                print(f"[DnsLearner] on_ips: {e}")

        with self._cache_lock:
            self._cache[name] = (now + _CACHE_TTL, resp)
            if len(self._cache) > 500:
                self._cache = {k: v for k, v in self._cache.items() if v[0] > now}

        self._send(resp, addr)
