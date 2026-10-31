package com.cibermonday.client.net

import android.app.Notification
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.IpPrefix
import android.net.ProxyInfo
import android.net.VpnService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.R
import com.cibermonday.client.session.SessionStore
import com.cibermonday.client.ui.StatusActivity
import java.io.FileInputStream
import java.net.InetAddress
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import com.cibermonday.client.util.AppLog

/**
 * VPN local (CGNAT-safe) + hostname gate.
 *
 * Allowlist: HTTP CONNECT proxy local decide por nombre (SNI/CONNECT), no por IP.
 * Así clients4.google.com puede pasar y google.com no, aunque compartan edge.
 * Apps nativas allowlist (YouTube, …) salen del túnel vía addDisallowedApplication.
 */
class NetworkFilterVpnService : VpnService() {

    private val running = AtomicBoolean(false)
    private var tunInterface: ParcelFileDescriptor? = null
    private var worker: Thread? = null
    private var resolverThread: Thread? = null
    private var activeFingerprint: String? = null
    private var activeMode: String? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var rebuildScheduled = false
    private var hostProxy: HostnameProxy? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                tearDown()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_REBUILD -> {
                val store = CiberMondayApp.instance.store
                if (!hasActiveTimedSession(store)) {
                    stopVpn(this)
                    return START_NOT_STICKY
                }
                val mode = store.computeNetworkPolicyMode()
                activeFingerprint = null
                ensureTunnel(mode, policyFingerprint(store, mode) + "|ips:${seededIps.size}")
                return START_STICKY
            }
            else -> {
                val mode = intent?.getStringExtra(EXTRA_MODE)
                    ?: CiberMondayApp.instance.store.computeNetworkPolicyMode()
                val fingerprint = intent?.getStringExtra(EXTRA_FINGERPRINT)
                    ?: policyFingerprint(CiberMondayApp.instance.store, mode)
                ensureTunnel(mode, fingerprint)
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        tearDown()
        super.onDestroy()
    }

    private fun ensureTunnel(mode: String, fingerprint: String) {
        if (running.get() && activeFingerprint == fingerprint) {
            try {
                startForeground(NOTIFICATION_ID, buildNotification(mode))
            } catch (_: Exception) {
            }
            return
        }

        // Resolver allowlist ANTES de bajar el túnel viejo (DNS sigue vivo).
        val store = CiberMondayApp.instance.store
        if (mode == SessionStore.MODE_ALLOWLIST) {
            refreshSeedIps(store)
        }

        if (running.get()) {
            tearDown()
        }
        if (!running.compareAndSet(false, true)) return

        startForeground(NOTIFICATION_ID, buildNotification(mode))
        try {
            val builder = Builder()
                .setSession("CiberMonday")
                .setMtu(1500)
                .addAddress(VPN_ADDR, 32)

            try {
                builder.addDisallowedApplication(packageName)
            } catch (_: Exception) {
            }

            when (mode) {
                SessionStore.MODE_UNRESTRICTED -> {
                    builder.addRoute("198.18.0.1", 32)
                }
                else -> {
                    if (Build.VERSION.SDK_INT >= 33) {
                        builder.addRoute("0.0.0.0", 0)
                        for (cidr in PRIVATE_V4) {
                            excludeIpPrefix(builder, cidr)
                        }
                        // Private DNS / resolvers públicos — si se capturan, no hay DNS
                        for (dns in PUBLIC_DNS) {
                            excludeIpPrefix(builder, "$dns/32")
                        }
                        // No excluir IPs allowlist: el name-gate es el proxy CONNECT.
                        // Tráfico directo al edge compartido cae al TUN y se descarta.
                        if (mode == SessionStore.MODE_ALLOWLIST) {
                            if (Build.VERSION.SDK_INT >= 29) {
                                builder.setHttpProxy(
                                    ProxyInfo.buildDirectProxy("127.0.0.1", HOST_PROXY_PORT)
                                )
                            }
                            for (pkg in relatedPackages(store)) {
                                try {
                                    builder.addDisallowedApplication(pkg)
                                } catch (_: Exception) {
                                }
                            }
                        }
                    } else {
                        addPublicRoutes(builder)
                    }
                }
            }

            tunInterface = builder.establish()
            if (tunInterface == null) {
                AppLog.e(TAG, "VPN establish() null — ¿permiso VPN?")
                running.set(false)
                activeFingerprint = null
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return
            }
            activeFingerprint = fingerprint
            activeMode = mode
            worker = Thread({ drainLoop() }, "cm-vpn-drain").also {
                it.isDaemon = true
                it.start()
            }
            if (mode == SessionStore.MODE_ALLOWLIST) {
                startHostProxy(store)
                startResolverLoop()
                maybeDiscoverRelated(store)
            } else {
                discoverFpDone = null
            }
            AppLog.i(TAG, "VPN ready mode=$mode hostProxy=${mode == SessionStore.MODE_ALLOWLIST}")
        } catch (e: Exception) {
            AppLog.e(TAG, "ensureTunnel: ${e.message}", e)
            running.set(false)
            activeFingerprint = null
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun excludeIpPrefix(builder: Builder, cidr: String) {
        try {
            val (ip, prefix) = cidr.split("/", limit = 2)
            val addr = InetAddress.getByName(ip)
            if (addr.address.size == 4) {
                builder.excludeRoute(IpPrefix(addr, prefix.toInt()))
            }
        } catch (_: Exception) {
        }
    }

    private fun tearDown() {
        running.set(false)
        activeFingerprint = null
        activeMode = null
        try {
            hostProxy?.stop()
        } catch (_: Exception) {
        }
        hostProxy = null
        try {
            worker?.interrupt()
        } catch (_: Exception) {
        }
        worker = null
        try {
            resolverThread?.interrupt()
        } catch (_: Exception) {
        }
        resolverThread = null
        try {
            tunInterface?.close()
        } catch (_: Exception) {
        }
        tunInterface = null
        AppLog.i(TAG, "VPN torn down")
    }

    private fun startHostProxy(store: SessionStore) {
        try {
            hostProxy?.stop()
        } catch (_: Exception) {
        }
        hostProxy = HostnameProxy(
            port = HOST_PROXY_PORT,
            isAllowed = { host ->
                val explicit = store.getAllowlist()
                val learned = store.getAllowlistLearned()
                var ok = AllowlistDomains.hostAllowed(host, explicit, learned)
                AllowlistDomains.liveLearnTarget(host, explicit, learned)?.let { target ->
                    store.addAllowlistLearned(target)
                    ok = true
                }
                ok
            },
            onDenied = { host ->
                if (store.internetRequestEnabled && store.networkFilterEnabled) {
                    try {
                        ApiClient(store).reportAccessRequest(host)
                    } catch (_: Exception) {
                    }
                }
            },
            protect = { sock ->
                try {
                    protect(sock)
                } catch (_: Exception) {
                }
            },
        ).also { it.start() }
    }

    private fun drainLoop() {
        val tun = tunInterface ?: return
        val input = FileInputStream(tun.fileDescriptor)
        val buf = ByteArray(32767)
        val store = CiberMondayApp.instance.store
        while (running.get()) {
            try {
                val n = input.read(buf)
                if (n < 0) break
                if (activeMode == SessionStore.MODE_ALLOWLIST && n > 40) {
                    maybeLearnFromPacket(buf, n, store)
                }
            } catch (_: InterruptedException) {
                break
            } catch (e: Exception) {
                if (running.get()) AppLog.d(TAG, "drainLoop: ${e.message}")
            }
        }
    }

    /** SNI learning: allowlist + related del tráfico (implícito). */
    private fun maybeLearnFromPacket(buf: ByteArray, n: Int, store: SessionStore) {
        try {
            if ((buf[0].toInt() ushr 4) != 4) return // solo IPv4
            val ihl = (buf[0].toInt() and 0x0f) * 4
            if (n < ihl + 20) return
            if (buf[9].toInt() and 0xff != 6) return // TCP
            val dest = "${buf[16].toInt() and 0xff}.${buf[17].toInt() and 0xff}." +
                "${buf[18].toInt() and 0xff}.${buf[19].toInt() and 0xff}"
            if (seededIps.contains(dest)) return
            val dataOff = ihl + ((buf[ihl + 12].toInt() ushr 4) and 0x0f) * 4
            if (dataOff + 6 >= n) return
            // TLS record: Handshake (22)
            if (buf[dataOff].toInt() and 0xff != 0x16) return
            val hs = dataOff + 5
            if (hs >= n || (buf[hs].toInt() and 0xff) != 0x01) return // ClientHello
            val sni = extractSni(buf, hs, n) ?: return
            val explicit = store.getAllowlist()
            val learned = store.getAllowlistLearned()
            val matchesExplicit = AllowlistDomains.matchesExplicit(sni, explicit)
            var allowed = matchesExplicit || AllowlistDomains.hostAllowed(sni, explicit, learned)
            val learnTarget = AllowlistDomains.liveLearnTarget(sni, explicit, learned)
            if (learnTarget != null) {
                if (store.addAllowlistLearned(learnTarget)) {
                    AppLog.i(TAG, "related learned $learnTarget (from $sni)")
                }
                allowed = true
            }
            if (!allowed) {
                if (store.internetRequestEnabled && store.networkFilterEnabled) {
                    try {
                        ApiClient(store).reportAccessRequest(sni)
                    } catch (_: Exception) {
                    }
                }
                return
            }
            // Name-gate via CONNECT proxy; no excluir IP (evitar abrir google.com
            // en el mismo edge). Solo log / related learning.
            AppLog.i(TAG, "SNI seen $sni → $dest (proxy name-gate; no IP exclude)")
        } catch (_: Exception) {
        }
    }

    private fun extractSni(buf: ByteArray, hs: Int, n: Int): String? {
        // Handshake header 4 bytes + ClientHello body
        if (hs + 38 >= n) return null
        var p = hs + 4 // skip handshake hdr
        p += 2 // client_version
        p += 32 // random
        if (p >= n) return null
        val sessionLen = buf[p].toInt() and 0xff
        p += 1 + sessionLen
        if (p + 2 > n) return null
        val csLen = ((buf[p].toInt() and 0xff) shl 8) or (buf[p + 1].toInt() and 0xff)
        p += 2 + csLen
        if (p >= n) return null
        val compLen = buf[p].toInt() and 0xff
        p += 1 + compLen
        if (p + 2 > n) return null
        val extLen = ((buf[p].toInt() and 0xff) shl 8) or (buf[p + 1].toInt() and 0xff)
        p += 2
        val extEnd = (p + extLen).coerceAtMost(n)
        while (p + 4 <= extEnd) {
            val typ = ((buf[p].toInt() and 0xff) shl 8) or (buf[p + 1].toInt() and 0xff)
            val len = ((buf[p + 2].toInt() and 0xff) shl 8) or (buf[p + 3].toInt() and 0xff)
            p += 4
            if (p + len > extEnd) break
            if (typ == 0 && len >= 5) { // server_name
                var q = p + 2 // skip list length
                val nameType = buf[q].toInt() and 0xff
                q += 1
                if (nameType != 0 || q + 2 > p + len) break
                val nameLen = ((buf[q].toInt() and 0xff) shl 8) or (buf[q + 1].toInt() and 0xff)
                q += 2
                if (q + nameLen > p + len) break
                return String(buf, q, nameLen, Charsets.US_ASCII).lowercase()
            }
            p += len
        }
        return null
    }

    private fun startResolverLoop() {
        resolverThread = Thread({
            var first = true
            while (running.get() && activeMode == SessionStore.MODE_ALLOWLIST) {
                try {
                    Thread.sleep(if (first) 5_000 else 20_000)
                    first = false
                    if (!running.get()) break
                    val before = seededIps.toSet()
                    refreshSeedIps(CiberMondayApp.instance.store)
                    if (seededIps != before) {
                        AppLog.i(TAG, "Allowlist IPs changed ${before.size}→${seededIps.size}, rebuild")
                        scheduleRebuild()
                    }
                } catch (_: InterruptedException) {
                    break
                } catch (e: Exception) {
                    AppLog.d(TAG, "resolver: ${e.message}")
                }
            }
        }, "cm-vpn-resolve").also {
            it.isDaemon = true
            it.start()
        }
    }

    private fun scheduleRebuild() {
        if (rebuildScheduled) return
        rebuildScheduled = true
        mainHandler.postDelayed({
            rebuildScheduled = false
            if (!running.get()) return@postDelayed
            if (activeMode != SessionStore.MODE_ALLOWLIST) return@postDelayed
            val app = applicationContext
            val i = Intent(app, NetworkFilterVpnService::class.java).setAction(ACTION_REBUILD)
            if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(i)
            else app.startService(i)
        }, 500)
    }

    private fun buildNotification(mode: String): Notification {
        val open = Intent(this, StatusActivity::class.java)
        val pending = PendingIntent.getActivity(
            this, 0, open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val text = when (mode) {
            SessionStore.MODE_UNRESTRICTED -> "VPN listo (internet normal)"
            SessionStore.MODE_ALWAYS_ALLOWED -> "Internet cortado (solo LAN/servidor)"
            SessionStore.MODE_ALLOWLIST -> "Filtro allowlist activo"
            else -> "VPN activo"
        }
        return NotificationCompat.Builder(this, CiberMondayApp.CHANNEL_SERVICE)
            .setContentTitle("CiberMonday")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentIntent(pending)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "NetworkFilterVpn"
        private const val NOTIFICATION_ID = 42
        private const val CONSENT_NOTIFICATION_ID = 43
        private const val VPN_ADDR = "10.255.0.2"
        private const val HOST_PROXY_PORT = 18080
        const val ACTION_STOP = "com.cibermonday.client.STOP_NET_FILTER"
        const val ACTION_REBUILD = "com.cibermonday.client.REBUILD_NET_FILTER"
        const val EXTRA_MODE = "mode"
        const val EXTRA_FINGERPRINT = "fingerprint"
        const val EXTRA_REQUEST_VPN = "request_vpn"

        private val PRIVATE_V4 = listOf(
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "127.0.0.0/8",
            "169.254.0.0/16",
        )

        /** Resolvers / Private DNS — deben quedar fuera del túnel o no hay DNS. */
        private val PUBLIC_DNS = listOf(
            "8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1",
            "9.9.9.9", "149.112.112.112", "208.67.222.222", "208.67.220.220"
        )

        private val seededIps = ConcurrentHashMap.newKeySet<String>()
        @Volatile private var discoverFpDone: String? = null

        fun hasActiveTimedSession(store: SessionStore): Boolean {
            val info = store.getSessionInfo() ?: return false
            return !info.isExpired && info.remainingSeconds > 0
        }

        fun needsVpnPreparation(store: SessionStore): Boolean = hasActiveTimedSession(store)

        private fun policyFingerprint(store: SessionStore, mode: String): String {
            val allow = if (mode == SessionStore.MODE_ALLOWLIST) {
                store.effectiveAllowlist().sorted().joinToString(",")
            } else ""
            return "$mode|$allow"
        }

        fun syncWithPolicy(context: Context) {
            val store = CiberMondayApp.instance.store
            val app = context.applicationContext

            if (!hasActiveTimedSession(store)) {
                store.vpnConsentNeeded = false
                cancelConsentNotification(app)
                seededIps.clear()
                stopVpn(app)
                AppLog.i(TAG, "No active timed session — VPN off")
                return
            }

            val mode = store.computeNetworkPolicyMode()
            if (mode != SessionStore.MODE_ALLOWLIST) {
                seededIps.clear()
            }
            val fingerprint = policyFingerprint(store, mode)

            val prep = prepare(app)
            if (prep != null) {
                store.vpnConsentNeeded = true
                store.vpnConsentGranted = false
                AppLog.i(TAG, "VPN consent required (want mode=$mode)")
                postConsentNotification(app)
                return
            }
            store.vpnConsentNeeded = false
            store.vpnConsentGranted = true
            cancelConsentNotification(app)

            val i = Intent(app, NetworkFilterVpnService::class.java)
                .putExtra(EXTRA_MODE, mode)
                .putExtra(EXTRA_FINGERPRINT, fingerprint)
            if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(i)
            else app.startService(i)
        }

        fun stopVpn(context: Context) {
            val app = context.applicationContext
            try {
                app.startService(
                    Intent(app, NetworkFilterVpnService::class.java).setAction(ACTION_STOP)
                )
            } catch (e: Exception) {
                AppLog.w(TAG, "stopVpn: ${e.message}")
            }
        }

        private fun refreshSeedIps(store: SessionStore) {
            for (entry in AllowlistDomains.expand(store.effectiveAllowlist())) {
                if (entry.contains("/")) continue
                if (entry.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) {
                    seededIps.add(entry)
                    continue
                }
                if (entry.startsWith("*.")) continue
                try {
                    InetAddress.getAllByName(entry).forEach { addr ->
                        if (addr.address.size == 4) {
                            seededIps.add(addr.hostAddress ?: return@forEach)
                        }
                    }
                } catch (_: Exception) {
                }
            }
        }

        private fun maybeDiscoverRelated(store: SessionStore) {
            val allow = store.getAllowlist()
            val fp = allow.map { it.trim().lowercase() }.filter { it.isNotBlank() }.sorted().joinToString("|")
            if (fp.isBlank() || fp == discoverFpDone) return
            AllowlistDiscover.discoverAsync(allow) { hosts ->
                if (hosts.isEmpty()) return@discoverAsync
                discoverFpDone = fp
                if (!store.mergeAllowlistLearned(hosts)) return@discoverAsync
                AppLog.i(TAG, "discover merged ${hosts.size} related")
                val before = seededIps.toSet()
                refreshSeedIps(store)
                if (seededIps != before) {
                    // Rebuild tunnel so new CDN IPs are excluded
                    try {
                        val app = CiberMondayApp.instance
                        val i = Intent(app, NetworkFilterVpnService::class.java).setAction(ACTION_REBUILD)
                        if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(i)
                        else app.startService(i)
                    } catch (e: Exception) {
                        AppLog.w(TAG, "discover rebuild: ${e.message}")
                    }
                }
            }
        }

        private fun relatedPackages(store: SessionStore): List<String> {
            val expanded = AllowlistDomains.expand(store.effectiveAllowlist())
            val pkgs = mutableListOf<String>()
            if (expanded.any { it.contains("youtube") || it == "youtu.be" || it.contains("googlevideo") }) {
                pkgs += listOf(
                    "com.google.android.youtube",
                    "com.google.android.apps.youtube.kids",
                    "com.google.android.apps.youtube.music"
                )
            }
            if (expanded.any { it.contains("netflix") }) pkgs += "com.netflix.mediaclient"
            if (expanded.any { it.contains("instagram") }) pkgs += "com.instagram.android"
            if (expanded.any { it.contains("tiktok") }) {
                pkgs += listOf("com.zhiliaoapp.musically", "com.ss.android.ugc.trill")
            }
            return pkgs
        }

        private fun postConsentNotification(context: Context) {
            val open = Intent(context, StatusActivity::class.java)
                .putExtra(EXTRA_REQUEST_VPN, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            val pending = PendingIntent.getActivity(
                context, 1, open,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val notification = NotificationCompat.Builder(context, CiberMondayApp.CHANNEL_ALERTS)
                .setContentTitle("CiberMonday")
                .setContentText("Tocá para permitir VPN (control de internet)")
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentIntent(pending)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .build()
            try {
                NotificationManagerCompat.from(context).notify(CONSENT_NOTIFICATION_ID, notification)
            } catch (e: Exception) {
                AppLog.w(TAG, "consent notify: ${e.message}")
            }
        }

        private fun cancelConsentNotification(context: Context) {
            try {
                NotificationManagerCompat.from(context).cancel(CONSENT_NOTIFICATION_ID)
            } catch (_: Exception) {
            }
        }

        private fun addPublicRoutes(builder: Builder) {
            for (cidr in listOf(
                "0.0.0.0/5", "8.0.0.0/7", "11.0.0.0/8", "12.0.0.0/6", "16.0.0.0/4",
                "32.0.0.0/3", "64.0.0.0/2", "128.0.0.0/3", "160.0.0.0/5",
                "168.0.0.0/6", "172.0.0.0/12", "172.32.0.0/11", "172.64.0.0/10",
                "172.128.0.0/9", "173.0.0.0/8", "174.0.0.0/7", "176.0.0.0/4",
                "192.0.0.0/9", "192.128.0.0/11", "192.160.0.0/13", "192.169.0.0/16",
                "192.170.0.0/15", "192.172.0.0/14", "192.176.0.0/12", "192.192.0.0/10",
                "193.0.0.0/8", "194.0.0.0/7", "196.0.0.0/6", "200.0.0.0/5", "208.0.0.0/4"
            )) {
                if (cidr == "172.0.0.0/12") continue
                try {
                    val (ip, prefix) = cidr.split("/", limit = 2)
                    builder.addRoute(ip, prefix.toInt())
                } catch (_: Exception) {
                }
            }
        }
    }
}
