"""
Matching de allowlist estricto + lista aprendida (related).

- allowlist (admin/UI): lo que el usuario ve y edita
- allowlist_learned (implícita): hosts related (CDN/APIs) descubiertos por
  scan HTML de subrecursos o subdominios de apexes ya conocidos.
  No se muestran en la UI. No hay ventana temporal de “companion”.
"""

from __future__ import annotations

# Primer label típico de navegación a un sitio (no subrecurso CDN).
_NAV_FIRST_LABELS = frozenset({
    "www", "m", "mail", "smtp", "imap",
    "accounts", "login", "signin", "sso", "oauth",
    "drive", "docs", "sheets", "slides", "calendar",
    "maps", "news", "shop", "store", "pay",
    "photos", "meet", "chat", "classroom", "myaccount",
    "admin", "support", "help", "about", "blog", "search",
    "console", "cloud",
})

# Apexes demasiado anchos: nunca aprender el apex de 2 labels (abriría Search/APIs).
_NEVER_EXPAND_APEX = frozenset({
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "googleusercontent.com",
    "facebook.com",
    "instagram.com",
    "fbcdn.net",
    "twitter.com",
    "x.com",
    "reddit.com",
    "wikipedia.org",
    # Cloud providers: aprender FQDN (s3.amazonaws.com), nunca el apex entero
    "amazonaws.com",
    "cloudfront.net",
    "azurewebsites.net",
})


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


def related_learn_target(qname: str) -> str | None:
    """Qué host persistir como related, o None si no debe auto-aprenderse.

    - No aprender navegaciones (google.com, www.google.com, accounts.google.com, …)
    - Apex CDN de 2 labels (googlevideo.com, ytimg.com) sí, salvo NEVER_EXPAND
    - En plataformas compartidas (googleapis/gstatic/…) aprender el host exacto
    """
    name = (qname or "").strip().lower().rstrip(".")
    parts = [p for p in name.split(".") if p]
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        if name in _NEVER_EXPAND_APEX:
            return None
        return name
    if parts[0] in _NAV_FIRST_LABELS:
        return None
    apex = ".".join(parts[-2:])
    if apex in _NEVER_EXPAND_APEX:
        return name
    return apex


# Alias histórico (DNS companion window eliminado; misma sanitización).
companion_learn_target = related_learn_target


def under_known_allowlist(qname: str, explicit, learned=None) -> bool:
    """True si qname es el host o un subdominio de algo ya allowlist/learned."""
    return name_is_allowed(qname, explicit, learned)


_MEDIA_LABELS = frozenset({
    "video", "ytimg", "ggpht", "img", "cdn", "assets", "media",
    "stream", "hls", "dash", "playback", "static",
})

# Substrings en un label: githubassets, githubusercontent, fbcdn, …
_CDN_HINTS = (
    "cdn", "assets", "static", "usercontent", "ggpht", "ytimg",
    "img", "media", "video", "cloudfront",
)


def _looks_media_cdn(target: str) -> bool:
    """True para googlevideo / githubassets / *.cdn.example — no google.com."""
    parts = [p for p in (target or "").lower().split(".") if p]
    if any(p in _MEDIA_LABELS for p in parts):
        return True
    if any(h in p for p in parts for h in _CDN_HINTS):
        return True
    return any(p.endswith("video") or p.startswith("ytimg") for p in parts)


# Apexes compartidos: se puede aprender el FQDN exacto, nunca el apex de 2 labels.
_SHARED_PLATFORM_APEX = frozenset({
    "googleapis.com",
    "gstatic.com",
    "googleusercontent.com",
    "fbcdn.net",
    "amazonaws.com",
    "cloudfront.net",
    "azurewebsites.net",
})


def discovery_learn_target(qname: str) -> str | None:
    """Qué persistir desde el scan HTML (subrecursos / APIs del sitio).

    Incluye frontends compartidos (clients4.google.com, …): el bloqueo de
    navegación directa a google.com es por SNI/DNS name-gate, no dejando de
    aprender hosts que YouTube necesita.
    """
    target = related_learn_target(qname)
    if not target:
        return None
    apex = dns_apex(target)
    if apex in _NEVER_EXPAND_APEX or apex == "google.com":
        head = target.split(".", 1)[0]
        if head in _NAV_FIRST_LABELS:
            return None
        # S3/CloudFront/googleapis: FQDN exacto (github-cloud.s3.amazonaws.com)
        if apex in _SHARED_PLATFORM_APEX:
            return target
        if head.startswith("youtube") or "youtube" in target:
            return target
        if head in ("ytimg", "ggpht", "fonts") or _looks_media_cdn(target):
            return target
        if head in (
            "apis", "clients", "clients1", "clients2", "clients3", "clients4",
            "client-channel", "youtubei", "youtubei-att",
        ):
            return target
        return None
    return target


def media_cdn_learn_target(qname: str) -> str | None:
    """Aprender CDN de media/API desde DNS/SNI denegado (sin ventana).

    p.ej. *.googlevideo.com, i.ytimg.com, githubassets, *.s3.amazonaws.com.
    Nunca google.com / accounts.google.com.
    """
    target = related_learn_target(qname)
    if not target:
        return None
    apex = dns_apex(target)
    if apex in _NEVER_EXPAND_APEX:
        head = target.split(".", 1)[0]
        if head in _NAV_FIRST_LABELS:
            return None
        if apex in _SHARED_PLATFORM_APEX:
            return target
        if head.startswith("youtube") or "youtube" in target:
            return target
        if head in ("ytimg", "ggpht", "fonts") or _looks_media_cdn(target):
            return target
        return None
    if _looks_media_cdn(target):
        return target
    return None


def live_learn_target(qname: str, explicit, learned=None) -> str | None:
    """Qué aprender del tráfico en vivo (DNS/SNI/CONNECT).

    1) Refinamientos bajo apexes ya conocidos
    2) CDNs de media (googlevideo, ytimg, …) — no suelen estar en el HTML
    3) APIs de plataformas compartidas (clients4.google.com, youtubei…):
       misma heurística que el scan HTML, aplicada al tráfico real.
       No hardcodea hosts de un sitio; solo filtra navegación vs subrecurso.
    Nunca abre google.com / accounts.google.com.
    """
    name = (qname or "").strip().lower().rstrip(".")
    if not name:
        return None

    if under_known_allowlist(name, explicit, learned):
        target = related_learn_target(name)
        if not target:
            return None
        if name_matches_explicit(target, explicit) or name_matches_explicit(name, explicit):
            return None
        merged = list(learned or [])
        if target in merged or name_is_allowed(target, explicit, merged):
            apex = dns_apex(target)
            if apex in _NEVER_EXPAND_APEX and target not in merged:
                return target
            return None
        return target

    media = media_cdn_learn_target(name)
    if media:
        return media
    # Solo plataformas compartidas (google/gstatic/…): APIs, no sitios nuevos.
    apex = dns_apex(name)
    if apex in _NEVER_EXPAND_APEX or apex == "google.com":
        return discovery_learn_target(name)
    return None


# Solo apexes de navegación (no APIs/CDN related).
_NAVIGATION_BLOCKLIST = frozenset({
    "google.com",
    "www.google.com",
    "accounts.google.com",
    "mail.google.com",
    "play.google.com",
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
})


def sanitize_learned(entries) -> list[str]:
    """Quita aprendidos navegacionales / apexes anchos. Conserva CDNs y APIs related."""
    out = []
    seen = set()
    for raw in entries or []:
        e = normalize_host(raw)
        if not e or e in seen:
            continue
        if e in _NAVIGATION_BLOCKLIST or e in _NEVER_EXPAND_APEX:
            continue
        parts = e.split(".")
        apex = dns_apex(e)
        if parts and parts[0] in _NAV_FIRST_LABELS and apex in _NEVER_EXPAND_APEX:
            continue
        target = related_learn_target(e)
        if target is None and e.count(".") >= 2:
            if parts[0] in _NAV_FIRST_LABELS:
                continue
            if e in _NEVER_EXPAND_APEX or (len(parts) == 2 and apex in _NEVER_EXPAND_APEX):
                continue
            target = e
        if not target or target in seen:
            continue
        if target in _NEVER_EXPAND_APEX or target in _NAVIGATION_BLOCKLIST:
            continue
        seen.add(target)
        out.append(target)
    return out


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
