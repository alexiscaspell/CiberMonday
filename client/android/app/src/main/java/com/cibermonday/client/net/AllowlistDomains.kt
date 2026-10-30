package com.cibermonday.client.net

/**
 * Matching estricto de allowlist (sin familias CDN hardcoded).
 * Related: scan HTML de subrecursos + CDNs de media del tráfico.
 * Sin ventana temporal “companion”.
 */
object AllowlistDomains {

    private val NAV_FIRST_LABELS = setOf(
        "www", "m", "mail", "smtp", "imap",
        "accounts", "login", "signin", "sso", "oauth",
        "drive", "docs", "sheets", "slides", "calendar",
        "maps", "news", "shop", "store", "pay",
        "photos", "meet", "chat", "classroom", "myaccount",
        "admin", "support", "help", "about", "blog", "search",
        "console", "cloud",
    )

    private val NEVER_EXPAND_APEX = setOf(
        "google.com", "googleapis.com", "gstatic.com", "googleusercontent.com",
        "facebook.com", "instagram.com", "fbcdn.net",
        "twitter.com", "x.com", "reddit.com", "wikipedia.org",
    )

    private val MEDIA_LABELS = setOf(
        "video", "ytimg", "ggpht", "img", "cdn", "assets", "media",
        "stream", "hls", "dash", "playback", "static",
    )

    private val DISCOVERY_GOOGLE_HEADS = setOf(
        "apis", "clients", "clients1", "clients2", "clients3", "clients4",
        "client-channel", "youtubei", "youtubei-att", "ytimg", "ggpht", "fonts",
    )

    fun normalize(raw: String): String? {
        var e = raw.trim()
        if (e.isBlank() || e.startsWith("#")) return null
        if ('#' in e) e = e.substringBefore("#").trim()
        e = e.lowercase()
        if (e.isBlank()) return null
        e = e.removePrefix("http://").removePrefix("https://")
        e = e.substringBefore("/").substringBefore(":").trim()
        if (e.isBlank()) return null
        if (e.startsWith("*") && !e.startsWith("*.") && e.length > 1) {
            e = "*." + e.substring(1)
        }
        return e
    }

    fun apexOf(entry: String): String = entry.removePrefix("*.")

    fun dnsApex(host: String): String {
        val parts = host.trim().lowercase().trimEnd('.').split('.').filter { it.isNotBlank() }
        if (parts.size <= 2) return parts.joinToString(".")
        return parts.takeLast(2).joinToString(".")
    }

    fun relatedLearnTarget(qname: String): String? {
        val name = qname.trim().lowercase().trimEnd('.')
        val parts = name.split('.').filter { it.isNotBlank() }
        if (parts.size < 2) return null
        if (parts.size == 2) {
            return if (name in NEVER_EXPAND_APEX) null else name
        }
        if (parts[0] in NAV_FIRST_LABELS) return null
        val apex = parts.takeLast(2).joinToString(".")
        if (apex in NEVER_EXPAND_APEX) return name
        return apex
    }

    fun companionLearnTarget(qname: String): String? = relatedLearnTarget(qname)

    private fun looksMediaCdn(target: String): Boolean {
        val parts = target.lowercase().split('.').filter { it.isNotBlank() }
        if (parts.any { it in MEDIA_LABELS }) return true
        return parts.any { it.endsWith("video") || it.startsWith("ytimg") || "ggpht" in it }
    }

    fun discoveryLearnTarget(qname: String): String? {
        val target = relatedLearnTarget(qname) ?: return null
        val apex = dnsApex(target)
        if (apex in NEVER_EXPAND_APEX || apex == "google.com") {
            val head = target.substringBefore('.')
            if (head.startsWith("youtube") || "youtube" in target) return target
            if (head in DISCOVERY_GOOGLE_HEADS || looksMediaCdn(target)) return target
            return null
        }
        return target
    }

    fun mediaCdnLearnTarget(qname: String): String? {
        val target = relatedLearnTarget(qname) ?: return null
        val apex = dnsApex(target)
        if (apex in NEVER_EXPAND_APEX) {
            val head = target.substringBefore('.')
            if (head.startsWith("youtube") || "youtube" in target) return target
            if (head in setOf("ytimg", "ggpht", "fonts") || looksMediaCdn(target)) return target
            return null
        }
        return if (looksMediaCdn(target)) target else null
    }

    /**
     * Aprender en vivo: refinamiento bajo known, o CDN de media (googlevideo…).
     * Sin ventana temporal — no abre google.com por timing.
     */
    fun liveLearnTarget(qname: String, explicit: List<String>, learned: List<String>): String? {
        val name = qname.trim().lowercase().trimEnd('.')
        if (name.isBlank()) return null
        if (hostAllowed(name, explicit, learned)) {
            val target = relatedLearnTarget(name) ?: return null
            if (matchesExplicit(target, explicit) || matchesExplicit(name, explicit)) return null
            if (target in learned || hostAllowed(target, explicit, learned)) {
                val apex = dnsApex(target)
                if (apex in NEVER_EXPAND_APEX && target !in learned) return target
                return null
            }
            return target
        }
        return mediaCdnLearnTarget(name)
    }

    fun sanitizeLearned(entries: List<String>): List<String> {
        val out = linkedSetOf<String>()
        for (raw in entries) {
            val e = normalize(raw) ?: continue
            val target = relatedLearnTarget(e)
                ?: if (e.count { it == '.' } >= 2 && e !in NEVER_EXPAND_APEX) {
                    val parts = e.split('.')
                    if (parts[0] in NAV_FIRST_LABELS) null
                    else if (parts.size == 2 && e in NEVER_EXPAND_APEX) null
                    else e
                } else null
            if (target.isNullOrBlank() || target in NEVER_EXPAND_APEX) continue
            out.add(target)
        }
        return out.toList()
    }

    fun expand(entries: List<String>): Set<String> {
        val out = linkedSetOf<String>()
        for (raw in entries) {
            val e = normalize(raw) ?: continue
            out.add(e)
            if (!e.startsWith("*.") && !looksLikeIpOrCidr(e)) {
                val host = apexOf(e)
                out.add("www.$host")
                out.add("m.$host")
            }
        }
        return out
    }

    private fun looksLikeIpOrCidr(e: String): Boolean {
        if (e.contains("/")) return true
        return e.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))
    }

    fun hostAllowed(host: String, expanded: Set<String>): Boolean {
        val h = host.trim().lowercase().trimEnd('.')
        if (h.isBlank()) return false
        for (entry in expanded) {
            if (looksLikeIpOrCidr(entry)) continue
            val e = normalize(entry) ?: continue
            if (e.startsWith("*.")) {
                val suffix = e.substring(2)
                if (h == suffix || h.endsWith(".$suffix")) return true
            } else if (h == e || h.endsWith(".$e")) {
                return true
            }
        }
        return false
    }

    fun hostAllowed(host: String, allowlist: List<String>): Boolean {
        return hostAllowed(host, expand(allowlist))
    }

    fun hostAllowed(host: String, explicit: List<String>, learned: List<String>): Boolean {
        return hostAllowed(host, expand(explicit + learned))
    }

    fun matchesExplicit(host: String, explicit: List<String>): Boolean {
        return hostAllowed(host, expand(explicit))
    }
}
