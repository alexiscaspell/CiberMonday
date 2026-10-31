"""
Descubrimiento de hosts related a partir del HTML de sitios allowlist.

Estrategia: al activar el filtro, se hace un fetch en background de cada apex
explícito y se extraen SOLO URLs de subrecursos (script/img/css/iframe/…),
nunca <a href> (eso serían navegaciones a otros sitios como google.com).

No requiere MITM: no leemos Referer del tráfico del usuario.
"""

from __future__ import annotations

import re
import threading
from html.parser import HTMLParser
from typing import Callable, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from domain_match import (
    dns_apex,
    learn_host_target,
    normalize_host,
    sanitize_learned,
)

# Atributos de subrecurso (no navegación)
_SUBRESOURCE_ATTRS = frozenset({
    "src", "srcset", "data-src", "data-srcset",
    "poster", "href",  # href solo si el tag es link (stylesheet/preload/…)
})
_SUBRESOURCE_TAGS = frozenset({
    "script", "img", "image", "source", "video", "audio", "track",
    "iframe", "embed", "object", "link", "use",
})
_LINK_REL_OK = frozenset({
    "stylesheet", "preload", "modulepreload", "icon", "shortcut icon",
    "apple-touch-icon", "manifest", "dns-prefetch", "preconnect",
})

_URL_IN_TEXT = re.compile(
    r"""https?://[a-zA-Z0-9][a-zA-Z0-9.\-]*[a-zA-Z0-9]\.[a-zA-Z]{2,}(?::\d+)?"""
    r"""|//[a-zA-Z0-9][a-zA-Z0-9.\-]*[a-zA-Z0-9]\.[a-zA-Z]{2,}(?::\d+)?""",
    re.I,
)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 CiberMondayDiscover/1.0"
)


class _SubresourceParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = (tag or "").lower()
        if tag not in _SUBRESOURCE_TAGS:
            return
        ad = {k.lower(): (v or "") for k, v in attrs if k}
        if tag == "link":
            rel = ad.get("rel", "").lower()
            if not any(r.strip() in _LINK_REL_OK for r in rel.split()):
                # Evitar <link> que sea navegación rara; sin rel útil, ignorar
                if "stylesheet" not in rel and "preload" not in rel and "icon" not in rel:
                    return
        for attr, val in ad.items():
            if attr not in _SUBRESOURCE_ATTRS:
                continue
            if attr == "href" and tag != "link":
                continue
            for piece in _split_srcset(val):
                abs_url = urljoin(self.base_url, piece.strip())
                if abs_url:
                    self.urls.append(abs_url)

    def handle_data(self, data):
        # URLs embebidas en JS/CSS inline (subrecursos dinámicos frecuentes)
        if not data or "://" not in data and "//" not in data:
            return
        for m in _URL_IN_TEXT.finditer(data):
            u = m.group(0)
            if u.startswith("//"):
                u = "https:" + u
            self.urls.append(u)


def _split_srcset(val: str) -> list[str]:
    out = []
    for part in (val or "").split(","):
        bit = part.strip().split(" ")[0].strip()
        if bit:
            out.append(bit)
    return out or ([val] if val else [])


def _host_from_url(url: str) -> Optional[str]:
    try:
        if url.startswith("//"):
            url = "https:" + url
        p = urlparse(url)
        host = (p.hostname or "").lower().rstrip(".")
        return host or None
    except Exception:
        return None


def _fetch(url: str, timeout: float = 8.0) -> Optional[str]:
    try:
        # Preferir proxy local (CONNECT ya allowlist) para no pelear con el
        # outbound-block del firewall; si no hay proxy, directo.
        from urllib.request import build_opener, ProxyHandler
        req = Request(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
        proxies = {"http": "http://127.0.0.1:18080", "https": "http://127.0.0.1:18080"}
        opener = build_opener(ProxyHandler(proxies))
        try:
            resp_ctx = opener.open(req, timeout=timeout)
        except Exception:
            opener = build_opener(ProxyHandler({}))
            resp_ctx = opener.open(req, timeout=timeout)
        with resp_ctx as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read(2_000_000)
        # Solo parsear como HTML si parece texto
        if "html" not in ctype and b"<" not in raw[:200]:
            # Igual buscar URLs en el blob (JS)
            text = raw.decode("utf-8", errors="ignore")
            hosts = set()
            for m in _URL_IN_TEXT.finditer(text):
                h = _host_from_url(m.group(0) if "://" in m.group(0) else "https:" + m.group(0))
                if h:
                    hosts.add(h)
            return "\n".join(f"https://{h}/" for h in hosts)  # fake doc of urls only
        return raw.decode("utf-8", errors="ignore")
    except (URLError, HTTPError, TimeoutError, OSError, ValueError) as e:
        print(f"[Discover] fetch {url}: {e}")
        return None


def _hosts_from_html(html: str, base_url: str) -> tuple[set[str], list[str]]:
    """Hosts desde tags de subrecurso + scripts same-site a seguir."""
    found: set[str] = set()
    follow: list[str] = []
    base_host = _host_from_url(base_url) or ""
    base_apex = dns_apex(base_host) if base_host else ""
    parser = _SubresourceParser(base_url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    for u in parser.urls:
        h = _host_from_url(u)
        if h:
            found.add(h)
        low = u.lower().split("?", 1)[0]
        if not (low.endswith(".js") or "/js/" in low or "/s/player/" in low):
            continue
        # Solo seguir JS del mismo apex (evita polyfills de terceros)
        uh = _host_from_url(u)
        if uh and base_apex and (uh == base_apex or uh.endswith("." + base_apex)):
            follow.append(u)
    return found, follow


def _hosts_from_script(body: str) -> set[str]:
    """URLs embebidas en JS del sitio (cualquier host de subrecurso)."""
    found: set[str] = set()
    for m in _URL_IN_TEXT.finditer(body or ""):
        raw = m.group(0)
        h = _host_from_url(raw if "://" in raw else "https:" + raw)
        if h and learn_host_target(h):
            found.add(h)
    return found


def discover_hosts_for_entry(entry: str) -> list[str]:
    """Descubre hosts related para un ítem de allowlist (apex)."""
    e = normalize_host(entry)
    if not e or e.startswith("*.") or "/" in e:
        return []
    try:
        import ipaddress
        ipaddress.ip_address(e)
        return []
    except ValueError:
        pass

    apex = dns_apex(e) or e
    found: set[str] = set()
    follow_urls: list[str] = []
    for url in (f"https://{apex}/", f"https://www.{apex}/", f"https://m.{apex}/"):
        html = _fetch(url)
        if not html:
            continue
        hosts, follow = _hosts_from_html(html, url)
        found |= hosts
        follow_urls.extend(follow)
        break  # un HTML exitoso basta

    # Un nivel: JS same-site (players suelen declarar CDNs de video)
    seen_follow = set()
    for u in follow_urls[:10]:
        if u in seen_follow:
            continue
        seen_follow.add(u)
        body = _fetch(u, timeout=8.0)
        if not body:
            continue
        found |= _hosts_from_script(body)

    learned = []
    seen = set()
    for h in sorted(found):
        # No aprender el propio apex allowlist (ya está)
        if h == apex or h == e or h in (f"www.{apex}", f"m.{apex}"):
            continue
        # No abrir Search/Accounts vía HTML; MITM+Referer cubre lo puntual.
        if dns_apex(h) == "google.com":
            continue
        target = learn_host_target(h)
        if not target or target in seen:
            continue
        # Ya cubierto por la allowlist explícita (apex y subdominios)
        if target == apex or target == e or target.endswith("." + apex):
            continue
        seen.add(target)
        learned.append(target)
    return sanitize_learned(learned)


def discover_hosts(allowlist: Iterable[str], max_entries: int = 12) -> list[str]:
    """Scan de todos los apexes explícitos (cap para no demorar)."""
    out: list[str] = []
    seen = set()
    n = 0
    for raw in allowlist or []:
        if n >= max_entries:
            break
        e = normalize_host(raw)
        if not e or e.startswith("*."):
            continue
        n += 1
        for h in discover_hosts_for_entry(e):
            if h not in seen:
                seen.add(h)
                out.append(h)
    return sanitize_learned(out)


_lock = threading.Lock()
_inflight = set()


def discover_async(
    allowlist: Iterable[str],
    on_done: Callable[[list[str]], None],
    fingerprint: str = "",
):
    """Lanza scan en background; on_done(hosts) en el worker thread."""
    fp = fingerprint or "|".join(sorted(str(x) for x in (allowlist or [])))
    with _lock:
        if fp in _inflight:
            return
        _inflight.add(fp)

    def _run():
        try:
            hosts = discover_hosts(allowlist)
            print(f"[Discover] {len(hosts)} hosts related: {', '.join(hosts[:20])}"
                  + ("…" if len(hosts) > 20 else ""))
            on_done(hosts)
        except Exception as e:
            print(f"[Discover] error: {e}")
        finally:
            with _lock:
                _inflight.discard(fp)

    threading.Thread(target=_run, name="cm-allow-discover", daemon=True).start()
