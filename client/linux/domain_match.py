"""
Matching de nombres allowlist + familias CDN (Linux / mismo API que Windows).
"""

from __future__ import annotations

DOMAIN_FAMILIES = {
    "youtube.com": (
        "youtube.com", "youtu.be", "youtube-nocookie.com", "youtubekids.com", "yt.be",
        "googlevideo.com", "gvt1.com", "gvt2.com", "gvt3.com",
        "ytimg.com", "yt3.ggpht.com", "ggpht.com",
        "googleusercontent.com", "googleapis.com", "gstatic.com",
        # Hosts concretos de Google (login / player UI); no hace falta abrir todo google.com
        # pero varios CNAMEs de YouTube viven bajo *.l.google.com / google.com.
        "google.com",
        "accounts.google.com", "play.google.com",
        "youtubei.googleapis.com", "youtube.googleapis.com",
        "youtube-ui.l.google.com", "ytimg.l.google.com", "ytstatic.l.google.com",
        "wide-youtube.l.google.com", "video.google.com",
    ),
    "github.com": (
        "github.com", "githubusercontent.com", "githubassets.com",
        "github.githubassets.com", "avatars.githubusercontent.com",
        "avatars0.githubusercontent.com", "avatars1.githubusercontent.com",
        "avatars2.githubusercontent.com", "avatars3.githubusercontent.com",
        "raw.githubusercontent.com", "objects.githubusercontent.com",
        "camo.githubusercontent.com", "cloud.githubusercontent.com",
        "media.githubusercontent.com", "codeload.github.com", "api.github.com",
        "ghcr.io", "npm.pkg.github.com", "github.io",
    ),
    "netflix.com": ("netflix.com", "nflxvideo.net", "nflxso.net", "nflximg.net", "fast.com"),
    "twitch.tv": ("twitch.tv", "ttvnw.net", "jtvnw.net", "twitchcdn.net"),
    "discord.com": ("discord.com", "discordapp.com", "discord.gg", "discord.media", "discordapp.net"),
    "instagram.com": ("instagram.com", "cdninstagram.com", "facebook.com", "fbcdn.net", "facebook.net"),
    "facebook.com": ("facebook.com", "fbcdn.net", "facebook.net", "instagram.com", "cdninstagram.com"),
    "tiktok.com": ("tiktok.com", "tiktokv.com", "tiktokcdn.com", "musical.ly", "byteoversea.com"),
}


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


def expand_allowed_names(allowlist) -> set[str]:
    """Nombres exactos permitidos (sin wildcards) tras expandir familias."""
    out: set[str] = set()
    for raw in allowlist or []:
        e = normalize_host(raw)
        if not e or "/" in e:
            continue
        try:
            import ipaddress
            ipaddress.ip_address(e)
            continue
        except ValueError:
            pass
        host = e[2:] if e.startswith("*.") else e
        out.add(host)
        out.add(f"www.{host}")
        out.add(f"m.{host}")
        for fam_apex, family in DOMAIN_FAMILIES.items():
            if host == fam_apex or host.endswith("." + fam_apex) or fam_apex in host or host in family:
                out.update(family)
        if "youtube" in host or host in ("youtu.be",) or "googlevideo" in host:
            out.update(DOMAIN_FAMILIES["youtube.com"])
        if "github" in host or host.endswith("githubusercontent.com") or host == "ghcr.io":
            out.update(DOMAIN_FAMILIES["github.com"])
    return out


def wildcard_suffixes(allowlist) -> list[str]:
    """Sufijos para *.example.com → example.com."""
    suffixes = []
    for raw in allowlist or []:
        e = normalize_host(raw)
        if not e:
            continue
        if e.startswith("*."):
            suffixes.append(e[2:])
    return suffixes


def name_is_allowed(qname: str, allowlist) -> bool:
    """True si QNAME/SNI está permitido por allowlist + familias."""
    name = (qname or "").strip().lower().rstrip(".")
    if not name:
        return False
    allowed = expand_allowed_names(allowlist)
    if name in allowed:
        return True
    for a in allowed:
        if name.endswith("." + a):
            return True
    for suf in wildcard_suffixes(allowlist):
        if name == suf or name.endswith("." + suf):
            return True
    return False
