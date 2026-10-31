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
import time
from datetime import datetime
from urllib.parse import urlparse

from domain_match import expand_allowed_names, merge_allowlists

TABLE_NAME = "cibermonday"
SET_NAME = "allow4"
DNS_REDIR_PORT = 5353
UPSTREAM_DNS = "1.1.1.1"
SNI_PROXY_PORT = 18443
PROXY_MARK = 0xC1BE00D1

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
_on_learned = None  # callback(apex) — related host del tráfico
_active_learned: list = []
_host_proxy = None


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


def build_allowed_remotes(mode, allowlist, server_url, learned=None):
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
        effective = merge_allowlists(allowlist, learned)
        names = expand_allowed_names(effective)
        remotes |= resolve_domains(sorted(names))
        for entry in effective:
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
        # Salidas del hostname proxy (SNI/CONNECT) — name-gate ya aplicado
        f"    meta mark {PROXY_MARK:#x} accept",
        f"    ip daddr {{ {priv} }} accept",
        # Upstream DNS del forwarder (evita bucle del redirect)
        f"    ip daddr {UPSTREAM_DNS} udp dport 53 accept",
        f"    ip daddr {UPSTREAM_DNS} tcp dport 53 accept",
        f"    ip daddr {UPSTREAM_DNS} tcp dport 853 accept",
        # Bloquear DoT / QUIC para forzar DNS clásico + TLS con SNI
        "    tcp dport 853 drop",
        "    udp dport 853 drop",
        "    udp dport 443 drop",
        f"    ip daddr @{SET_NAME} accept",
        "  }",
    ]
    if enable_dns_redir:
        script += [
            "  chain dnsredir {",
            "    type nat hook output priority -100; policy accept;",
            f"    meta mark {PROXY_MARK:#x} return",
            # No redirigir queries al upstream del learner
            f"    ip daddr {UPSTREAM_DNS} udp dport 53 return",
            f"    ip daddr {UPSTREAM_DNS} tcp dport 53 return",
            f"    udp dport 53 dnat ip to 127.0.0.1:{DNS_REDIR_PORT}",
            f"    tcp dport 53 dnat ip to 127.0.0.1:{DNS_REDIR_PORT}",
            # HTTPS → SNI proxy (name-gate; IPs compartidas no abren otros hosts)
            f"    tcp dport 443 redirect to :{SNI_PROXY_PORT}",
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
    _run(["iptables", "-t", "nat", "-D", "OUTPUT", "-p", "tcp", "--dport", "443",
          "-j", "REDIRECT", "--to-ports", str(SNI_PROXY_PORT)], timeout=5)
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
        ["-A", "CIBERMONDAY", "-m", "mark", "--mark", str(PROXY_MARK), "-j", "ACCEPT"],
        ["-A", "CIBERMONDAY", "-d", UPSTREAM_DNS, "-p", "udp", "--dport", "53", "-j", "ACCEPT"],
        ["-A", "CIBERMONDAY", "-d", UPSTREAM_DNS, "-p", "tcp", "--dport", "53", "-j", "ACCEPT"],
        ["-A", "CIBERMONDAY", "-p", "tcp", "--dport", "853", "-j", "DROP"],
        ["-A", "CIBERMONDAY", "-p", "udp", "--dport", "853", "-j", "DROP"],
        ["-A", "CIBERMONDAY", "-p", "udp", "--dport", "443", "-j", "DROP"],
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
        _run(
            ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "443",
             "-m", "mark", "!", "--mark", str(PROXY_MARK),
             "-j", "REDIRECT", "--to-ports", str(SNI_PROXY_PORT)],
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


_mitm_ca_dir = None
_mitm_ready = False
_mitm_error = None


def configure_mitm(ca_dir=None):
    global _mitm_ca_dir
    _mitm_ca_dir = ca_dir


def _ensure_mitm_ca() -> bool:
    global _mitm_ready, _mitm_error
    if _mitm_ready:
        return True
    try:
        import mitm_tls
        import os
        try:
            from cryptography import x509 as _x509  # noqa: F401
        except ImportError as ie:
            _mitm_error = f"cryptography import: {ie}"
            print(f"[NetPolicy] MITM CA: {_mitm_error}")
            return False
        mitm_tls.set_ca_dir(_mitm_ca_dir or os.path.join(os.path.expanduser("~"), ".cibermonday"))
        mitm_tls.ensure_ca()
        if not mitm_tls.install_ca_trust():
            _mitm_error = "install_ca_trust failed"
            print(f"[NetPolicy] MITM CA: {_mitm_error}")
            return False
        _mitm_ready = True
        _mitm_error = None
        return True
    except Exception as e:
        _mitm_error = str(e)
        print(f"[NetPolicy] MITM CA: {e}")
        return False


def _enable_mitm_on_proxy_if_ready():
    if _host_proxy is None:
        return
    if getattr(_host_proxy, "_mitm_enabled", False):
        return
    if not _ensure_mitm_ca():
        return
    _host_proxy.update_callbacks(
        authorize_referer=_proxy_authorize_referer,
        mitm_enabled=True,
    )
    print("[NetPolicy] HostnameProxy MITM hot-enabled")


def _proxy_host_allowed(name: str) -> bool:
    from domain_match import name_is_allowed
    return name_is_allowed(name, _active_allowlist, _active_learned)


_sticky_until = 0.0
_STICKY_SECONDS = 90.0
_STICKY_BLOCK_APEX = frozenset({"google.com"})


def _proxy_note_allowed_host(name: str) -> None:
    global _sticky_until
    from domain_match import name_is_allowed
    if name_is_allowed(name, _active_allowlist, learned=None):
        _sticky_until = time.time() + _STICKY_SECONDS


def _proxy_sticky_authorize(dest: str) -> bool:
    global _sticky_until, _active_learned
    if time.time() > _sticky_until:
        return False
    from domain_match import dns_apex, learn_host_target, name_is_allowed
    if name_is_allowed(dest, _active_allowlist, _active_learned):
        return True
    if dns_apex(dest) in _STICKY_BLOCK_APEX:
        return False
    target = learn_host_target(dest)
    if not target:
        return False
    if target not in _active_learned:
        _active_learned.append(target)
        cb = _on_learned
        if cb:
            threading.Thread(
                target=lambda t=target: _safe_on_learned(cb, t),
                name="cm-sticky-learned",
                daemon=True,
            ).start()
    _sticky_until = time.time() + _STICKY_SECONDS
    return True


def _proxy_authorize_referer(dest: str, referer_host, origin_host) -> bool:
    from domain_match import learn_host_target, name_is_allowed

    if name_is_allowed(dest, _active_allowlist, _active_learned):
        return True
    for src in (referer_host, origin_host):
        if not src:
            continue
        if name_is_allowed(src, _active_allowlist, _active_learned):
            target = learn_host_target(dest)
            if target and target not in _active_learned:
                _active_learned.append(target)
                cb = _on_learned
                if cb:
                    threading.Thread(
                        target=lambda t=target: _safe_on_learned(cb, t),
                        name="cm-proxy-learned",
                        daemon=True,
                    ).start()
            return True
    return False


def _safe_on_learned(cb, target: str):
    try:
        cb(target)
    except Exception:
        pass


def _stop_host_proxy():
    global _host_proxy
    if _host_proxy:
        try:
            _host_proxy.stop()
        except Exception:
            pass
        _host_proxy = None


def _start_host_proxy():
    global _host_proxy
    _stop_host_proxy()
    try:
        from hostname_proxy import HostnameProxy
    except ImportError as e:
        print(f"[NetPolicy] hostname_proxy no disponible: {e}")
        return
    try:
        mitm_ok = _ensure_mitm_ca()
        proxy = HostnameProxy(
            is_allowed=_proxy_host_allowed,
            on_allowed=_proxy_note_allowed_host,
            on_denied=_on_denied,
            authorize_referer=_proxy_authorize_referer if mitm_ok else None,
            sticky_authorize=_proxy_sticky_authorize,
            mitm_enabled=mitm_ok,
        )
        if proxy.start():
            _host_proxy = proxy
            print(
                f"[NetPolicy] HostnameProxy MITM={'on' if mitm_ok else 'off'}"
                f"{'' if mitm_ok else f' err={_mitm_error}'}"
            )
        else:
            print("[NetPolicy] HostnameProxy no arrancó (CONNECT)")
    except Exception as e:
        print(f"[NetPolicy] HostnameProxy error: {e}")
        _host_proxy = None


def set_denied_callback(cb):
    """Registra callback para dominios DNS no allowlist (pedidos de acceso)."""
    global _on_denied, _learner
    _on_denied = cb
    if _learner is not None:
        _learner._on_denied = cb
    if _host_proxy is not None:
        _host_proxy.update_callbacks(on_denied=cb)


def set_learned_callback(cb):
    """Callback cuando el tráfico descubre un host related (allowlist_learned)."""
    global _on_learned, _learner
    _on_learned = cb
    if _learner is not None:
        _learner._on_learned = cb


def _start_learner(allowlist, learned=None):
    global _learner, _active_allowlist, _active_learned
    _active_allowlist = list(allowlist or [])
    _active_learned = list(learned or [])
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
        on_learned=_on_learned,
        passthrough=True,
    )
    if learner.start(_active_allowlist, _active_learned, passthrough=True):
        _learner = learner


def apply_network_policy(mode, allowlist, server_url, on_denied=None, learned=None, on_learned=None):
    global _last_fingerprint, _on_denied, _on_learned, _active_learned, _active_allowlist
    if on_denied is not None:
        _on_denied = on_denied
    if on_learned is not None:
        _on_learned = on_learned
    if learned is not None:
        incoming = list(learned or [])
        _active_learned = list(dict.fromkeys(incoming + list(_active_learned or [])))
    _active_allowlist = list(allowlist or [])
    if mode == "unrestricted":
        return clear_network_policy()

    remotes = build_allowed_remotes(mode, allowlist, server_url, learned=_active_learned)
    enable_dns = mode == "allowlist"
    al_key = "|".join(sorted(str(x).strip().lower() for x in (allowlist or []) if str(x).strip()))
    fingerprint = f"{mode}|dns:{enable_dns}|al:{al_key}|sni-mitm|{'|'.join(remotes)}"
    if fingerprint == _last_fingerprint:
        # Si el proxy murió, no hacer early-return: rearmar.
        if enable_dns and _host_proxy is None:
            print("[NetPolicy] HostnameProxy ausente; reaplicando política")
        else:
            if _learner and enable_dns:
                _learner.update_allowlist(allowlist or [], _active_learned)
                if _on_denied is not None:
                    _learner._on_denied = _on_denied
                if _on_learned is not None:
                    _learner._on_learned = _on_learned
            if _host_proxy and enable_dns:
                _host_proxy.update_callbacks(
                    is_allowed=_proxy_host_allowed,
                    on_denied=_on_denied,
                    authorize_referer=_proxy_authorize_referer,
                )
                _enable_mitm_on_proxy_if_ready()
            return True

    backend = _detect_backend()
    if not backend:
        print("[NetPolicy] No hay nft ni iptables disponibles")
        return False

    print(
        f"[NetPolicy] Aplicando modo={mode} backend={backend} "
        f"seed={len(remotes)} learned={len(_active_learned or [])} "
        f"dns_passthrough={enable_dns} host_proxy={enable_dns}"
    )
    if backend == "nft":
        ok = _apply_nft(remotes, enable_dns)
    else:
        ok = _apply_iptables(remotes, enable_dns)

    if ok:
        _last_fingerprint = fingerprint
        if enable_dns:
            _start_learner(allowlist, _active_learned)
            _start_host_proxy()
            if _host_proxy is None:
                print("[NetPolicy] HostnameProxy no arrancó (CONNECT)")
        else:
            _stop_learner()
            _stop_host_proxy()
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
    _stop_host_proxy()
    backend = _detect_backend()
    if backend == "nft":
        _clear_nft()
    elif backend == "iptables":
        _clear_iptables()
    _learned_ips = set()
    _last_fingerprint = "unrestricted"
    return True


def clear_mitm_trust():
    global _mitm_ready
    try:
        import mitm_tls
        mitm_tls.uninstall_ca_trust()
    except Exception as e:
        print(f"[NetPolicy] clear MITM trust: {e}")
    _mitm_ready = False


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
