package com.cibermonday.client.net

import android.os.Build
import com.cibermonday.client.session.SessionStore
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import java.util.Collections

class ApiClient(private val store: SessionStore) {

    fun register(serverUrl: String? = null, existingClientId: String? = null): String? {
        val target = (serverUrl ?: findAvailableServer()) ?: return null
        val clientId = existingClientId ?: store.ensureClientId()
        val body = JSONObject().apply {
            put("name", store.customName ?: deviceName())
            put("client_id", clientId)
            put("client_ip", localIpAddress() ?: JSONObject.NULL)
            put("diagnostic_port", DIAGNOSTIC_PORT)
            put("platform", "android")
            store.getSessionInfo()?.let { info ->
                if (!info.isExpired && info.remainingSeconds > 0) {
                    put(
                        "session",
                        JSONObject()
                            .put("remaining_seconds", info.remainingSeconds)
                            .put("time_limit_seconds", info.timeLimitSeconds)
                    )
                }
            }
            put(
                "config",
                JSONObject()
                    .put("sync_interval", store.syncInterval)
                    .put("alert_thresholds", JSONArray(store.getAlertThresholds()))
                    .put("custom_name", store.customName ?: JSONObject.NULL)
            )
            put("known_servers", serversToJson(store.loadServers()))
        }

        val response = postJson("$target/api/register", body) ?: return null
        if (response.code != 201) return null
        val json = response.json ?: return null
        val newId = json.optString("client_id", clientId)
        store.clientId = newId
        store.markServerOk(target)
        store.serverUrl = target

        val known = json.optJSONArray("known_servers")
        if (known != null) {
            store.mergeServers(jsonArrayToMaps(known))
        }
        val config = json.optJSONObject("config")
        if (config != null) {
            store.applyServerConfig(jsonObjectToMap(config))
        }
        return newId
    }

    fun reportSession(clientId: String, serverUrl: String? = null): Boolean {
        val info = store.getSessionInfo() ?: return false
        if (info.isExpired || info.remainingSeconds <= 0) return false
        val session = store.getSession() ?: return false
        val target = serverUrl ?: findAvailableServer() ?: return false
        val body = JSONObject()
            .put("remaining_seconds", info.remainingSeconds)
            .put("time_limit_seconds", session.timeLimitSeconds)
        val response = postJson("$target/api/client/$clientId/report-session", body) ?: return false
        if (response.code == 200) {
            store.markServerOk(target)
            return true
        }
        if (response.code == 404) {
            register(target, clientId)
        }
        return false
    }

    fun reportZero(clientId: String, serverUrl: String): Boolean {
        val session = store.getSession()
        val body = JSONObject()
            .put("remaining_seconds", 0)
            .put("time_limit_seconds", session?.timeLimitSeconds ?: 0)
        val response = postJson("$serverUrl/api/client/$clientId/report-session", body) ?: return false
        if (response.code != 200) return false
        store.markServerOk(serverUrl)
        // Si el admin ya asignó tiempo nuevo, el servidor lo devuelve aquí
        adoptSessionFromJson(response.json?.optJSONObject("session"))
        return true
    }

    /**
     * Consulta el estado en el servidor y adopta la sesión si hay tiempo restante
     * (fallback cuando el push a :5002 falló tras el bloqueo).
     * @return true si se aplicó una sesión nueva
     */
    fun pullSession(clientId: String, serverUrl: String): Boolean {
        return try {
            val conn = openGet("$serverUrl/api/client/$clientId/status")
            val code = conn.responseCode
            val text = if (code in 200..299) {
                conn.inputStream?.bufferedReader()?.use(BufferedReader::readText)
            } else null
            conn.disconnect()
            if (code != 200 || text.isNullOrBlank()) return false
            store.markServerOk(serverUrl)
            val json = JSONObject(text)
            adoptSessionFromJson(json.optJSONObject("session"))
        } catch (_: Exception) {
            false
        }
    }

    fun health(serverUrl: String): Boolean {
        return try {
            val conn = openGet("$serverUrl/api/health")
            val code = conn.responseCode
            conn.disconnect()
            code == 200
        } catch (_: Exception) {
            false
        }
    }

    fun findAvailableServer(): String? {
        val candidates = linkedSetOf<String>()
        val primary = store.serverUrl
        if (primary.isNotBlank()) candidates.add(primary.trimEnd('/'))
        store.loadServers().forEach { candidates.add(it.url) }

        val failed = mutableListOf<String>()
        for (url in candidates) {
            if (health(url)) {
                store.markServerOk(url)
                return url
            }
            failed.add(url)
        }
        store.incrementServerTimeouts(failed)
        return null
    }

    /**
     * Sync con servidores. @return true si se adoptó una sesión nueva del servidor.
     */
    fun syncAllServers(clientId: String): Boolean {
        val servers = store.loadServers().map { it.url }.toMutableSet()
        servers.add(store.serverUrl.trimEnd('/'))
        val failed = mutableListOf<String>()
        val before = store.getSessionInfo()?.remainingSeconds ?: -1
        val info = store.getSessionInfo()
        val localExpired = info == null || info.isExpired || info.remainingSeconds <= 0
        for (url in servers) {
            if (url.isBlank()) continue
            try {
                if (!health(url)) {
                    failed.add(url)
                    continue
                }
                if (!localExpired && info != null && info.remainingSeconds > 0) {
                    if (!reportSession(clientId, url)) failed.add(url)
                } else {
                    if (!reportZero(clientId, url)) failed.add(url)
                    pullSession(clientId, url)
                }
            } catch (_: Exception) {
                failed.add(url)
            }
        }
        store.incrementServerTimeouts(failed)
        val after = store.getSessionInfo()?.remainingSeconds ?: -1
        return after > 0 && after != before
    }

    /** @return true si se aplicó una sesión con remaining > 0 */
    private fun adoptSessionFromJson(session: JSONObject?): Boolean {
        if (session == null) return false
        val remaining = session.optInt("remaining_seconds", 0)
        if (remaining <= 0) return false
        val timeLimit = session.optInt("time_limit_seconds", remaining)
        val local = store.getSessionInfo()
        if (local != null && !local.isExpired && local.remainingSeconds > 0) {
            if (remaining <= local.remainingSeconds + 2) return false
        }
        store.applySessionFromPush(timeLimit, remaining)
        return true
    }

    private data class HttpResponse(val code: Int, val json: JSONObject?)

    private fun postJson(url: String, body: JSONObject): HttpResponse? {
        return try {
            val conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8_000
                readTimeout = 8_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("Accept", "application/json")
            }
            OutputStreamWriter(conn.outputStream).use { it.write(body.toString()) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use(BufferedReader::readText)
            conn.disconnect()
            HttpResponse(code, text?.let { JSONObject(it) })
        } catch (_: Exception) {
            null
        }
    }

    private fun openGet(url: String): HttpURLConnection {
        return (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 5_000
            readTimeout = 5_000
            setRequestProperty("Accept", "application/json")
        }
    }

    companion object {
        const val DIAGNOSTIC_PORT = 5002

        fun deviceName(): String {
            val model = Build.MODEL ?: "Android"
            val manufacturer = Build.MANUFACTURER ?: ""
            return if (model.startsWith(manufacturer, ignoreCase = true)) {
                model
            } else {
                "$manufacturer $model".trim()
            }
        }

        fun localIpAddress(): String? {
            return try {
                Collections.list(NetworkInterface.getNetworkInterfaces()).flatMap { ni ->
                    Collections.list(ni.inetAddresses)
                }.firstOrNull { addr ->
                    !addr.isLoopbackAddress && addr is Inet4Address
                }?.hostAddress
            } catch (_: Exception) {
                null
            }
        }

        fun serversToJson(servers: List<com.cibermonday.client.session.ServerEntry>): JSONArray {
            val arr = JSONArray()
            servers.forEach { s ->
                arr.put(
                    JSONObject()
                        .put("url", s.url)
                        .put("last_seen", s.lastSeen)
                        .put("timeout_count", s.timeoutCount)
                )
            }
            return arr
        }

        fun jsonArrayToMaps(arr: JSONArray): List<Map<String, Any?>> {
            return (0 until arr.length()).map { i ->
                val obj = arr.getJSONObject(i)
                obj.keys().asSequence().associateWith { key -> obj.opt(key) }
            }
        }

        fun jsonObjectToMap(obj: JSONObject): Map<String, Any?> {
            val map = mutableMapOf<String, Any?>()
            obj.keys().forEach { key ->
                val value = obj.opt(key)
                map[key] = when (value) {
                    is JSONArray -> (0 until value.length()).map { value.opt(it) }
                    is JSONObject -> jsonObjectToMap(value)
                    JSONObject.NULL -> null
                    else -> value
                }
            }
            return map
        }
    }
}
