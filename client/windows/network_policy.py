"""
Política de red CiberMonday (Windows).
Allowlist + corte outbound; DNS learning; hostname CONNECT proxy (name-gate).
"""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys
import threading
from datetime import datetime
from urllib.parse import urlparse

from domain_match import expand_allowed_names, merge_allowlists

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

_saved_outbound_policy = None
_saved_dns = None  # list of (iface_name, dns_list)
_last_fingerprint = None
_learner = None
_learned_ips: set[str] = set()
_learn_lock = threading.Lock()
_rule_seq = 0
_on_denied = None  # callback(qname) opcional
_on_learned = None  # callback(apex)
_active_learned: list = []
_active_allowlist: list = []
_host_proxy = None
_saved_win_proxy = None  # snapshot for restore


def _run(cmd, timeout=15):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags
    )


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


def resolve_domains(domains, timeout=2.0):
    """Resuelve A en paralelo para sembrar reglas antes del primer paint."""
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
            ipaddress.ip_address(server_host)
            remotes.add(server_host)
        except ValueError:
            remotes |= resolve_domains([server_host])

    if mode == "allowlist":
        # No sembrar IPs de dominios: HTTPS pasa por hostname proxy (CONNECT).
        # Sembrar IPs compartidas (youtube ≡ google edge) abriría Search.
        effective = merge_allowlists(allowlist, learned)
        for entry in effective:
            kind = classify_entry(entry)
            if kind and kind[0] in ("ip", "cidr"):
                remotes.add(kind[1])
    elif mode == "always_allowed":
        pass
    return sorted(remotes)


def _delete_our_rules():
    try:
        r = _run(["netsh", "advfirewall", "firewall", "show", "rule", "name=all"], timeout=30)
        names = set()
        current = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("Rule Name:") or line.startswith("Nombre de regla:"):
                current = line.split(":", 1)[1].strip()
            if current and current.startswith(RULE_PREFIX):
                names.add(current)
                current = None
        for name in names:
            _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"], timeout=10)
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
                ["netsh", "advfirewall", "set", p, "firewallpolicy", "blockinbound,blockoutbound"],
                timeout=10,
            )
    else:
        if _saved_outbound_policy is None:
            for p in profiles:
                _run(
                    ["netsh", "advfirewall", "set", p, "firewallpolicy", "blockinbound,allowoutbound"],
                    timeout=10,
                )
            return
        for p, outbound in _saved_outbound_policy.items():
            inbound = "block"
            _run(
                ["netsh", "advfirewall", "set", p, "firewallpolicy", f"{inbound},{outbound}"],
                timeout=10,
            )
        _saved_outbound_policy = None


def _add_allow_rule(name_suffix: str, remoteip: str) -> bool:
    name = f"{RULE_PREFIX} {name_suffix}"
    r = _run(
        [
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={name}", "dir=out", "action=allow", "enable=yes", "profile=any",
            f"remoteip={remoteip}", "description=CiberMonday network allowlist",
        ],
        timeout=10,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        print(f"[NetPolicy] netsh add rule falló ({remoteip}): {err}")
        return False
    return True


def learn_ips(ips):
    """DNS learner: con hostname proxy no abrimos IPs (name-gate)."""
    if _host_proxy is not None:
        return
    global _rule_seq
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        key = str(addr)
        with _learn_lock:
            if key in _learned_ips:
                continue
            _learned_ips.add(key)
            _rule_seq += 1
            seq = _rule_seq
        _add_allow_rule(f"learn-{seq}", key)


def _list_ipv4_interfaces():
    """Nombres de interfaces con IPv4 (netsh)."""
    r = _run(["netsh", "interface", "ipv4", "show", "interfaces"], timeout=15)
    names = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("idx") or set(line) <= set("- "):
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit():
            name = " ".join(parts[4:])
            if name and name.lower() not in ("loopback*", "loopback"):
                names.append(name)
    return names


def _save_and_set_dns_localhost():
    """Guarda DNS actual y apunta interfaces a 127.0.0.1."""
    global _saved_dns
    if _saved_dns is not None:
        return
    saved = []
    for iface in _list_ipv4_interfaces():
        r = _run(["netsh", "interface", "ipv4", "show", "dnsservers", f"name={iface}"], timeout=10)
        dns_list = []
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            try:
                ipaddress.IPv4Address(line.split()[-1] if line.split() else "")
                cand = line.split()[-1]
                ipaddress.ip_address(cand)
                dns_list.append(cand)
            except Exception:
                if "dhcp" in line.lower() or "dhcp" in (r.stdout or "").lower():
                    dns_list = ["dhcp"]
        if not dns_list:
            blob = (r.stdout or "").lower()
            dns_list = ["dhcp"] if "dhcp" in blob else []
        saved.append((iface, dns_list))
        _run(
            ["netsh", "interface", "ipv4", "set", "dnsservers", f"name={iface}",
             "static", "127.0.0.1", "primary"],
            timeout=10,
        )
    _saved_dns = saved
    print(f"[NetPolicy] DNS → 127.0.0.1 en {len(saved)} interfaces")


def _restore_dns():
    global _saved_dns
    if _saved_dns is None:
        return
    for iface, dns_list in _saved_dns:
        if not dns_list or dns_list == ["dhcp"] or (len(dns_list) == 1 and dns_list[0] == "dhcp"):
            _run(
                ["netsh", "interface", "ipv4", "set", "dnsservers", f"name={iface}", "dhcp"],
                timeout=10,
            )
        else:
            primary = dns_list[0]
            _run(
                ["netsh", "interface", "ipv4", "set", "dnsservers", f"name={iface}",
                 "static", primary, "primary"],
                timeout=10,
            )
            for extra in dns_list[1:]:
                _run(
                    ["netsh", "interface", "ipv4", "add", "dnsservers", f"name={iface}",
                     extra],
                    timeout=10,
                )
    _saved_dns = None
    print("[NetPolicy] DNS restaurado")


def _stop_learner():
    global _learner
    if _learner:
        try:
            _learner.stop()
        except Exception:
            pass
        _learner = None


def set_denied_callback(cb):
    global _on_denied, _learner
    _on_denied = cb
    if _learner is not None:
        _learner._on_denied = cb
    if _host_proxy is not None:
        _host_proxy.update_callbacks(on_denied=cb)


def set_learned_callback(cb):
    global _on_learned, _learner
    _on_learned = cb
    if _learner is not None:
        _learner._on_learned = cb


def _proxy_host_allowed(name: str) -> bool:
    from domain_match import live_learn_target, name_is_allowed

    if name_is_allowed(name, _active_allowlist, _active_learned):
        return True
    target = live_learn_target(name, _active_allowlist, _active_learned)
    if not target:
        return False
    if target not in _active_learned:
        _active_learned.append(target)
        cb = _on_learned
        if cb:
            # No bloquear CONNECT con save_config a disco
            threading.Thread(
                target=lambda t=target: _safe_on_learned(cb, t),
                name="cm-proxy-learned",
                daemon=True,
            ).start()
    return True


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
    proxy = HostnameProxy(
        is_allowed=_proxy_host_allowed,
        on_denied=_on_denied,
    )
    if proxy.start():
        _host_proxy = proxy
    else:
        print("[NetPolicy] HostnameProxy no arrancó")


def _read_proxy_values(key):
    import winreg
    try:
        enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
    except OSError:
        enable = 0
    try:
        server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        server = ""
    try:
        override, _ = winreg.QueryValueEx(key, "ProxyOverride")
    except OSError:
        override = ""
    return int(enable), str(server), str(override)


def _write_proxy_values(key, enable, server, override):
    import winreg
    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(enable))
    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server or "")
    winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, override or "")


def _notify_proxy_changed():
    """Avisa a WinINET que cambió el proxy (Chrome/Edge lo toman)."""
    try:
        import ctypes
        internet_set_option = ctypes.windll.wininet.InternetSetOptionW
        # INTERNET_OPTION_SETTINGS_CHANGED = 39, INTERNET_OPTION_REFRESH = 37
        internet_set_option(0, 39, 0, 0)
        internet_set_option(0, 37, 0, 0)
    except Exception:
        pass


def _save_and_set_system_proxy():
    """Proxy machine-wide + todos los usuarios interactivos.

    El cliente corre como servicio (SYSTEM): setear solo HKCU no afecta al
    browser del niño. Forzamos ProxySettingsPerUser=0 + HKLM + cada HKU\\SID.
    """
    global _saved_win_proxy
    if _saved_win_proxy is not None:
        return
    import winreg

    proxy_server = "127.0.0.1:18080"
    proxy_override = "localhost;127.*;<local>;*.local"
    snapshot = {"hkcu": None, "hklm": None, "policy": None, "users": {}}

    try:
        # Política: un solo proxy para toda la máquina
        try:
            pol = winreg.CreateKeyEx(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Policies\Microsoft\Windows\CurrentVersion\Internet Settings",
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            )
            try:
                prev, _ = winreg.QueryValueEx(pol, "ProxySettingsPerUser")
                snapshot["policy"] = int(prev)
            except OSError:
                snapshot["policy"] = None
            winreg.SetValueEx(pol, "ProxySettingsPerUser", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(pol)
        except Exception as e:
            print(f"[NetPolicy] policy ProxySettingsPerUser: {e}")

        # HKLM (usado cuando ProxySettingsPerUser=0)
        try:
            hklm = winreg.CreateKeyEx(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings",
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            )
            snapshot["hklm"] = _read_proxy_values(hklm)
            _write_proxy_values(hklm, 1, proxy_server, proxy_override)
            winreg.CloseKey(hklm)
        except Exception as e:
            print(f"[NetPolicy] HKLM proxy: {e}")

        # HKCU del proceso (SYSTEM / servicio)
        try:
            hkcu = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            )
            snapshot["hkcu"] = _read_proxy_values(hkcu)
            _write_proxy_values(hkcu, 1, proxy_server, proxy_override)
            winreg.CloseKey(hkcu)
        except Exception as e:
            print(f"[NetPolicy] HKCU proxy: {e}")

        # Cada usuario interactivo cargado
        try:
            i = 0
            while True:
                try:
                    sid = winreg.EnumKey(winreg.HKEY_USERS, i)
                except OSError:
                    break
                i += 1
                if not sid.startswith("S-1-5-21-"):
                    continue
                path = sid + r"\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
                try:
                    ukey = winreg.CreateKeyEx(
                        winreg.HKEY_USERS, path, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
                    )
                    snapshot["users"][sid] = _read_proxy_values(ukey)
                    _write_proxy_values(ukey, 1, proxy_server, proxy_override)
                    winreg.CloseKey(ukey)
                except Exception:
                    continue
        except Exception as e:
            print(f"[NetPolicy] HKU proxy: {e}")

        _saved_win_proxy = snapshot
        _run(["netsh", "winhttp", "set", "proxy", proxy_server], timeout=10)
        _notify_proxy_changed()
        print(f"[NetPolicy] System proxy → {proxy_server} (machine-wide hostname gate)")
    except Exception as e:
        print(f"[NetPolicy] No se pudo setear proxy del sistema: {e}")


def _restore_system_proxy():
    global _saved_win_proxy
    if _saved_win_proxy is None:
        return
    import winreg
    snap = _saved_win_proxy
    try:
        if snap.get("policy") is not None or "policy" in snap:
            try:
                pol = winreg.CreateKeyEx(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Policies\Microsoft\Windows\CurrentVersion\Internet Settings",
                    0,
                    winreg.KEY_SET_VALUE,
                )
                if snap.get("policy") is None:
                    try:
                        winreg.DeleteValue(pol, "ProxySettingsPerUser")
                    except OSError:
                        pass
                else:
                    winreg.SetValueEx(
                        pol, "ProxySettingsPerUser", 0, winreg.REG_DWORD, int(snap["policy"])
                    )
                winreg.CloseKey(pol)
            except Exception as e:
                print(f"[NetPolicy] restore policy: {e}")

        if snap.get("hklm"):
            try:
                hklm = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings",
                    0,
                    winreg.KEY_SET_VALUE,
                )
                _write_proxy_values(hklm, *snap["hklm"])
                winreg.CloseKey(hklm)
            except Exception as e:
                print(f"[NetPolicy] restore HKLM: {e}")

        if snap.get("hkcu"):
            try:
                hkcu = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                    0,
                    winreg.KEY_SET_VALUE,
                )
                _write_proxy_values(hkcu, *snap["hkcu"])
                winreg.CloseKey(hkcu)
            except Exception as e:
                print(f"[NetPolicy] restore HKCU: {e}")

        for sid, vals in (snap.get("users") or {}).items():
            try:
                path = sid + r"\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
                ukey = winreg.OpenKey(winreg.HKEY_USERS, path, 0, winreg.KEY_SET_VALUE)
                _write_proxy_values(ukey, *vals)
                winreg.CloseKey(ukey)
            except Exception:
                continue

        _run(["netsh", "winhttp", "reset", "proxy"], timeout=10)
        _notify_proxy_changed()
        print("[NetPolicy] System proxy restaurado")
    except Exception as e:
        print(f"[NetPolicy] restore proxy: {e}")
    _saved_win_proxy = None


def _add_program_allow_rule():
    """Permite outbound del proceso cliente (proxy dial-out)."""
    exe = sys.executable
    name = f"{RULE_PREFIX} program"
    _run(
        [
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={name}", "dir=out", "action=allow", "enable=yes", "profile=any",
            f"program={exe}", "description=CiberMonday hostname proxy dial-out",
        ],
        timeout=10,
    )
    # Bloquear QUIC (bypass del proxy CONNECT)
    _run(
        [
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={RULE_PREFIX} block-quic", "dir=out", "action=block",
            "enable=yes", "profile=any", "protocol=UDP", "remoteport=443",
            "description=CiberMonday force TCP+SNI/CONNECT",
        ],
        timeout=10,
    )


def _start_learner(allowlist, learned=None):
    global _learner, _active_learned, _active_allowlist
    _active_allowlist = list(allowlist or [])
    _active_learned = list(learned or [])
    _stop_learner()
    try:
        from dns_learner import DnsLearner
    except ImportError as e:
        print(f"[NetPolicy] dns_learner no disponible: {e}")
        return
    learner = DnsLearner(
        on_ips=learn_ips,
        on_denied=_on_denied,
        on_learned=_on_learned,
    )
    if learner.start(allowlist or [], _active_learned):
        _learner = learner
        if getattr(learner, "listen_port_used", None) == 53:
            _save_and_set_dns_localhost()
        else:
            print(
                f"[NetPolicy] DNS learner en puerto "
                f"{getattr(learner, 'listen_port_used', '?')}; "
                "no se cambió DNS del sistema"
            )


def apply_network_policy(mode, allowlist, server_url, on_denied=None, learned=None, on_learned=None):
    global _last_fingerprint, _learned_ips, _on_denied, _on_learned, _active_learned, _active_allowlist
    if on_denied is not None:
        _on_denied = on_denied
    if on_learned is not None:
        _on_learned = on_learned
    if learned is not None:
        # Unión con memoria: el save a disco puede ir atrasado respecto del live-learn.
        incoming = list(learned or [])
        _active_learned = list(dict.fromkeys(incoming + list(_active_learned or [])))
    _active_allowlist = list(allowlist or [])
    if mode == "unrestricted":
        return clear_network_policy()

    remotes = build_allowed_remotes(mode, allowlist, server_url, learned=_active_learned)
    enable_dns = mode == "allowlist"
    al_key = "|".join(sorted(str(x).strip().lower() for x in (allowlist or []) if str(x).strip()))
    # learned NO va en el fingerprint: cada related nuevo (ytimg, clients4, …)
    # reventaba firewall/proxy a mitad de carga y YouTube nunca terminaba de abrir.
    fingerprint = f"{mode}|dns:{enable_dns}|al:{al_key}|proxy2|{'|'.join(remotes)}"
    if fingerprint == _last_fingerprint:
        if _learner and enable_dns:
            _learner.update_allowlist(allowlist or [], _active_learned)
            if _on_denied is not None:
                _learner._on_denied = _on_denied
            if _on_learned is not None:
                _learner._on_learned = _on_learned
        if _host_proxy and enable_dns:
            _host_proxy.update_callbacks(is_allowed=_proxy_host_allowed, on_denied=_on_denied)
        return True

    print(
        f"[NetPolicy] Aplicando modo={mode} destinos={len(remotes)} "
        f"learned={len(_active_learned or [])} dns_learn={enable_dns} host_proxy={enable_dns}"
    )
    _delete_our_rules()
    _set_outbound_block(True)
    _learned_ips = set()

    ok_count = 0
    for i, remote in enumerate(remotes):
        if _add_allow_rule(f"allow-{i}", remote):
            ok_count += 1
            if "/" not in remote:
                try:
                    ipaddress.ip_address(remote)
                    _learned_ips.add(remote)
                except ValueError:
                    pass

    if ok_count == 0 and remotes:
        print("[NetPolicy] Ninguna regla allow se aplicó")
        return False

    _add_allow_rule("dns-upstream", "1.1.1.1")
    if enable_dns:
        _add_program_allow_rule()

    _last_fingerprint = fingerprint
    if enable_dns:
        # Proxy primero: aunque DNS falle, el name-gate queda activo
        _start_host_proxy()
        _save_and_set_system_proxy()
        try:
            _start_learner(allowlist, _active_learned)
        except Exception as e:
            print(f"[NetPolicy] DNS learner error: {e}")
        _run(["ipconfig", "/flushdns"], timeout=10)
    else:
        _stop_learner()
        _stop_host_proxy()
        _restore_system_proxy()
        _restore_dns()
    return True


def clear_network_policy(force: bool = False):
    global _last_fingerprint, _learned_ips
    if not force and _last_fingerprint == "unrestricted":
        return True
    print("[NetPolicy] Limpiando política (unrestricted)")
    _stop_learner()
    _stop_host_proxy()
    _restore_system_proxy()
    _restore_dns()
    _delete_our_rules()
    _set_outbound_block(False)
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
