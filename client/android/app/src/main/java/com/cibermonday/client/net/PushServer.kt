package com.cibermonday.client.net

import com.cibermonday.client.session.SessionStore
import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import com.cibermonday.client.util.AppLog

class PushServer(
    private val store: SessionStore,
    private val api: ApiClient,
    port: Int = ApiClient.DIAGNOSTIC_PORT,
    private val onSessionChanged: () -> Unit,
    private val onStoppedByAdmin: (() -> Unit)? = null
) : NanoHTTPD(port) {

    private val started = AtomicBoolean(false)

    fun startServer() {
        if (!started.compareAndSet(false, true)) return
        try {
            start(SOCKET_READ_TIMEOUT, false)
            AppLog.i(TAG, "Push server listening on :$listeningPort")
        } catch (e: Exception) {
            started.set(false)
            AppLog.e(TAG, "Failed to start push server: ${e.message}")
        }
    }

    fun stopServer() {
        if (!started.get()) return
        try {
            stop()
        } catch (_: Exception) {
        }
        started.set(false)
    }

    override fun serve(session: IHTTPSession): Response {
        val path = session.uri.substringBefore('?')
        return try {
            when {
                session.method == Method.GET && path == "/api/status" -> json(statusPayload())
                session.method == Method.GET && path == "/api/diagnostic" -> json(diagnosticPayload())
                session.method == Method.GET && path == "/api/logs" -> json(logsPayload(session))
                session.method == Method.GET && path == "/api/servers" -> json(serversPayload())
                session.method == Method.POST && path == "/api/push/session" -> handlePushSession(session)
                session.method == Method.POST && path == "/api/push/config" -> handlePushConfig(session)
                session.method == Method.POST && path == "/api/push/stop" -> handlePushStop()
                session.method == Method.POST && path == "/api/push/internet" -> handlePushInternet(session)
                session.method == Method.GET && path == "/" -> newFixedLengthResponse(
                    Response.Status.OK,
                    "text/plain",
                    "CiberMonday Android Client"
                )
                else -> json(JSONObject().put("error", "Not found"), Response.Status.NOT_FOUND)
            }
        } catch (e: Exception) {
            AppLog.e(TAG, "Request error: ${e.message}")
            json(JSONObject().put("success", false).put("message", e.message), Response.Status.INTERNAL_ERROR)
        }
    }

    private fun handlePushSession(session: IHTTPSession): Response {
        val data = readJsonBody(session) ?: return json(
            JSONObject().put("success", false).put("message", "No data"),
            Response.Status.BAD_REQUEST
        )
        val tl = data.optInt("time_limit_seconds", 0)
        val rem = data.optInt("remaining_seconds", 0)
        if (tl <= 0 || rem <= 0) {
            return json(
                JSONObject().put("success", false).put("message", "Datos incompletos"),
                Response.Status.BAD_REQUEST
            )
        }
        // applySessionFromPush ya pone serviceEnabled=true y persiste end_time local
        store.applySessionFromPush(tl, rem)
        AppLog.i(TAG, "Push session: ${rem}s remaining (${tl}s total)")
        onSessionChanged()
        propagateAsync()
        return json(JSONObject().put("success", true).put("message", "Sesión actualizada: ${rem}s restantes"))
    }

    private fun handlePushConfig(session: IHTTPSession): Response {
        val data = readJsonBody(session) ?: return json(
            JSONObject().put("success", false).put("message", "No data"),
            Response.Status.BAD_REQUEST
        )
        store.applyServerConfig(ApiClient.jsonObjectToMap(data))
        AppLog.i(TAG, "Push config received")
        onSessionChanged()
        propagateAsync()
        return json(JSONObject().put("success", true).put("message", "Configuración actualizada"))
    }

    private fun handlePushStop(): Response {
        store.serviceEnabled = false
        store.clearSession()
        store.clearInternetSession()
        AppLog.i(TAG, "Push stop: session cleared — shutting down client")
        onSessionChanged()
        onStoppedByAdmin?.invoke()
        // No sync/reportZero: renovaría last_seen y el panel seguiría en "conectado"
        return json(JSONObject().put("success", true).put("message", "Sesión detenida"))
    }

    private fun handlePushInternet(session: IHTTPSession): Response {
        val data = readJsonBody(session) ?: return json(
            JSONObject().put("success", false).put("message", "No data"),
            Response.Status.BAD_REQUEST
        )
        if (data.optBoolean("cleared", false)) {
            store.clearInternetSession()
            AppLog.i(TAG, "Push internet cleared")
            onSessionChanged()
            propagateAsync()
            return json(JSONObject().put("success", true).put("message", "Internet detenido"))
        }
        val tl = data.optInt("time_limit_seconds", 0)
        val rem = data.optInt("remaining_seconds", 0).coerceAtLeast(0)
        if (tl < 0) {
            return json(
                JSONObject().put("success", false).put("message", "Datos incompletos"),
                Response.Status.BAD_REQUEST
            )
        }
        store.applyInternetFromPush(if (tl > 0) tl else rem, rem)
        AppLog.i(TAG, "Push internet: ${rem}s remaining")
        onSessionChanged()
        propagateAsync()
        return json(JSONObject().put("success", true).put("message", "Internet actualizado: ${rem}s"))
    }

    private fun propagateAsync() {
        Thread({
            val clientId = store.clientId ?: return@Thread
            api.syncAllServers(clientId)
        }, "push-propagate").start()
    }

    private fun statusPayload(): JSONObject {
        val info = store.getSessionInfo()
        return JSONObject()
            .put("client_id", store.clientId)
            .put("platform", "android")
            .put("server_url", store.serverUrl)
            .put("has_session", info != null)
            .put("remaining_seconds", info?.remainingSeconds ?: 0)
            .put("is_expired", info?.isExpired ?: false)
            .put("local_ip", ApiClient.localIpAddress())
    }

    private fun diagnosticPayload(): JSONObject {
        val tail = AppLog.tail(40)
        return statusPayload()
            .put("sync_interval", store.syncInterval)
            .put("lock_recheck_interval", store.lockRecheckInterval)
            .put("known_servers", ApiClient.serversToJson(store.loadServers()))
            .put("log_path", AppLog.path())
            .put("log_tail", org.json.JSONArray(tail))
    }

    private fun logsPayload(session: IHTTPSession): JSONObject {
        val linesParam = session.parms["lines"]?.toIntOrNull() ?: 120
        val lines = AppLog.tail(linesParam)
        return JSONObject()
            .put("success", true)
            .put("path", AppLog.path())
            .put("lines", org.json.JSONArray(lines))
            .put("count", lines.size)
    }

    private fun serversPayload(): JSONObject {
        return JSONObject().put("servers", ApiClient.serversToJson(store.loadServers()))
    }

    private fun readJsonBody(session: IHTTPSession): JSONObject? {
        val files = HashMap<String, String>()
        session.parseBody(files)
        val raw = files["postData"] ?: return null
        if (raw.isBlank()) return null
        return JSONObject(raw)
    }

    private fun json(obj: JSONObject, status: Response.Status = Response.Status.OK): Response {
        val response = newFixedLengthResponse(status, "application/json", obj.toString())
        response.addHeader("Access-Control-Allow-Origin", "*")
        return response
    }

    companion object {
        private const val TAG = "PushServer"
    }
}
