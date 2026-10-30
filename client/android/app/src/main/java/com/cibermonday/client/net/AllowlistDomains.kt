package com.cibermonday.client.net

/**
 * Matching estricto de allowlist (sin familias CDN hardcoded).
 * youtube.com → youtube.com / *.youtube.com / www|m.youtube.com.
 * Los CDN se descubren del tráfico (SNI denegado → pedido de acceso).
 */
object AllowlistDomains {

    /** Ventana tras visitar un sitio de la allowlist explícita para aprender related. */
    const val COMPANION_WINDOW_MS = 45_000L

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

    /** Apex aproximado para agrupar pedidos (rr.x.googlevideo.com → googlevideo.com). */
    fun dnsApex(host: String): String {
        val parts = host.trim().lowercase().trimEnd('.').split('.').filter { it.isNotBlank() }
        if (parts.size <= 2) return parts.joinToString(".")
        return parts.takeLast(2).joinToString(".")
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

    /** Convenience: allowlist cruda → ¿host permitido? */
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
