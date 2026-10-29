"""
Política de red CiberMonday (Linux).
Allowlist + corte de internet vía nftables (preferido) o iptables.
"""

from __future__ import annotations

import ipaddress
import shutil
import socket
import subprocess
from datetime import datetime
from urllib.parse import urlparse

TABLE_NAME = "cibermonday"
PRIVATE_NETWORKS = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
)

# Familias CDN (alineado con Android / Windows)
DOMAIN_FAMILIES = {
    "youtube.com": (
        "youtube.com", "youtu.be", "youtube-nocookie.com",
        "googlevideo.com", "ytimg.com", "yt3.ggpht.com", "ggpht.com",
        "googleusercontent.com", "googleapis.com", "gstatic.com", "google.com",
    ),
    "netflix.com": ("netflix.com", "nflxvideo.net", "nflxso.net", "nflximg.net", "fast.com"),
    "twitch.tv": ("twitch.tv", "ttvnw.net", "jtvnw.net", "twitchcdn.net"),
    "discord.com": ("discord.com", "discordapp.com", "discord.gg", "discord.media", "discordapp.net"),
    "instagram.com": ("instagram.com", "cdninstagram.com", "facebook.com", "fbcdn.net", "facebook.net"),
    "facebook.com": ("facebook.com", "fbcdn.net", "facebook.net", "instagram.com", "cdninstagram.com"),
    "tiktok.com": ("tiktok.com", "tiktokv.com", "tiktokcdn.com", "musical.ly", "byteoversea.com"),
}

_last_fingerprint = None
_backend = None  # 'nft' | 'iptables' | None


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
    ips = set()
    for d in domains:
        host = d[2:] if d.startswith("*.") else d
        try:
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                addr = info[4][0]
                try:
                    # Solo IPv4 para iptables/nft set simple
                    if isinstance(ipaddress.ip_address(addr), ipaddress.IPv4Address):
                        ips.add(addr)
                except ValueError:
                    pass
        except Exception:
            continue
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
        domains = []
        for entry in allowlist or []:
            kind = classify_entry(entry)
            if not kind:
                continue
            t, val = kind
            if t in ("ip", "cidr"):
                try:
                    # Filtrar IPv6 para backend simple
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
            elif t == "domain":
                host = val[2:] if val.startswith("*.") else val
                domains.extend([host, f"www.{host}", f"m.{host}"])
                for fam_apex, family in DOMAIN_FAMILIES.items():
                    if host == fam_apex or host.endswith("." + fam_apex) or fam_apex in host or host in family:
                        domains.extend(family)
                        break
                if "youtube" in host or host in ("youtu.be",) or "googlevideo" in host:
                    domains.extend(DOMAIN_FAMILIES["youtube.com"])
        remotes |= resolve_domains(domains)

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


def _apply_nft(remotes):
    _clear_nft()
    # Crear tabla + chain output policy drop + accepts
    script = [
        f"table inet {TABLE_NAME} {{",
        "  chain output {",
        "    type filter hook output priority 0; policy drop;",
        "    oifname \"lo\" accept",
        "    ct state established,related accept",
    ]
    if remotes:
        joined = ", ".join(remotes)
        script.append(f"    ip daddr {{ {joined} }} accept")
    script += [
        "  }",
        "}",
    ]
    conf = "\n".join(script)
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
    return True


IPTABLES_COMMENT = "cibermonday-netpolicy"


def _clear_iptables():
    # Eliminar reglas con nuestro comentario
    try:
        r = _run(["iptables", "-S", "OUTPUT"], timeout=10)
        for line in (r.stdout or "").splitlines():
            if IPTABLES_COMMENT in line:
                # Convert -A to -D
                parts = line.split()
                if parts and parts[0] == "-A":
                    parts[0] = "-D"
                    _run(["iptables"] + parts, timeout=10)
    except Exception as e:
        print(f"[NetPolicy] iptables clear error: {e}")
    # Quitar jump a chain propia si existe
    _run(["iptables", "-D", "OUTPUT", "-j", "CIBERMONDAY"], timeout=5)
    _run(["iptables", "-F", "CIBERMONDAY"], timeout=5)
    _run(["iptables", "-X", "CIBERMONDAY"], timeout=5)


def _apply_iptables(remotes):
    _clear_iptables()
    _run(["iptables", "-N", "CIBERMONDAY"], timeout=5)
    _run(["iptables", "-F", "CIBERMONDAY"], timeout=5)
    _run(
        [
            "iptables",
            "-A",
            "CIBERMONDAY",
            "-o",
            "lo",
            "-j",
            "ACCEPT",
            "-m",
            "comment",
            "--comment",
            IPTABLES_COMMENT,
        ],
        timeout=5,
    )
    _run(
        [
            "iptables",
            "-A",
            "CIBERMONDAY",
            "-m",
            "conntrack",
            "--ctstate",
            "ESTABLISHED,RELATED",
            "-j",
            "ACCEPT",
            "-m",
            "comment",
            "--comment",
            IPTABLES_COMMENT,
        ],
        timeout=5,
    )
    for remote in remotes:
        _run(
            [
                "iptables",
                "-A",
                "CIBERMONDAY",
                "-d",
                remote,
                "-j",
                "ACCEPT",
                "-m",
                "comment",
                "--comment",
                IPTABLES_COMMENT,
            ],
            timeout=5,
        )
    _run(
        [
            "iptables",
            "-A",
            "CIBERMONDAY",
            "-j",
            "DROP",
            "-m",
            "comment",
            "--comment",
            IPTABLES_COMMENT,
        ],
        timeout=5,
    )
    _run(
        [
            "iptables",
            "-I",
            "OUTPUT",
            "1",
            "-j",
            "CIBERMONDAY",
            "-m",
            "comment",
            "--comment",
            IPTABLES_COMMENT,
        ],
        timeout=5,
    )
    return True


def apply_network_policy(mode, allowlist, server_url):
    global _last_fingerprint
    if mode == "unrestricted":
        return clear_network_policy()

    remotes = build_allowed_remotes(mode, allowlist, server_url)
    fingerprint = f"{mode}|{'|'.join(remotes)}"
    if fingerprint == _last_fingerprint:
        return True

    backend = _detect_backend()
    if not backend:
        print("[NetPolicy] No hay nft ni iptables disponibles")
        return False

    print(f"[NetPolicy] Aplicando modo={mode} backend={backend} destinos={len(remotes)}")
    ok = _apply_nft(remotes) if backend == "nft" else _apply_iptables(remotes)
    if ok:
        _last_fingerprint = fingerprint
    return ok


def clear_network_policy():
    global _last_fingerprint
    if _last_fingerprint == "unrestricted":
        return True
    print("[NetPolicy] Limpiando política (unrestricted)")
    backend = _detect_backend()
    if backend == "nft":
        _clear_nft()
    elif backend == "iptables":
        _clear_iptables()
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
