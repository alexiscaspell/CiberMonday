package com.cibermonday.client.net

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import com.cibermonday.client.session.SessionStore
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.URL
import java.util.Collections
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Escucha broadcasts UDP :5001 y, si no hay resultado, barre la LAN por HTTP /api/health.
 */
class DiscoveryListener(
    private val context: Context,
    private val store: SessionStore,
    private val onServerFound: ((String) -> Unit)? = null,
    private val onStatus: ((String) -> Unit)? = null
) {
    private val running = AtomicBoolean(false)
    private var thread: Thread? = null
    private var socket: DatagramSocket? = null
    private var multicastLock: WifiManager.MulticastLock? = null

    @Volatile
    var lastBroadcastFrom: String? = null
        private set

    @Volatile
    var broadcastCount: Int = 0
        private set

    fun start(timeoutMs: Long = 8_000L, continuous: Boolean = false) {
        if (!running.compareAndSet(false, true)) return
        thread = Thread({
            val found = AtomicReference<String?>(null)
            try {
                acquireMulticastLock()
                if (continuous) {
                    listenUdpForever(found)
                } else {
                    listenUdp(found, timeoutMs)
                    if (found.get() == null && running.get()) {
                        onStatus?.invoke("Sin broadcast UDP. Buscando por HTTP en la LAN…")
                        val httpUrl = scanLanHttp()
                        if (httpUrl != null) {
                            found.set(httpUrl)
                            applyFound(httpUrl, null)
                        }
                    }
                    if (found.get() == null && running.get()) {
                        onStatus?.invoke("No se encontró servidor. Probá ingresar la URL manualmente.")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Discovery failed: ${e.message}")
                onStatus?.invoke("Error de descubrimiento: ${e.message}")
            } finally {
                if (!continuous) {
                    releaseMulticastLock()
                    running.set(false)
                    try {
                        socket?.close()
                    } catch (_: Exception) {
                    }
                    socket = null
                }
            }
        }, "discovery-listener").also { it.isDaemon = true; it.start() }
    }

    private fun listenUdpForever(found: AtomicReference<String?>) {
        val sock = DatagramSocket(null).apply {
            reuseAddress = true
            broadcast = true
            bind(InetSocketAddress(DISCOVERY_PORT))
            soTimeout = 2000
        }
        socket = sock
        Log.i(TAG, "Continuous UDP listen on $DISCOVERY_PORT")
        val buffer = ByteArray(2048)
        while (running.get()) {
            try {
                val packet = DatagramPacket(buffer, buffer.size)
                sock.receive(packet)
                val text = String(packet.data, 0, packet.length, Charsets.UTF_8)
                val url = parsePayload(text, packet.address?.hostAddress) ?: continue
                applyFound(url, packet.address?.hostAddress)
                found.set(url)
            } catch (_: java.net.SocketTimeoutException) {
                // continue
            } catch (e: Exception) {
                if (running.get()) {
                    Log.w(TAG, "UDP receive error: ${e.message}")
                }
            }
        }
        releaseMulticastLock()
        try {
            sock.close()
        } catch (_: Exception) {
        }
    }

    fun stop() {
        running.set(false)
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        socket = null
        releaseMulticastLock()
        thread = null
    }

    private fun listenUdp(found: AtomicReference<String?>, timeoutMs: Long) {
        val sock = DatagramSocket(null).apply {
            reuseAddress = true
            broadcast = true
            bind(InetSocketAddress(DISCOVERY_PORT))
            soTimeout = 500
        }
        socket = sock
        Log.i(TAG, "Listening UDP on $DISCOVERY_PORT")
        onStatus?.invoke("Escuchando UDP $DISCOVERY_PORT…")
        val buffer = ByteArray(2048)
        val deadline = System.currentTimeMillis() + timeoutMs
        while (running.get() && found.get() == null && System.currentTimeMillis() < deadline) {
            try {
                val packet = DatagramPacket(buffer, buffer.size)
                sock.receive(packet)
                val text = String(packet.data, 0, packet.length, Charsets.UTF_8)
                val url = parsePayload(text, packet.address?.hostAddress) ?: continue
                found.set(url)
                applyFound(url, packet.address?.hostAddress)
            } catch (_: java.net.SocketTimeoutException) {
                // keep waiting until deadline
            } catch (e: Exception) {
                if (running.get()) {
                    Log.w(TAG, "UDP receive error: ${e.message}")
                }
            }
        }
    }

    private fun applyFound(url: String, fromIp: String?) {
        broadcastCount += 1
        lastBroadcastFrom = fromIp
        store.addServer(url)
        store.serverUrl = url
        onServerFound?.invoke(url)
        Log.i(TAG, "Discovered server: $url")
    }

    private fun parsePayload(text: String, fromIp: String?): String? {
        return try {
            val json = JSONObject(text)
            val url = json.optString("url").ifBlank {
                val ip = json.optString("ip", fromIp ?: "")
                val port = json.optInt("port", 5000)
                if (ip.isBlank()) return null
                "http://$ip:$port"
            }.trimEnd('/')
            url.ifBlank { null }
        } catch (e: Exception) {
            Log.w(TAG, "Invalid discovery payload: ${e.message}")
            null
        }
    }

    private fun scanLanHttp(): String? {
        val candidates = linkedSetOf<String>()
        val localIp = localIpv4()
        val prefix = localIp?.substringBeforeLast('.')
        val gateway = wifiGatewayIp()

        if (!gateway.isNullOrBlank()) {
            candidates.add("http://$gateway:5000")
        }
        if (prefix != null) {
            // Priorizar IPs típicas de gateway / PC
            listOf(1, 100, 101, 38, 10, 20, 50).forEach { n ->
                candidates.add("http://$prefix.$n:5000")
            }
            for (n in 1..254) {
                candidates.add("http://$prefix.$n:5000")
            }
        }

        val executor = Executors.newFixedThreadPool(24)
        val result = AtomicReference<String?>(null)
        try {
            val futures = candidates.map { base ->
                executor.submit {
                    if (result.get() != null || !running.get()) return@submit
                    if (probeHealth(base)) {
                        result.compareAndSet(null, base)
                    }
                }
            }
            // Esperar hasta ~6s o hasta el primero
            val deadline = System.currentTimeMillis() + 6_000
            while (result.get() == null && running.get() && System.currentTimeMillis() < deadline) {
                Thread.sleep(100)
            }
            futures.forEach { it.cancel(true) }
        } finally {
            executor.shutdownNow()
            executor.awaitTermination(1, TimeUnit.SECONDS)
        }
        return result.get()
    }

    private fun probeHealth(baseUrl: String): Boolean {
        return try {
            val conn = (URL("$baseUrl/api/health").openConnection() as HttpURLConnection).apply {
                connectTimeout = 250
                readTimeout = 250
                requestMethod = "GET"
            }
            val ok = conn.responseCode == 200
            conn.disconnect()
            ok
        } catch (_: Exception) {
            false
        }
    }

    private fun localIpv4(): String? {
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

    @Suppress("DEPRECATION")
    private fun wifiGatewayIp(): String? {
        return try {
            val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            val gateway = wm.dhcpInfo?.gateway ?: return null
            if (gateway == 0) return null
            String.format(
                "%d.%d.%d.%d",
                gateway and 0xff,
                gateway shr 8 and 0xff,
                gateway shr 16 and 0xff,
                gateway shr 24 and 0xff
            )
        } catch (_: Exception) {
            null
        }
    }

    @Suppress("DEPRECATION")
    private fun acquireMulticastLock() {
        try {
            val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            multicastLock = wm.createMulticastLock("cibermonday-discovery").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (e: Exception) {
            Log.w(TAG, "MulticastLock failed: ${e.message}")
        }
    }

    private fun releaseMulticastLock() {
        try {
            if (multicastLock?.isHeld == true) multicastLock?.release()
        } catch (_: Exception) {
        }
        multicastLock = null
    }

    companion object {
        private const val TAG = "DiscoveryListener"
        const val DISCOVERY_PORT = 5001
    }
}
