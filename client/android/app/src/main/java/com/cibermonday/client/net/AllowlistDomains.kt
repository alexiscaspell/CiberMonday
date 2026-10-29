package com.cibermonday.client.net

/**
 * Expande dominios de allowlist a familias CDN típicas
 * (p.ej. youtube.com → googlevideo.com, ytimg.com, …).
 *
 * Acepta: youtube.com, *.youtube.com, *youtube.com (typo frecuente).
 */
object AllowlistDomains {

    private val FAMILIES = mapOf(
        "youtube.com" to listOf(
            "youtube.com", "youtu.be", "youtube-nocookie.com", "yt.be",
            "googlevideo.com", "ytimg.com", "yt3.ggpht.com", "ggpht.com",
            "googleusercontent.com", "googleapis.com", "gstatic.com",
            "google.com", "youtubekids.com"
        ),
        "netflix.com" to listOf(
            "netflix.com", "nflxvideo.net", "nflxso.net", "nflximg.net", "fast.com"
        ),
        "twitch.tv" to listOf(
            "twitch.tv", "ttvnw.net", "jtvnw.net", "twitchcdn.net"
        ),
        "discord.com" to listOf(
            "discord.com", "discordapp.com", "discord.gg", "discord.media", "discordapp.net"
        ),
        "instagram.com" to listOf(
            "instagram.com", "cdninstagram.com", "facebook.com", "fbcdn.net", "facebook.net"
        ),
        "facebook.com" to listOf(
            "facebook.com", "fbcdn.net", "facebook.net", "instagram.com", "cdninstagram.com"
        ),
        "tiktok.com" to listOf(
            "tiktok.com", "tiktokv.com", "tiktokcdn.com", "musical.ly", "byteoversea.com"
        ),
    )

    fun expand(entries: List<String>): Set<String> {
        val out = linkedSetOf<String>()
        for (raw in entries) {
            val e = normalize(raw) ?: continue
            out.add(e)
            val apex = apexOf(e)
            if (!e.startsWith("*.") && !looksLikeIpOrCidr(e)) {
                out.add("www.$e")
                out.add("m.$e")
            }
            FAMILIES[apex]?.forEach { out.add(it) }
            // Cualquier mención a youtube
            if (apex.contains("youtube") || apex == "youtu.be" || apex.contains("googlevideo")) {
                FAMILIES["youtube.com"]?.forEach { out.add(it) }
            }
        }
        return out
    }

    /**
     * Normaliza entrada de allowlist.
     * "*youtube.com" → "*.youtube.com"
     * "https://YouTube.com/watch" → "youtube.com"
     */
    fun normalize(raw: String): String? {
        var e = raw.trim().lowercase()
        if (e.isBlank()) return null
        e = e.removePrefix("http://").removePrefix("https://")
        e = e.substringBefore("/").substringBefore(":")
        if (e.isBlank()) return null
        // *youtube.com (sin punto) → *.youtube.com
        if (e.startsWith("*") && !e.startsWith("*.") && e.length > 1) {
            e = "*." + e.substring(1)
        }
        return e
    }

    fun apexOf(entry: String): String {
        return entry.removePrefix("*.")
    }

    private fun looksLikeIpOrCidr(e: String): Boolean {
        if (e.contains("/")) return true
        return e.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))
    }

    /** ¿El host DNS está permitido por la lista expandida? */
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
}
