"""
Matching de allowlist estricto + lista aprendida (tráfico).

- allowlist (admin/UI): lo que el usuario ve y edita
- allowlist_learned (implícita): hosts descubiertos del tráfico al usar un
  sitio permitido (CDN, APIs). No se muestran en la UI.
"""

from __future__ import annotations

COMPANION_WINDOW_SEC = 45.0


def normalize_host(raw: str) -> str | None:
    e = (raw or "").strip()
    if not e or e.startswith("#"):
        return None
    if "#" in e:
        e = e.split("#", 1)[0].strip()
    e = e.lower()
    if not e:
        return None
    if e.startswith("https://"):
        e = e[8:]
    elif e.startswith("http://"):
        e = e[7:]
    e = e.split("/")[0].split(":")[0].strip()
    if e.startswith("*") and not e.startswith("*.") and len(e) > 1:
        e = "*." + e[1:]
    return e or None


def dns_apex(name: str) -> str:
    """Aproxima el apex registrable (últimas 2 etiquetas)."""
    parts = [p for p in (name or "").strip().lower().rstrip(".").split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    return ".".join(parts[-2:])


def active_allowlist_entries(allowlist) -> list[str]:
    out = []
    for raw in allowlist or []:
        e = normalize_host(raw)
        if e:
            out.append(e)
    return out


def merge_allowlists(explicit, learned) -> list[str]:
    """Allowlist efectiva = explícita + aprendida (sin duplicar)."""
    seen = set()
    out = []
    for raw in list(explicit or []) + list(learned or []):
        e = normalize_host(raw)
        if not e or e in seen:
            continue
        # learned solo apex simples (sin #)
        if e.startswith("*."):
            key = e
        else:
            key = e
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def expand_allowed_names(allowlist) -> set[str]:
    """Nombres a sembrar (apex + www/m)."""
    out: set[str] = set()
    for e in active_allowlist_entries(allowlist):
        if "/" in e:
            continue
        try:
            import ipaddress
            ipaddress.ip_address(e[2:] if e.startswith("*.") else e)
            continue
        except ValueError:
            pass
        host = e[2:] if e.startswith("*.") else e
        out.add(host)
        if not e.startswith("*."):
            out.add(f"www.{host}")
            out.add(f"m.{host}")
    return out


def wildcard_suffixes(allowlist) -> list[str]:
    return [e[2:] for e in active_allowlist_entries(allowlist) if e.startswith("*.")]


def name_is_allowed(qname: str, allowlist, learned=None) -> bool:
    """True si coincide con allowlist explícita o aprendida."""
    name = (qname or "").strip().lower().rstrip(".")
    if not name:
        return False
    for e in active_allowlist_entries(merge_allowlists(allowlist, learned)):
        if e.startswith("*."):
            suf = e[2:]
            if name == suf or name.endswith("." + suf):
                return True
            continue
        if name == e or name.endswith("." + e):
            return True
        if name in (f"www.{e}", f"m.{e}"):
            return True
    return False


def name_matches_explicit(qname: str, allowlist) -> bool:
    """True solo si matchea la allowlist del admin (no la aprendida)."""
    return name_is_allowed(qname, allowlist, learned=None)
