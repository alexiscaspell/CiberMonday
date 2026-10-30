package com.cibermonday.client.session

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList

data class SessionData(
    val timeLimitSeconds: Int,
    val startTimeIso: String,
    val endTimeIso: String
)

data class SessionInfo(
    val remainingSeconds: Int,
    val isExpired: Boolean,
    val timeLimitSeconds: Int
)

data class ServerEntry(
    val url: String,
    var lastSeen: String = Instant.now().toString(),
    var timeoutCount: Int = 0
)

class SessionStore(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private val listeners = CopyOnWriteArrayList<() -> Unit>()

    fun addListener(listener: () -> Unit) {
        listeners.add(listener)
    }

    fun removeListener(listener: () -> Unit) {
        listeners.remove(listener)
    }

    private fun notifyChanged() {
        listeners.forEach { it.invoke() }
    }

    var clientId: String?
        get() = prefs.getString(KEY_CLIENT_ID, null)
        set(value) {
            prefs.edit().putString(KEY_CLIENT_ID, value).apply()
            notifyChanged()
        }

    fun ensureClientId(): String {
        val existing = clientId
        if (!existing.isNullOrBlank()) return existing
        val generated = UUID.randomUUID().toString()
        clientId = generated
        return generated
    }

    var serverUrl: String
        get() = prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL
        set(value) {
            prefs.edit().putString(KEY_SERVER_URL, value.trim().trimEnd('/')).apply()
            addServer(value)
            notifyChanged()
        }

    var customName: String?
        get() = prefs.getString(KEY_CUSTOM_NAME, null)
        set(value) {
            prefs.edit().putString(KEY_CUSTOM_NAME, value).apply()
        }

    var syncInterval: Int
        get() = prefs.getInt(KEY_SYNC_INTERVAL, DEFAULT_SYNC_INTERVAL)
        set(value) {
            prefs.edit().putInt(KEY_SYNC_INTERVAL, value.coerceIn(5, 300)).apply()
        }

    var lockRecheckInterval: Int
        get() = prefs.getInt(KEY_LOCK_RECHECK, DEFAULT_LOCK_RECHECK)
        set(value) {
            prefs.edit().putInt(KEY_LOCK_RECHECK, value.coerceIn(1, 60)).apply()
        }

    var maxServerTimeouts: Int
        get() = prefs.getInt(KEY_MAX_TIMEOUTS, DEFAULT_MAX_TIMEOUTS)
        set(value) {
            prefs.edit().putInt(KEY_MAX_TIMEOUTS, value.coerceAtLeast(1)).apply()
        }

    var setupComplete: Boolean
        get() = prefs.getBoolean(KEY_SETUP_COMPLETE, false)
        set(value) {
            prefs.edit().putBoolean(KEY_SETUP_COMPLETE, value).apply()
        }

    var vpnConsentNeeded: Boolean
        get() = prefs.getBoolean(KEY_VPN_CONSENT_NEEDED, false)
        set(value) {
            prefs.edit().putBoolean(KEY_VPN_CONSENT_NEEDED, value).apply()
        }

    var vpnConsentGranted: Boolean
        get() = prefs.getBoolean(KEY_VPN_CONSENT_GRANTED, false)
        set(value) {
            prefs.edit().putBoolean(KEY_VPN_CONSENT_GRANTED, value).apply()
        }

    /**
     * Si es false, el servicio no debe reiniciarse solo (admin detuvo la sesión).
     * Se vuelve a true al abrir la app o al recibir tiempo nuevo.
     */
    var serviceEnabled: Boolean
        get() = prefs.getBoolean(KEY_SERVICE_ENABLED, true)
        set(value) {
            prefs.edit().putBoolean(KEY_SERVICE_ENABLED, value).commit()
        }

    /**
     * Hay countdown/bloqueo local (equivalente a SessionData en el registro de Windows).
     * Independiente de red: basta con end_time en SharedPreferences.
     */
    fun hasWatchableSession(): Boolean = getSessionInfo() != null

    /**
     * Mantener FGS/watchdog vivos: sesión local activa o expirada pendiente de bloqueo.
     * Tras "Detener" no hay sesión → false (el cliente puede quedar cerrado).
     */
    fun shouldKeepAlive(): Boolean = setupComplete && hasWatchableSession()

    fun getAlertThresholds(): List<Int> {
        val raw = prefs.getString(KEY_ALERT_THRESHOLDS, null) ?: return DEFAULT_ALERT_THRESHOLDS
        return try {
            JSONArray(raw).let { arr ->
                (0 until arr.length()).map { arr.getInt(it) }.sortedDescending()
            }
        } catch (_: Exception) {
            DEFAULT_ALERT_THRESHOLDS
        }
    }

    fun setAlertThresholds(thresholds: List<Int>) {
        val arr = JSONArray()
        thresholds.forEach { arr.put(it) }
        prefs.edit().putString(KEY_ALERT_THRESHOLDS, arr.toString()).apply()
    }

    fun saveSession(timeLimitSeconds: Int, startTimeIso: String, endTimeIso: String) {
        // commit(): debe quedar en disco antes de un kill OEM / cierre desde recientes
        prefs.edit()
            .putInt(KEY_TIME_LIMIT, timeLimitSeconds)
            .putString(KEY_START_TIME, startTimeIso)
            .putString(KEY_END_TIME, endTimeIso)
            .commit()
        notifyChanged()
    }

    fun clearSession() {
        prefs.edit()
            .remove(KEY_TIME_LIMIT)
            .remove(KEY_START_TIME)
            .remove(KEY_END_TIME)
            .remove(KEY_INET_TIME_LIMIT)
            .remove(KEY_INET_START_TIME)
            .remove(KEY_INET_END_TIME)
            .commit()
        notifyChanged()
    }

    var networkFilterEnabled: Boolean
        get() = prefs.getBoolean(KEY_NETWORK_FILTER, false)
        set(value) {
            prefs.edit().putBoolean(KEY_NETWORK_FILTER, value).apply()
        }

    var internetRequestEnabled: Boolean
        get() = prefs.getBoolean(KEY_INTERNET_REQUEST, false)
        set(value) {
            prefs.edit().putBoolean(KEY_INTERNET_REQUEST, value).apply()
        }

    fun getAllowlist(): List<String> {
        val raw = prefs.getString(KEY_ALLOWLIST, null) ?: return emptyList()
        return try {
            JSONArray(raw).let { arr ->
                (0 until arr.length()).mapNotNull { i ->
                    arr.optString(i)?.trim()?.lowercase()?.takeIf { it.isNotBlank() }
                }
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    fun setAllowlist(entries: List<String>) {
        val arr = JSONArray()
        entries.map { it.trim().lowercase() }.filter { it.isNotBlank() }.distinct().forEach { arr.put(it) }
        prefs.edit().putString(KEY_ALLOWLIST, arr.toString()).apply()
    }

    fun getAllowlistLearned(): List<String> {
        val raw = prefs.getString(KEY_ALLOWLIST_LEARNED, null) ?: return emptyList()
        return try {
            val parsed = JSONArray(raw).let { arr ->
                (0 until arr.length()).mapNotNull { i ->
                    arr.optString(i)?.trim()?.lowercase()?.takeIf { it.isNotBlank() }
                }
            }
            val clean = com.cibermonday.client.net.AllowlistDomains.sanitizeLearned(parsed)
            if (clean != parsed) setAllowlistLearned(clean)
            clean
        } catch (_: Exception) {
            emptyList()
        }
    }

    fun setAllowlistLearned(entries: List<String>) {
        val clean = com.cibermonday.client.net.AllowlistDomains.sanitizeLearned(entries)
        val arr = JSONArray()
        clean.forEach { arr.put(it) }
        prefs.edit().putString(KEY_ALLOWLIST_LEARNED, arr.toString()).apply()
    }

    /** Agrega host related (scan o refinamiento bajo known; oculto en UI). */
    fun addAllowlistLearned(apex: String): Boolean {
        val target = com.cibermonday.client.net.AllowlistDomains.relatedLearnTarget(apex)
            ?: com.cibermonday.client.net.AllowlistDomains.sanitizeLearned(listOf(apex)).firstOrNull()
            ?: return false
        val cur = getAllowlistLearned()
        if (target in cur) return false
        val next = cur + target
        setAllowlistLearned(if (next.size > 300) next.takeLast(300) else next)
        notifyChanged()
        return true
    }

    /** Fusiona hosts del scan HTML de subrecursos. */
    fun mergeAllowlistLearned(hosts: List<String>): Boolean {
        if (hosts.isEmpty()) return false
        val cur = getAllowlistLearned()
        val next = com.cibermonday.client.net.AllowlistDomains.sanitizeLearned(cur + hosts)
        if (next == cur) return false
        setAllowlistLearned(if (next.size > 300) next.takeLast(300) else next)
        notifyChanged()
        return true
    }

    fun effectiveAllowlist(): List<String> = getAllowlist() + getAllowlistLearned()

    var configUpdatedAt: String?
        get() = prefs.getString(KEY_CONFIG_UPDATED_AT, null)
        set(value) {
            val ed = prefs.edit()
            if (value.isNullOrBlank()) ed.remove(KEY_CONFIG_UPDATED_AT)
            else ed.putString(KEY_CONFIG_UPDATED_AT, value)
            ed.apply()
        }

    fun saveInternetSession(timeLimitSeconds: Int, startTimeIso: String, endTimeIso: String) {
        prefs.edit()
            .putInt(KEY_INET_TIME_LIMIT, timeLimitSeconds)
            .putString(KEY_INET_START_TIME, startTimeIso)
            .putString(KEY_INET_END_TIME, endTimeIso)
            .commit()
        notifyChanged()
    }

    fun clearInternetSession() {
        prefs.edit()
            .remove(KEY_INET_TIME_LIMIT)
            .remove(KEY_INET_START_TIME)
            .remove(KEY_INET_END_TIME)
            .commit()
        notifyChanged()
    }

    fun getInternetSession(): SessionData? {
        val limit = prefs.getInt(KEY_INET_TIME_LIMIT, -1)
        val start = prefs.getString(KEY_INET_START_TIME, null)
        val end = prefs.getString(KEY_INET_END_TIME, null)
        if (limit < 0 || start.isNullOrBlank() || end.isNullOrBlank()) return null
        return SessionData(limit, start, end)
    }

    fun getInternetSessionInfo(): SessionInfo? {
        val session = getInternetSession() ?: return null
        return try {
            val endMs = Instant.parse(normalizeIso(session.endTimeIso)).toEpochMilli()
            val remaining = ((endMs - System.currentTimeMillis()) / 1000L).toInt().coerceAtLeast(0)
            SessionInfo(
                remainingSeconds = remaining,
                isExpired = remaining <= 0,
                timeLimitSeconds = session.timeLimitSeconds
            )
        } catch (_: Exception) {
            null
        }
    }

    fun applyInternetFromPush(timeLimitSeconds: Int, remainingSeconds: Int) {
        val now = Instant.now()
        val rem = remainingSeconds.coerceAtLeast(0)
        val end = now.plusSeconds(rem.toLong())
        val start = now.minusSeconds((timeLimitSeconds - rem).toLong().coerceAtLeast(0))
        saveInternetSession(timeLimitSeconds.coerceAtLeast(rem), start.toString(), end.toString())
    }

    /**
     * unrestricted | allowlist | always_allowed_only
     */
    fun computeNetworkPolicyMode(): String {
        val info = getSessionInfo()
        val deviceActive = info != null && !info.isExpired && info.remainingSeconds > 0
        if (!deviceActive) return MODE_UNRESTRICTED

        val inet = getInternetSessionInfo()
        if (inet != null && inet.remainingSeconds <= 0) return MODE_ALWAYS_ALLOWED

        if (networkFilterEnabled) return MODE_ALLOWLIST
        return MODE_UNRESTRICTED
    }

    fun getSession(): SessionData? {
        val limit = prefs.getInt(KEY_TIME_LIMIT, -1)
        val start = prefs.getString(KEY_START_TIME, null)
        val end = prefs.getString(KEY_END_TIME, null)
        if (limit <= 0 || start.isNullOrBlank() || end.isNullOrBlank()) return null
        return SessionData(limit, start, end)
    }

    fun getSessionInfo(): SessionInfo? {
        val session = getSession() ?: return null
        return try {
            val endMs = endTimeMillis(session) ?: return null
            val remaining = ((endMs - System.currentTimeMillis()) / 1000L).toInt()
            SessionInfo(
                remainingSeconds = remaining,
                isExpired = remaining <= 0,
                timeLimitSeconds = session.timeLimitSeconds
            )
        } catch (_: Exception) {
            null
        }
    }

    fun endTimeMillis(): Long? {
        val session = getSession() ?: return null
        return endTimeMillis(session)
    }

    private fun endTimeMillis(session: SessionData): Long? {
        return try {
            Instant.parse(normalizeIso(session.endTimeIso)).toEpochMilli()
        } catch (_: Exception) {
            null
        }
    }

    fun applySessionFromPush(timeLimitSeconds: Int, remainingSeconds: Int) {
        // Antes de saveSession (que notifica listeners): habilitar vigilancia
        // para que no se cancelen las alarmas de expiry/watchdog.
        serviceEnabled = true
        val now = Instant.now()
        val end = now.plusSeconds(remainingSeconds.toLong())
        val start = now.minusSeconds((timeLimitSeconds - remainingSeconds).toLong().coerceAtLeast(0))
        saveSession(timeLimitSeconds, start.toString(), end.toString())
    }

    fun loadServers(): MutableList<ServerEntry> {
        val raw = prefs.getString(KEY_SERVERS, null) ?: return mutableListOf()
        return try {
            val arr = JSONArray(raw)
            MutableList(arr.length()) { i ->
                val obj = arr.getJSONObject(i)
                ServerEntry(
                    url = obj.getString("url").trimEnd('/'),
                    lastSeen = obj.optString("last_seen", Instant.now().toString()),
                    timeoutCount = obj.optInt("timeout_count", 0)
                )
            }
        } catch (_: Exception) {
            mutableListOf()
        }
    }

    fun saveServers(servers: List<ServerEntry>) {
        val arr = JSONArray()
        servers.forEach { s ->
            arr.put(
                JSONObject()
                    .put("url", s.url.trimEnd('/'))
                    .put("last_seen", s.lastSeen)
                    .put("timeout_count", s.timeoutCount)
            )
        }
        prefs.edit().putString(KEY_SERVERS, arr.toString()).apply()
    }

    fun addServer(url: String) {
        val normalized = url.trim().trimEnd('/')
        if (normalized.isBlank()) return
        val servers = loadServers()
        val existing = servers.find { it.url == normalized }
        if (existing != null) {
            existing.lastSeen = Instant.now().toString()
            existing.timeoutCount = 0
        } else {
            servers.add(ServerEntry(normalized))
        }
        saveServers(servers)
    }

    fun mergeServers(received: List<Map<String, Any?>>) {
        val servers = loadServers()
        val byUrl = servers.associateBy { it.url }.toMutableMap()
        received.forEach { srv ->
            val url = (srv["url"] as? String)?.trim()?.trimEnd('/') ?: return@forEach
            val existing = byUrl[url]
            if (existing != null) {
                existing.lastSeen = Instant.now().toString()
                existing.timeoutCount = 0
            } else {
                byUrl[url] = ServerEntry(url)
            }
        }
        saveServers(byUrl.values.toList())
    }

    fun incrementServerTimeouts(failedUrls: List<String>) {
        if (failedUrls.isEmpty()) return
        val max = maxServerTimeouts
        val primary = serverUrl.trimEnd('/')
        val servers = loadServers()
        val remaining = servers.mapNotNull { server ->
            if (server.url in failedUrls) {
                server.timeoutCount += 1
                // Nunca borrar el servidor primario configurado (p.ej. web caído temporalmente)
                if (server.timeoutCount >= max && server.url != primary) null else server
            } else {
                server
            }
        }
        saveServers(remaining)
    }

    fun markServerOk(url: String) {
        val servers = loadServers()
        servers.find { it.url == url.trimEnd('/') }?.let {
            it.lastSeen = Instant.now().toString()
            it.timeoutCount = 0
            saveServers(servers)
        }
    }

    fun applyServerConfig(config: Map<String, Any?>) {
        (config["sync_interval"] as? Number)?.toInt()?.let { syncInterval = it }
        (config["lock_recheck_interval"] as? Number)?.toInt()?.let { lockRecheckInterval = it }
        (config["max_server_timeouts"] as? Number)?.toInt()?.let { maxServerTimeouts = it }
        (config["custom_name"] as? String)?.let { customName = it }
        @Suppress("UNCHECKED_CAST")
        (config["alert_thresholds"] as? List<*>)?.mapNotNull { (it as? Number)?.toInt() }?.let {
            if (it.isNotEmpty()) setAlertThresholds(it)
        }
        (config["network_filter_enabled"] as? Boolean)?.let { networkFilterEnabled = it }
        (config["internet_request_enabled"] as? Boolean)?.let { internetRequestEnabled = it }
        @Suppress("UNCHECKED_CAST")
        (config["allowlist"] as? List<*>)?.mapNotNull { it as? String }?.let { setAllowlist(it) }
        (config["allowlist_learned"] as? List<*>)?.mapNotNull { it as? String }?.let { remote ->
            val merged = (getAllowlistLearned() + remote.map { it.trim().lowercase() }.filter { it.isNotBlank() })
                .distinct()
            setAllowlistLearned(merged)
        }
        (config["config_updated_at"] as? String)?.takeIf { it.isNotBlank() }?.let { configUpdatedAt = it }
        notifyChanged()
    }

    private fun normalizeIso(value: String): String {
        // Python isoformat may lack Z; Instant.parse needs offset or Z
        return when {
            value.endsWith("Z") || value.contains("+") || Regex(".*-\\d{2}:\\d{2}$").matches(value) -> value
            value.contains(".") -> value + "Z"
            else -> value + "Z"
        }
    }

    companion object {
        const val PREFS_NAME = "cibermonday_client"
        const val DEFAULT_SERVER_URL = "http://192.168.1.38:5000"
        const val DEFAULT_SYNC_INTERVAL = 30
        const val DEFAULT_LOCK_RECHECK = 1
        const val DEFAULT_MAX_TIMEOUTS = 10
        val DEFAULT_ALERT_THRESHOLDS = listOf(600, 300, 120, 60)

        private const val KEY_CLIENT_ID = "client_id"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_CUSTOM_NAME = "custom_name"
        private const val KEY_SYNC_INTERVAL = "sync_interval"
        private const val KEY_LOCK_RECHECK = "lock_recheck_interval"
        private const val KEY_MAX_TIMEOUTS = "max_server_timeouts"
        private const val KEY_ALERT_THRESHOLDS = "alert_thresholds"
        private const val KEY_SETUP_COMPLETE = "setup_complete"
        private const val KEY_SERVICE_ENABLED = "service_enabled"
        private const val KEY_VPN_CONSENT_NEEDED = "vpn_consent_needed"
        private const val KEY_VPN_CONSENT_GRANTED = "vpn_consent_granted"
        private const val KEY_TIME_LIMIT = "time_limit_seconds"
        private const val KEY_START_TIME = "start_time"
        private const val KEY_END_TIME = "end_time"
        private const val KEY_SERVERS = "known_servers"
        private const val KEY_NETWORK_FILTER = "network_filter_enabled"
        private const val KEY_INTERNET_REQUEST = "internet_request_enabled"
        private const val KEY_ALLOWLIST = "allowlist"
        private const val KEY_ALLOWLIST_LEARNED = "allowlist_learned"
        private const val KEY_CONFIG_UPDATED_AT = "config_updated_at"
        private const val KEY_INET_TIME_LIMIT = "internet_time_limit_seconds"
        private const val KEY_INET_START_TIME = "internet_start_time"
        private const val KEY_INET_END_TIME = "internet_end_time"

        const val MODE_UNRESTRICTED = "unrestricted"
        const val MODE_ALLOWLIST = "allowlist"
        const val MODE_ALWAYS_ALLOWED = "always_allowed_only"
    }
}
