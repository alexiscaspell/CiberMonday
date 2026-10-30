"""
Política de red CiberMonday (Linux).
Allowlist + corte vía nftables (set dinámico) o iptables.
DNS learning: redirect :53 → forwarder local que agrega IPs al set.
"""

from __future__ import annotations

import ipaddress
import shutil
import socket
import subprocess
import threading
from datetime import datetime
from urllib.parse import urlparse

from domain_match import expand_allowed_names

TABLE_NAME = "cibermonday"
SET_NAME = "allow4"
DNS_REDIR_PORT = 5353
UPSTREAM_DNS = "1.1.1.1"

PRIVATE_NETWORKS = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
)

_last_fingerprint = None
_backend = None
_learner = None
_learned_ips: set[str] = set()
_learn_lock = threading.Lock()
_active_allowlist: list = []
_rule_counter = 0
_on_denied = None  # callback(qname) opcional


def _run(cmd, timeout=15):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def classify_entry(entry: str):
    raw = (entry or "").strip().lower()
    if not raw:
        return None
    if "/" in raw:
        try:
            net = ipaddress.ip_network(raw, strict=False)
            return ("cidr", str(net))
        except ValueError:
            return None
    try:
        ip = ipaddress.ip_address(raw)
        return ("ip", str(ip))
    except ValueError:
        pass
    host = raw[2:] if raw.startswith("*.") else raw
    if "." in host or host == "localhost":
        return ("domain", raw)
    return None


def resolve_domains(domains):
    """Resuelve A/AAAA→IPv4 en paralelo para sembrar el set antes del primer paint."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _one(d):
        host = d[2:] if d.startswith("*.") else d
        out = set()
        try:
            for info in socket.getaddrinfo(host, None, socket.AF_INET):
                addr = info[4][0]
                try:
                    if isinstance(ipaddress.ip_address(addr), ipaddress.IPv4Address):
                        out.add(addr)
                except ValueError:
                    pass
        except Exception:
            pass
        return out

    ips = set()
    names = [d for d in domains if d]
    if not names:
        return ips
    workers = min(16, max(4, len(names)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, d) for d in names]
        for fut in as_completed(futs):
            try:
                ips |= fut.result()
            except Exception:
                pass
    return ips


def host_from_server_url(server_url):
    if not server_url:
        return None
    try:
        parsed = urlparse(server_url if "://" in server_url else f"http://{server_url}")
        return parsed.hostname
    except Exception:
        return None


def compute_policy_mode(network_filter_enabled, allowlist, internet_session_info, device_session_active):
    if not device_session_active:
        return "unrestricted"

    inet_exists = internet_session_info is not None
    inet_remaining = 0
    if inet_exists:
        inet_remaining = max(0, int(internet_session_info.get("remaining_seconds", 0)))

    if inet_exists and inet_remaining == 0:
        return "always_allowed_only"

    if network_filter_enabled:
        return "allowlist"

    return "unrestricted"


def build_allowed_remotes(mode, allowlist, server_url):
    remotes = set(PRIVATE_NETWORKS)
    server_host = host_from_server_url(server_url)
    if server_host:
        try:
            ip = ipaddress.ip_address(server_host)
            if isinstance(ip, ipaddress.IPv4Address):
                remotes.add(str(ip))
        except ValueError:
            remotes |= resolve_domains([server_host])

    if mode == "allowlist":
        names = expand_allowed_names(allowlist)
        remotes |= resolve_domains(sorted(names))
        for entry in allowlist or []:
            kind = classify_entry(entry)
            if not kind:
                continue
            t, val = kind
            if t in ("ip", "cidr"):
                try:
                    if "/" in val:
                        net = ipaddress.ip_network(val, strict=False)
                        if isinstance(net, ipaddress.IPv4Network):
                            remotes.add(str(net))
                    else:
                        ip = ipaddress.ip_address(val)
                        if isinstance(ip, ipaddress.IPv4Address):
                            remotes.add(str(ip))
                except ValueError:
                    pass

    return sorted(remotes)


def _detect_backend():
    global _backend
    if _backend:
        return _backend
    if shutil.which("nft"):
        _backend = "nft"
    elif shutil.which("iptables"):
        _backend = "iptables"
    else:
        _backend = None
    return _backend


def _clear_nft():
    _run(["nft", "delete", "table", "inet", TABLE_NAME], timeout=10)


def nft_set_add(ips):
    """Agrega IPv4 al set allow4 (idempotente)."""
    global _learned_ips
    added = []
    with _learn_lock:
        for ip in ips:
            try:
                if not isinstance(ipaddress.ip_address(ip), ipaddress.IPv4Address):
                    continue
            except ValueError:
                continue
            if ip in _learned_ips:
                continue
            r = _run(
                ["nft", "add", "element", "inet", TABLE_NAME, SET_NAME, "{", f"{ip}", "}"],
                timeout=5,
            )
            if r.returncode == 0:
                _learned_ips.add(ip)
                added.append(ip)
            else:
                # set puede no existir aún
                err = (r.stderr or "").strip()
                if err and "No such file" not in err:
                    print(f"[NetPolicy] nft add {ip}: {err}")
    return added


def _apply_nft(remotes, enable_dns_redir: bool):
    global _learned_ips
    _clear_nft()
    _learned_ips = set()

    # Solo IPs/host /32 en el set; CIDRs privados van como reglas fijas
    set_elems = []
    for r in remotes:
        if "/" in r:
            try:
                net = ipaddress.ip_network(r, strict=False)
                if isinstance(net, ipaddress.IPv4Network) and net.prefixlen == 32:
                    set_elems.append(str(net.network_address))
            except ValueError:
                pass
        else:
            try:
                if isinstance(ipaddress.ip_address(r), ipaddress.IPv4Address):
                    set_elems.append(r)
            except ValueError:
                pass

    priv = ", ".join(PRIVATE_NETWORKS)
    elems = ", ".join(set_elems) if set_elems else ""
    set_body = f" elements = {{ {elems} }}" if elems else ""

    script = [
        f"table inet {TABLE_NAME} {{",
        f"  set {SET_NAME} {{",
        "    type ipv4_addr",
        "    flags interval",
        set_body,
        "  }",
        "  chain output {",
        "    type filter hook output priority 0; policy drop;",
        '    oifname "lo" accept',
        "    ct state established,related accept",
        f"    ip daddr {{ {priv} }} accept",
        # Upstream DNS del forwarder (evita bucle del redirect)
        f"    ip daddr {UPSTREAM_DNS} udp dport 53 accept",
        f"    ip daddr {UPSTREAM_DNS} tcp dport 53 accept",
        f"    ip daddr {UPSTREAM_DNS} tcp dport 853 accept",
        # Bloquear DoT genérico para forzar DNS clásico → learning
        "    tcp dport 853 drop",
        "    udp dport 853 drop",
        f"    ip daddr @{SET_NAME} accept",
        "  }",
    ]
    if enable_dns_redir:
        script += [
            "  chain dnsredir {",
            "    type nat hook output priority -100; policy accept;",
            # No redirigir queries al upstream del learner
            f"    ip daddr {UPSTREAM_DNS} udp dport 53 return",
            f"    ip daddr {UPSTREAM_DNS} tcp dport 53 return",
            f"    udp dport 53 dnat ip to 127.0.0.1:{DNS_REDIR_PORT}",
            f"    tcp dport 53 dnat ip to 127.0.0.1:{DNS_REDIR_PORT}",
            "  }",
        ]
    script += ["}"]
    conf = "\n".join(line for line in script if line is not None)
    r = subprocess.run(
        ["nft", "-f", "-"],
        input=conf,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0:
        print(f"[NetPolicy] nft error: {r.stderr}")
        return False
    with _learn_lock:
        _learned_ips = set(set_elems)
    return True


IPTABLES_COMMENT = "cibermonday-netpolicy"


def _clear_iptables():
    try:
        r = _run(["iptables", "-S", "OUTPUT"], timeout=10)
        for line in (r.stdout or "").splitlines():
            if IPTABLES_COMMENT in line:
                parts = line.split()
                if parts and parts[0] == "-A":
                    parts[0] = "-D"
                    _run(["iptables"] + parts, timeout=10)
    except Exception as e:
        print(f"[NetPolicy] iptables clear error: {e}")
    _run(["iptables", "-t", "nat", "-D", "OUTPUT", "-p", "udp", "--dport", "53",
          "-j", "DNAT", "--to-destination", f"127.0.0.1:{DNS_REDIR_PORT}"], timeout=5)
    _run(["iptables", "-t", "nat", "-D", "OUTPUT", "-p", "tcp", "--dport", "53",
          "-j", "DNAT", "--to-destination", f"127.0.0.1:{DNS_REDIR_PORT}"], timeout=5)
    _run(["iptables", "-D", "OUTPUT", "-j", "CIBERMONDAY"], timeout=5)
    _run(["iptables", "-F", "CIBERMONDAY"], timeout=5)
    _run(["iptables", "-X", "CIBERMONDAY"], timeout=5)


def _apply_iptables(remotes, enable_dns_redir: bool):
    _clear_iptables()
    _run(["iptables", "-N", "CIBERMONDAY"], timeout=5)
    _run(["iptables", "-F", "CIBERMONDAY"], timeout=5)
    for args in (
        ["-A", "CIBERMONDAY", "-o", "lo", "-j", "ACCEPT"],
        ["-A", "CIBERMONDAY", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
        ["-A", "CIBERMONDAY", "-d", UPSTREAM_DNS, "-p", "udp", "--dport", "53", "-j", "ACCEPT"],
        ["-A", "CIBERMONDAY", "-d", UPSTREAM_DNS, "-p", "tcp", "--dport", "53", "-j", "ACCEPT"],
        ["-A", "CIBERMONDAY", "-p", "tcp", "--dport", "853", "-j", "DROP"],
        ["-A", "CIBERMONDAY", "-p", "udp", "--dport", "853", "-j", "DROP"],
    ):
        _run(["iptables"] + args + ["-m", "comment", "--comment", IPTABLES_COMMENT], timeout=5)
    for remote in remotes:
        _run(
            ["iptables", "-A", "CIBERMONDAY", "-d", remote, "-j", "ACCEPT",
             "-m", "comment", "--comment", IPTABLES_COMMENT],
            timeout=5,
        )
    _run(
        ["iptables", "-A", "CIBERMONDAY", "-j", "DROP", "-m", "comment", "--comment", IPTABLES_COMMENT],
        timeout=5,
    )
    _run(
        ["iptables", "-I", "OUTPUT", "1", "-j", "CIBERMONDAY", "-m", "comment", "--comment", IPTABLES_COMMENT],
        timeout=5,
    )
    if enable_dns_redir:
        _run(
            ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "udp", "--dport", "53",
             "!", "-d", UPSTREAM_DNS, "-j", "DNAT", "--to-destination", f"127.0.0.1:{DNS_REDIR_PORT}"],
            timeout=5,
        )
        _run(
            ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "53",
             "!", "-d", UPSTREAM_DNS, "-j", "DNAT", "--to-destination", f"127.0.0.1:{DNS_REDIR_PORT}"],
            timeout=5,
        )
    return True


def _on_learned_ips(ips):
    backend = _detect_backend()
    if backend == "nft":
        nft_set_add(ips)
    elif backend == "iptables":
        global _rule_counter
        for ip in ips:
            with _learn_lock:
                if ip in _learned_ips:
                    continue
                _learned_ips.add(ip)
                _rule_counter += 1
            _run(
                ["iptables", "-I", "CIBERMONDAY", "3", "-d", ip, "-j", "ACCEPT",
                 "-m", "comment", "--comment", IPTABLES_COMMENT],
                timeout=5,
            )


def _stop_learner():
    global _learner
    if _learner:
        try:
            _learner.stop()
        except Exception:
            pass
        _learner = None


def set_denied_callback(cb):
    """Registra callback para dominios DNS no allowlist (pedidos de acceso)."""
    global _on_denied, _learner
    _on_denied = cb
    if _learner is not None:
        _learner._on_denied = cb


def _start_learner(allowlist):
    global _learner, _active_allowlist
    _active_allowlist = list(allowlist or [])
    _stop_learner()
    try:
        from dns_learner import DnsLearner
    except ImportError as e:
        print(f"[NetPolicy] dns_learner no disponible: {e}")
        return
    learner = DnsLearner(
        on_ips=_on_learned_ips,
        listen_port=DNS_REDIR_PORT,
        on_denied=_on_denied,
    )
    if learner.start(_active_allowlist):
        _learner = learner


def apply_network_policy(mode, allowlist, server_url, on_denied=None):
    global _last_fingerprint, _on_denied
    if on_denied is not None:
        _on_denied = on_denied
    if mode == "unrestricted":
        return clear_network_policy()

    remotes = build_allowed_remotes(mode, allowlist, server_url)
    enable_dns = mode == "allowlist"
    # Incluir allowlist: al achicar la lista hay que rearmar el set (IPs aprendidas viejas).
    al_key = "|".join(sorted(str(x).strip().lower() for x in (allowlist or []) if str(x).strip()))
    fingerprint = f"{mode}|dns:{enable_dns}|al:{al_key}|{'|'.join(remotes)}"
    if fingerprint == _last_fingerprint:
        if _learner and enable_dns:
            _learner.update_allowlist(allowlist or [])
            if _on_denied is not None:
                _learner._on_denied = _on_denied
        return True

    backend = _detect_backend()
    if not backend:
        print("[NetPolicy] No hay nft ni iptables disponibles")
        return False

    print(f"[NetPolicy] Aplicando modo={mode} backend={backend} seed={len(remotes)} dns_learn={enable_dns}")
    if backend == "nft":
        ok = _apply_nft(remotes, enable_dns)
    else:
        ok = _apply_iptables(remotes, enable_dns)

    if ok:
        _last_fingerprint = fingerprint
        if enable_dns:
            _start_learner(allowlist)
        else:
            _stop_learner()
        _flush_conntrack()
    return ok


def _flush_conntrack():
    """Cierra flujos TCP viejos que quedarían abiertos por established/related."""
    if shutil.which("conntrack"):
        try:
            _run(["conntrack", "-F"], timeout=5)
        except Exception:
            pass


def clear_network_policy(force: bool = False):
    global _last_fingerprint, _learned_ips
    if not force and _last_fingerprint == "unrestricted":
        return True
    print("[NetPolicy] Limpiando política (unrestricted)")
    _stop_learner()
    backend = _detect_backend()
    if backend == "nft":
        _clear_nft()
    elif backend == "iptables":
        _clear_iptables()
    _learned_ips = set()
    _last_fingerprint = "unrestricted"
    return True


def internet_session_info_from_data(data):
    if not data:
        return None
    try:
        end = datetime.fromisoformat(data["end_time"])
        remaining = max(0, int((end - datetime.now()).total_seconds()))
        return {
            "time_limit_seconds": data.get("time_limit_seconds", data.get("time_limit", 0)),
            "start_time": data.get("start_time"),
            "end_time": data["end_time"],
            "remaining_seconds": remaining,
            "is_expired": remaining == 0,
        }
    except Exception:
        return None
