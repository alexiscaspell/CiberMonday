package com.cibermonday.client.net

import android.app.Notification
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.IpPrefix
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.R
import com.cibermonday.client.session.SessionStore
import com.cibermonday.client.ui.StatusActivity
import java.io.FileInputStream
import java.net.InetAddress
import java.util.concurrent.atomic.AtomicBoolean

/**
 * VPN local sin servidor remoto (CGNAT-safe).
 *
 * - Esta app se excluye del túnel → sync/push al servidor CiberMonday siguen.
 * - Se enrutan rangos públicos al VPN; LAN (RFC1918) queda fuera → siempre accesible.
 * - Paquetes capturados se descartan (corte de internet).
 * - En allowlist (API 33+): se excluyen IPs resueltas del allowlist del túnel
 *   para que esos destinos usen la red normal. En APIs viejas el allowlist
 *   actúa como corte total de internet público (más estricto).
 */
class NetworkFilterVpnService : VpnService() {

    private val running = AtomicBoolean(false)
    private var tunInterface: ParcelFileDescriptor? = null
    private var worker: Thread? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopFilter()
                stopSelf()
                return START_NOT_STICKY
            }
            else -> startFilter()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopFilter()
        super.onDestroy()
    }

    private fun startFilter() {
        if (!running.compareAndSet(false, true)) return
        startForeground(NOTIFICATION_ID, buildNotification())
        try {
            val store = CiberMondayApp.instance.store
            val mode = store.computeNetworkPolicyMode()
            val builder = Builder()
                .setSession("CiberMonday Filter")
                .setMtu(1500)
                .addAddress("10.255.0.2", 32)

            // Enrutar internet público (dejar LAN fuera del túnel)
            addPublicRoutes(builder)

            try {
                builder.addDisallowedApplication(packageName)
            } catch (_: Exception) {
            }

            // API 33+: excluir allowlist del túnel para acceso completo a esos destinos
            if (mode == SessionStore.MODE_ALLOWLIST && Build.VERSION.SDK_INT >= 33) {
                for (ip in resolveAllowlistIps(store)) {
                    try {
                        val addr = InetAddress.getByName(ip)
                        if (addr.address.size == 4) {
                            builder.excludeRoute(IpPrefix(addr, 32))
                        }
                    } catch (_: Exception) {
                    }
                }
            }

            tunInterface = builder.establish()
            if (tunInterface == null) {
                Log.e(TAG, "VPN establish() null — ¿permiso VPN?")
                running.set(false)
                stopSelf()
                return
            }
            worker = Thread({ dropLoop() }, "cm-vpn-drop").also {
                it.isDaemon = true
                it.start()
            }
            Log.i(TAG, "Filter VPN on mode=$mode")
        } catch (e: Exception) {
            Log.e(TAG, "startFilter: ${e.message}")
            running.set(false)
            stopSelf()
        }
    }

    private fun stopFilter() {
        running.set(false)
        try {
            worker?.interrupt()
        } catch (_: Exception) {
        }
        worker = null
        try {
            tunInterface?.close()
        } catch (_: Exception) {
        }
        tunInterface = null
        Log.i(TAG, "Filter VPN off")
    }

    /** Lee y descarta — tráfico público capturado no sale. */
    private fun dropLoop() {
        val tun = tunInterface ?: return
        val input = FileInputStream(tun.fileDescriptor)
        val buf = ByteArray(32767)
        while (running.get()) {
            try {
                val n = input.read(buf)
                if (n < 0) break
                // drop
            } catch (_: InterruptedException) {
                break
            } catch (e: Exception) {
                if (running.get()) Log.d(TAG, "dropLoop: ${e.message}")
            }
        }
    }

    private fun buildNotification(): Notification {
        val open = Intent(this, StatusActivity::class.java)
        val pending = PendingIntent.getActivity(
            this, 0, open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CiberMondayApp.CHANNEL_SERVICE)
            .setContentTitle("CiberMonday")
            .setContentText("Filtro de internet activo")
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentIntent(pending)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "NetworkFilterVpn"
        private const val NOTIFICATION_ID = 42
        const val ACTION_STOP = "com.cibermonday.client.STOP_NET_FILTER"

        fun syncWithPolicy(context: Context) {
            val store = CiberMondayApp.instance.store
            val needVpn = store.computeNetworkPolicyMode() != SessionStore.MODE_UNRESTRICTED
            val app = context.applicationContext
            if (needVpn) {
                val prep = prepare(app)
                if (prep != null) {
                    store.vpnConsentNeeded = true
                    Log.i(TAG, "VPN consent required")
                    return
                }
                store.vpnConsentNeeded = false
                val i = Intent(app, NetworkFilterVpnService::class.java)
                if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(i)
                else app.startService(i)
            } else {
                app.startService(
                    Intent(app, NetworkFilterVpnService::class.java).setAction(ACTION_STOP)
                )
            }
        }

        private fun addPublicRoutes(builder: Builder) {
            // Rangos públicos aproximados (excluye 10/8, 127/8, 169.254/16, 172.16/12, 192.168/16)
            for (cidr in listOf(
                "0.0.0.0/5", "8.0.0.0/7", "11.0.0.0/8", "12.0.0.0/6", "16.0.0.0/4",
                "32.0.0.0/3", "64.0.0.0/2", "128.0.0.0/3", "160.0.0.0/5",
                "168.0.0.0/6", "172.0.0.0/12", "172.32.0.0/11", "172.64.0.0/10",
                "172.128.0.0/9", "173.0.0.0/8", "174.0.0.0/7", "176.0.0.0/4",
                "192.0.0.0/9", "192.128.0.0/11", "192.160.0.0/13", "192.169.0.0/16",
                "192.170.0.0/15", "192.172.0.0/14", "192.176.0.0/12", "192.192.0.0/10",
                "193.0.0.0/8", "194.0.0.0/7", "196.0.0.0/6", "200.0.0.0/5", "208.0.0.0/4"
            )) {
                // 172.0.0.0/12 overlaps private 172.16/12 — skip and use neighbors only
                if (cidr == "172.0.0.0/12") continue
                try {
                    val (ip, prefix) = cidr.split("/", limit = 2)
                    builder.addRoute(ip, prefix.toInt())
                } catch (_: Exception) {
                }
            }
        }

        private fun resolveAllowlistIps(store: SessionStore): Set<String> {
            val out = linkedSetOf<String>()
            for (entry in store.getAllowlist()) {
                val e = entry.trim().lowercase()
                if (e.isBlank()) continue
                if (e.contains("/")) continue
                if (e.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) {
                    out.add(e)
                    continue
                }
                val host = if (e.startsWith("*.")) e.substring(2) else e
                try {
                    InetAddress.getAllByName(host).forEach { addr ->
                        if (addr.address.size == 4) out.add(addr.hostAddress ?: return@forEach)
                    }
                } catch (_: Exception) {
                }
            }
            return out
        }
    }
}
