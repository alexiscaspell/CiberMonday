package com.cibermonday.client.net

import java.io.BufferedInputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import com.cibermonday.client.util.AppLog

/**
 * Proxy HTTP CONNECT local: decide por hostname (no por IP).
 * clients4.google.com puede pasar y google.com no, aunque compartan edge IP.
 */
class HostnameProxy(
    private val port: Int = 18080,
    private val isAllowed: (String) -> Boolean,
    private val onDenied: ((String) -> Unit)? = null,
    private val protect: ((Socket) -> Unit)? = null,
) {
    private val running = AtomicBoolean(false)
    private var server: ServerSocket? = null
    private val pool = Executors.newCachedThreadPool()

    fun start(): Boolean {
        stop()
        return try {
            val ss = ServerSocket()
            ss.reuseAddress = true
            ss.bind(InetSocketAddress("127.0.0.1", port))
            server = ss
            running.set(true)
            Thread({
                while (running.get()) {
                    try {
                        val client = ss.accept()
                        pool.execute { handle(client) }
                    } catch (_: Exception) {
                        if (!running.get()) break
                    }
                }
            }, "cm-hostproxy").also {
                it.isDaemon = true
                it.start()
            }
            AppLog.i(TAG, "listening 127.0.0.1:$port")
            true
        } catch (e: Exception) {
            AppLog.e(TAG, "start: ${e.message}")
            false
        }
    }

    fun stop() {
        running.set(false)
        try {
            server?.close()
        } catch (_: Exception) {
        }
        server = null
    }

    private fun handle(client: Socket) {
        var remote: Socket? = null
        try {
            client.soTimeout = 15000
            val input = BufferedInputStream(client.getInputStream())
            val header = readHeaders(input) ?: return
            val line = header.lineSequence().firstOrNull() ?: return
            val parts = line.split(" ")
            if (parts.size < 2 || !parts[0].equals("CONNECT", ignoreCase = true)) {
                client.getOutputStream().write(
                    "HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n".toByteArray()
                )
                return
            }
            var host = parts[1]
            var port = 443
            if (":" in host) {
                val idx = host.lastIndexOf(':')
                port = host.substring(idx + 1).toIntOrNull() ?: 443
                host = host.substring(0, idx)
            }
            host = host.trim().trim('[', ']').lowercase()
            if (!isAllowed(host)) {
                AppLog.i(TAG, "DENY $host")
                onDenied?.invoke(host)
                client.getOutputStream().write(
                    "HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n".toByteArray()
                )
                return
            }
            remote = Socket()
            protect?.invoke(remote)
            remote.connect(InetSocketAddress(host, port), 10000)
            client.getOutputStream().write(
                "HTTP/1.1 200 Connection Established\r\n\r\n".toByteArray()
            )
            client.soTimeout = 0
            remote.soTimeout = 0
            val a = client
            val b = remote
            val t = Thread({ pipe(b.getInputStream(), a.getOutputStream()) }, "cm-proxy-up")
            t.isDaemon = true
            t.start()
            pipe(input, b.getOutputStream())
            t.join(1000)
        } catch (e: Exception) {
            AppLog.d(TAG, "handle: ${e.message}")
        } finally {
            try {
                client.close()
            } catch (_: Exception) {
            }
            try {
                remote?.close()
            } catch (_: Exception) {
            }
        }
    }

    private fun readHeaders(input: BufferedInputStream): String? {
        val buf = ByteArray(1)
        val out = StringBuilder()
        while (out.length < 65536) {
            val n = input.read(buf)
            if (n <= 0) return null
            out.append(buf[0].toInt().toChar())
            if (out.endsWith("\r\n\r\n")) break
        }
        return out.toString()
    }

    private fun pipe(input: InputStream, output: OutputStream) {
        val buf = ByteArray(32768)
        try {
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                output.write(buf, 0, n)
                output.flush()
            }
        } catch (_: Exception) {
        }
    }

    companion object {
        private const val TAG = "HostnameProxy"
    }
}
