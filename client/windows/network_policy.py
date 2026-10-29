"""
Política de red CiberMonday (Windows).
Allowlist + corte de internet vía firewall outbound (default block + allows).
"""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys
from datetime import datetime
from urllib.parse import urlparse

RULE_PREFIX = "CiberMonday NetPolicy"
PRIVATE_NETWORKS = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)

# Familias CDN (mismo criterio que Android AllowlistDomains)
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

# Estado previo del perfil outbound para restaurar
_saved_outbound_policy = None
_last_fingerprint = None


def _run(cmd, timeout=15):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags
    )


def classify_entry(entry: str):
    """Retorna ('cidr'|'ip'|'domain', valor_normalizado) o None."""
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
    # dominio / wildcard
    host = raw[2:] if raw.startswith("*.") else raw
    if "." in host or host == "localhost":
        return ("domain", raw)
    return None


def resolve_domains(domains, timeout=2.0):
    """Resuelve dominios (sin wildcard expand) a IPs."""
    ips = set()
    for d in domains:
        host = d[2:] if d.startswith("*.") else d
        try:
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                addr = info[4][0]
                try:
                    ipaddress.ip_address(addr)
                    ips.add(addr)
                except ValueError:
                    pass
        except Exception:
            continue
    return ips


def host_from_server_url(server_url: str | None):
    if not server_url:
        return None
    try:
        parsed = urlparse(server_url if "://" in server_url else f"http://{server_url}")
        return parsed.hostname
    except Exception:
        return None


def compute_policy_mode(network_filter_enabled, allowlist, internet_session_info, device_session_active):
    """
    Retorna ('unrestricted' | 'allowlist' | 'always_allowed_only').
    """
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

    if inet_exists and inet_remaining > 0:
        # Timer activo pero sin filtro: internet completo hasta que expire
        return "unrestricted"

    return "unrestricted"


def _expand_allowlist_domains(allowlist):
    """Expande entradas a apex + CDNs conocidos + www/m."""
    out = []
    seen = set()
    for entry in allowlist or []:
        kind = classify_entry(entry)
        if not kind:
            continue
        t, val = kind
        if t in ("ip", "cidr"):
            if val not in seen:
                seen.add(val)
                out.append(("ip_or_cidr", val))
            continue
        host = val[2:] if val.startswith("*.") else val
        candidates = {host, f"www.{host}", f"m.{host}"}
        apex = host
        for fam_apex, family in DOMAIN_FAMILIES.items():
            if apex == fam_apex or apex.endswith("." + fam_apex) or fam_apex in apex or apex in family:
                candidates.update(family)
                break
        if "youtube" in apex or apex in ("youtu.be",) or "googlevideo" in apex:
            candidates.update(DOMAIN_FAMILIES["youtube.com"])
        for d in sorted(candidates):
            if d not in seen:
                seen.add(d)
                out.append(("domain", d))
    return out


def build_allowed_remotes(mode, allowlist, server_url):
    """Lista de remoteip (IPs/CIDRs) a permitir en outbound."""
    remotes = set(PRIVATE_NETWORKS)

    server_host = host_from_server_url(server_url)
    if server_host:
        try:
            ipaddress.ip_address(server_host)
            remotes.add(server_host)
        except ValueError:
            remotes |= resolve_domains([server_host])

    if mode == "allowlist":
        domains = []
        for kind, val in _expand_allowlist_domains(allowlist):
            if kind == "ip_or_cidr":
                remotes.add(val)
            else:
                domains.append(val)
        remotes |= resolve_domains(domains)

    return sorted(remotes)


def _delete_our_rules():
    # Eliminar por prefijo: netsh no soporta wildcard; listar y borrar
    try:
        r = _run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=all"],
            timeout=30,
        )
        names = set()
        current = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("Rule Name:") or line.startswith("Nombre de regla:"):
                current = line.split(":", 1)[1].strip()
            if current and current.startswith(RULE_PREFIX):
                names.add(current)
                current = None
        for name in names:
            _run(
                ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                timeout=10,
            )
    except Exception as e:
        print(f"[NetPolicy] Error limpiando reglas: {e}")


def _set_outbound_block(enabled: bool):
    global _saved_outbound_policy
    profiles = ("domainprofile", "privateprofile", "publicprofile")
    if enabled:
        if _saved_outbound_policy is None:
            _saved_outbound_policy = {}
            for p in profiles:
                try:
                    r = _run(["netsh", "advfirewall", "show", p], timeout=10)
                    policy = "allow"
                    for line in (r.stdout or "").splitlines():
                        low = line.lower()
                        if "outbound" in low or "saliente" in low:
                            if "block" in low or "bloquear" in low:
                                policy = "block"
                            elif "allow" in low or "permitir" in low:
                                policy = "allow"
                    _saved_outbound_policy[p] = policy
                except Exception:
                    _saved_outbound_policy[p] = "allow"
        for p in profiles:
            _run(
                [
                    "netsh",
                    "advfirewall",
                    "set",
                    p,
                    "firewallpolicy",
                    "blockinbound,blockoutbound",
                ],
                timeout=10,
            )
    else:
        saved = _saved_outbound_policy or {}
        for p in profiles:
            out = saved.get(p, "allow")
            inbound = "blockinbound"
            outbound = "blockoutbound" if out == "block" else "allowoutbound"
            _run(
                ["netsh", "advfirewall", "set", p, "firewallpolicy", f"{inbound},{outbound}"],
                timeout=10,
            )
        _saved_outbound_policy = None


def _add_allow_rule(name_suffix: str, remoteip: str) -> bool:
    name = f"{RULE_PREFIX} {name_suffix}"
    r = _run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={name}",
            "dir=out",
            "action=allow",
            "enable=yes",
            "profile=any",
            f"remoteip={remoteip}",
            "description=CiberMonday network allowlist",
        ],
        timeout=10,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        print(f"[NetPolicy] netsh add rule falló ({remoteip}): {err}")
        return False
    return True


def apply_network_policy(mode, allowlist, server_url):
    """Aplica o limpia la política según mode."""
    global _last_fingerprint
    if mode == "unrestricted":
        return clear_network_policy()

    remotes = build_allowed_remotes(mode, allowlist, server_url)
    fingerprint = f"{mode}|{'|'.join(remotes)}"
    if fingerprint == _last_fingerprint:
        return True

    print(f"[NetPolicy] Aplicando modo={mode} destinos={len(remotes)}")
    _delete_our_rules()
    _set_outbound_block(True)

    ok_count = 0
    for i, remote in enumerate(remotes):
        if _add_allow_rule(f"allow-{i}", remote):
            ok_count += 1

    if ok_count == 0 and remotes:
        print("[NetPolicy] Ninguna regla allow se aplicó (¿sin admin / netsh?)")
        return False

    _last_fingerprint = fingerprint
    return True


def clear_network_policy(force: bool = False):
    global _last_fingerprint
    if not force and _last_fingerprint == "unrestricted":
        return True
    print("[NetPolicy] Limpiando política (unrestricted)")
    _delete_our_rules()
    _set_outbound_block(False)
    _last_fingerprint = "unrestricted"
    return True


def internet_session_info_from_data(data):
    """Construye info de sesión de internet desde dict persistido."""
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
