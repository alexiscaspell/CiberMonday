package com.cibermonday.client.net

import android.util.Log
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.regex.Pattern

/**
 * Descubre hosts related fetchando el HTML de apexes allowlist y extrayendo
 * SOLO URLs de subrecursos (script/img/css/… e URLs en texto), nunca <a href>.
 */
object AllowlistDiscover {
    private const val TAG = "AllowlistDiscover"
    private val executor = Executors.newSingleThreadExecutor()
    private val inflight = ConcurrentHashMap.newKeySet<String>()

    private val SUBRESOURCE_TAG = Pattern.compile(
        """<(script|img|image|source|video|audio|track|iframe|embed|object|link|use)\b([^>]*)>""",
        Pattern.CASE_INSENSITIVE
    )
    private val ATTR = Pattern.compile(
        """\b(src|srcset|data-src|data-srcset|poster|href)\s*=\s*["']([^"']+)["']""",
        Pattern.CASE_INSENSITIVE
    )
    private val URL_IN_TEXT = Pattern.compile(
        """https?://[a-zA-Z0-9][a-zA-Z0-9.\-]*[a-zA-Z0-9]\.[a-zA-Z]{2,}(?::\d+)?""" +
            """|//[a-zA-Z0-9][a-zA-Z0-9.\-]*[a-zA-Z0-9]\.[a-zA-Z]{2,}(?::\d+)?""",
        Pattern.CASE_INSENSITIVE
    )
    private val LINK_REL_OK = setOf(
        "stylesheet", "preload", "modulepreload", "icon", "shortcut icon",
        "apple-touch-icon", "manifest", "dns-prefetch", "preconnect",
    )

    fun discoverAsync(allowlist: List<String>, onDone: (List<String>) -> Unit) {
        val fp = allowlist.map { it.trim().lowercase() }.filter { it.isNotBlank() }.sorted().joinToString("|")
        if (fp.isBlank() || !inflight.add(fp)) return
        executor.execute {
            try {
                val hosts = discoverHosts(allowlist)
                Log.i(TAG, "related ${hosts.size}: ${hosts.take(20).joinToString()}${if (hosts.size > 20) "…" else ""}")
                onDone(hosts)
            } catch (e: Exception) {
                Log.w(TAG, "error: ${e.message}")
            } finally {
                inflight.remove(fp)
            }
        }
    }

    fun discoverHosts(allowlist: List<String>, maxEntries: Int = 12): List<String> {
        val out = linkedSetOf<String>()
        var n = 0
        for (raw in allowlist) {
            if (n >= maxEntries) break
            val e = AllowlistDomains.normalize(raw) ?: continue
            if (e.startsWith("*.")) continue
            n++
            for (h in discoverForEntry(e)) {
                out.add(h)
            }
        }
        return AllowlistDomains.sanitizeLearned(out.toList())
    }

    private fun discoverForEntry(entry: String): List<String> {
        val e = AllowlistDomains.normalize(entry) ?: return emptyList()
        if (e.startsWith("*.") || "/" in e) return emptyList()
        if (e.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) return emptyList()
        val apex = AllowlistDomains.dnsApex(e).ifBlank { e }
        val found = linkedSetOf<String>()
        val follow = mutableListOf<String>()
        for (url in listOf("https://$apex/", "https://www.$apex/", "https://m.$apex/")) {
            val html = fetch(url) ?: continue
            val (hosts, scripts) = extractHostsAndFollow(html, url)
            found.addAll(hosts)
            follow.addAll(scripts)
            break
        }
        val seenFollow = mutableSetOf<String>()
        for (u in follow.take(10)) {
            if (!seenFollow.add(u)) continue
            val body = fetch(u) ?: continue
            found.addAll(extractMediaHostsFromScript(body))
        }
        val learned = linkedSetOf<String>()
        for (h in found) {
            if (h == apex || h == e || h == "www.$apex" || h == "m.$apex") continue
            val target = AllowlistDomains.discoveryLearnTarget(h) ?: continue
            if (target == apex || target == e) continue
            learned.add(target)
        }
        return AllowlistDomains.sanitizeLearned(learned.toList())
    }

    private fun fetch(url: String): String? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = 8000
                readTimeout = 8000
                instanceFollowRedirects = true
                setRequestProperty(
                    "User-Agent",
                    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36 CiberMondayDiscover/1.0"
                )
                setRequestProperty("Accept", "text/html,*/*")
            }
            if (conn.responseCode !in 200..399) return null
            conn.inputStream.bufferedReader().use { it.readText().take(2_000_000) }
        } catch (e: Exception) {
            Log.d(TAG, "fetch $url: ${e.message}")
            null
        } finally {
            conn?.disconnect()
        }
    }

    private fun extractHostsAndFollow(html: String, baseUrl: String): Pair<Set<String>, List<String>> {
        val hosts = linkedSetOf<String>()
        val follow = mutableListOf<String>()
        val tagMatcher = SUBRESOURCE_TAG.matcher(html)
        while (tagMatcher.find()) {
            val tag = tagMatcher.group(1)?.lowercase() ?: continue
            val attrs = tagMatcher.group(2) ?: continue
            if (tag == "link") {
                val relM = Pattern.compile("""\brel\s*=\s*["']([^"']+)["']""", Pattern.CASE_INSENSITIVE)
                    .matcher(attrs)
                val rel = if (relM.find()) relM.group(1)?.lowercase().orEmpty() else ""
                if (rel.split(Regex("\\s+")).none { it in LINK_REL_OK } &&
                    "stylesheet" !in rel && "preload" !in rel && "icon" !in rel
                ) {
                    continue
                }
            }
            val attrM = ATTR.matcher(attrs)
            while (attrM.find()) {
                val attr = attrM.group(1)?.lowercase() ?: continue
                val raw = attrM.group(2) ?: continue
                if (attr == "href" && tag != "link") continue
                for (piece in splitSrcset(raw)) {
                    val abs = resolve(baseUrl, piece)
                    hostFromUrl(abs)?.let { hosts.add(it) }
                    val low = abs.lowercase().substringBefore("?")
                    val uh = hostFromUrl(abs)
                    val baseHost = hostFromUrl(baseUrl)
                    val baseApex = baseHost?.let { AllowlistDomains.dnsApex(it) }.orEmpty()
                    if ((low.endsWith(".js") || "/js/" in low || "/s/player/" in low) &&
                        uh != null && baseApex.isNotBlank() &&
                        (uh == baseApex || uh.endsWith(".$baseApex"))
                    ) {
                        follow.add(abs)
                    }
                }
            }
        }
        // No escanear URLs sueltas del HTML (capturan <a>/promos); solo tags de subrecurso.
        return hosts to follow
    }

    private fun extractMediaHostsFromScript(body: String): Set<String> {
        val hosts = linkedSetOf<String>()
        val urlM = URL_IN_TEXT.matcher(body)
        while (urlM.find()) {
            var u = urlM.group() ?: continue
            if (u.startsWith("//")) u = "https:$u"
            val h = hostFromUrl(u) ?: continue
            if (AllowlistDomains.mediaCdnLearnTarget(h) != null) hosts.add(h)
        }
        return hosts
    }

    private fun splitSrcset(val_: String): List<String> {
        val parts = val_.split(",").map { it.trim().split(Regex("\\s+")).firstOrNull()?.trim().orEmpty() }
            .filter { it.isNotBlank() }
        return parts.ifEmpty { listOf(val_).filter { it.isNotBlank() } }
    }

    private fun resolve(base: String, ref: String): String {
        val r = ref.trim()
        if (r.startsWith("http://") || r.startsWith("https://")) return r
        if (r.startsWith("//")) return "https:$r"
        return try {
            URL(URL(base), r).toString()
        } catch (_: Exception) {
            r
        }
    }

    private fun hostFromUrl(url: String): String? {
        return try {
            val u = if (url.startsWith("//")) "https:$url" else url
            URL(u).host?.lowercase()?.trimEnd('.')?.takeIf { it.isNotBlank() }
        } catch (_: Exception) {
            null
        }
    }
}
