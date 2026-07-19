package com.cibermonday.client.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.R
import com.cibermonday.client.lock.LockController
import com.cibermonday.client.lock.UnlockReceiver
import com.cibermonday.client.net.ApiClient
import com.cibermonday.client.net.DiscoveryListener
import com.cibermonday.client.net.PushServer
import com.cibermonday.client.session.SessionStore
import com.cibermonday.client.ui.StatusActivity
import java.util.concurrent.atomic.AtomicBoolean

class ClientService : Service() {

    private lateinit var store: SessionStore
    private lateinit var api: ApiClient
    private lateinit var lockController: LockController
    private var discovery: DiscoveryListener? = null
    private var pushServer: PushServer? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var unlockReceiver: UnlockReceiver? = null

    private val running = AtomicBoolean(false)
    private var monitorThread: Thread? = null
    private var syncThread: Thread? = null

    private var lastRemaining: Int? = null
    private val alertsShown = mutableMapOf<Int, Boolean>()
    private var registered = false

    override fun onCreate() {
        super.onCreate()
        store = CiberMondayApp.instance.store
        api = ApiClient(store)
        lockController = LockController(this)
        acquireWakeLock()
        acquireWifiLock()
        registerUnlockReceiver()
        SessionAlarmScheduler.rescheduleAll(this, store)
        store.addListener(sessionListener)
    }

    private val sessionListener: () -> Unit = {
        if (store.serviceEnabled) {
            SessionAlarmScheduler.rescheduleAll(this, store)
            handleSessionStateChange()
        } else {
            SessionAlarmScheduler.cancelAll(this)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_SHUTDOWN) {
            shutdownAfterAdminStop()
            return START_NOT_STICKY
        }
        // No reactivar serviceEnabled aquí: solo Setup/Status o push de sesión nueva
        if (!store.serviceEnabled && !lockController.isLockNeeded()) {
            Log.i(TAG, "Start ignored — service disabled and no lock needed")
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(NOTIFICATION_ID, buildServiceNotification("Iniciando…"))
        SessionAlarmScheduler.rescheduleAll(this, store)
        if (running.compareAndSet(false, true)) {
            startNetworking()
            startMonitorLoop()
            startSyncLoop()
            handleSessionStateChange()
        } else {
            handleSessionStateChange()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        if (!store.serviceEnabled) return
        Log.w(TAG, "Task removed — scheduling restart")
        SessionAlarmScheduler.rescheduleAll(this, store)
        if (store.setupComplete) {
            start(this)
        }
    }

    override fun onDestroy() {
        running.set(false)
        try {
            store.removeListener(sessionListener)
        } catch (_: Exception) {
        }
        unregisterUnlockReceiver()
        discovery?.stop()
        pushServer?.stopServer()
        releaseWakeLock()
        releaseWifiLock()
        // Solo reprogramar watchdog si el admin no apagó el cliente a propósito
        if (store.serviceEnabled && store.setupComplete) {
            SessionAlarmScheduler.scheduleWatchdog(this, true)
        } else {
            SessionAlarmScheduler.cancelAll(this)
        }
        super.onDestroy()
    }

    private fun registerUnlockReceiver() {
        if (unlockReceiver != null) return
        unlockReceiver = UnlockReceiver()
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_USER_PRESENT)
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_SCREEN_OFF)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                addAction(Intent.ACTION_USER_UNLOCKED)
            }
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                registerReceiver(unlockReceiver, filter, RECEIVER_NOT_EXPORTED)
            } else {
                registerReceiver(unlockReceiver, filter)
            }
        } catch (e: Exception) {
            Log.w(TAG, "registerUnlockReceiver: ${e.message}")
        }
    }

    private fun unregisterUnlockReceiver() {
        try {
            unlockReceiver?.let { unregisterReceiver(it) }
        } catch (_: Exception) {
        }
        unlockReceiver = null
    }

    private fun startNetworking() {
        discovery = DiscoveryListener(this, store).also { it.start(continuous = true) }
        pushServer = PushServer(
            store = store,
            api = api,
            onSessionChanged = {
                handleSessionStateChange()
                updateNotification()
            },
            onStoppedByAdmin = {
                // Dar tiempo a responder el HTTP del push stop
                android.os.Handler(mainLooper).postDelayed({
                    shutdownAfterAdminStop()
                }, 400L)
            }
        ).also { it.startServer() }
    }

    /**
     * Admin detuvo la sesión: apagar servicio, alarmas y locks (ahorro de batería).
     * Para volver a usar: abrir la app en el teléfono y luego asignar tiempo.
     */
    private fun shutdownAfterAdminStop() {
        Log.i(TAG, "Admin stop — full client shutdown")
        store.serviceEnabled = false
        running.set(false)
        lockController.dismissLockIfNeeded()
        SessionAlarmScheduler.cancelAll(this)
        try {
            store.removeListener(sessionListener)
        } catch (_: Exception) {
        }
        unregisterUnlockReceiver()
        discovery?.stop()
        discovery = null
        pushServer?.stopServer()
        pushServer = null
        releaseWakeLock()
        releaseWifiLock()
        try {
            NotificationManagerCompat.from(this).cancel(NOTIFICATION_ID)
            NotificationManagerCompat.from(this).cancel(ALERT_NOTIFICATION_ID)
        } catch (_: Exception) {
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
        stopSelf()
    }

    private fun startMonitorLoop() {
        monitorThread = Thread({
            Log.i(TAG, "Monitor loop started")
            while (running.get()) {
                try {
                    val info = store.getSessionInfo()
                    if (info == null) {
                        if (lastRemaining != null) {
                            lastRemaining = null
                            alertsShown.clear()
                            lockController.dismissLockIfNeeded()
                            updateNotification("Esperando sesión")
                        }
                        Thread.sleep(1000)
                        continue
                    }

                    val remaining = info.remainingSeconds
                    val expired = info.isExpired || remaining <= 0

                    if (lastRemaining == null) {
                        resetAlerts(remaining)
                    }

                    if (expired) {
                        val firstExpiry = lastRemaining == null || (lastRemaining ?: 0) > 0
                        if (firstExpiry) {
                            Log.i(TAG, "Session expired — lock screen off")
                            // Sin notificación heads-up: despertaría la pantalla
                            lockController.lockWorkstation(forceSystemLock = true)
                            releaseWifiLock()
                        } else if (lockController.isScreenInteractive()) {
                            lockController.enforceLock()
                        } else {
                            // Pantalla apagada: bajo consumo
                            releaseWifiLock()
                            lockController.onScreenOff()
                        }
                        lastRemaining = remaining
                        updateNotification("Tiempo agotado")
                        Thread.sleep(10_000L)
                        continue
                    }

                    // Sesión activa: asegurar Wi‑Fi para sync
                    if (wifiLock?.isHeld != true) {
                        acquireWifiLock()
                    }

                    // Sesión válida (p.ej. push o pull): quitar bloqueo
                    lockController.dismissLockIfNeeded()
                    checkAlerts(remaining)
                    if (lastRemaining != remaining) {
                        lastRemaining = remaining
                        updateNotification(formatTime(remaining))
                    }
                    Thread.sleep(1000)
                } catch (e: InterruptedException) {
                    break
                } catch (e: Exception) {
                    Log.e(TAG, "Monitor error: ${e.message}")
                    Thread.sleep(1000)
                }
            }
        }, "client-monitor").also { it.isDaemon = true; it.start() }
    }

    private fun startSyncLoop() {
        syncThread = Thread({
            Log.i(TAG, "Sync loop started")
            while (running.get()) {
                try {
                    val clientId = store.ensureClientId()
                    if (!registered) {
                        val id = api.register(existingClientId = clientId)
                        registered = id != null
                        if (registered) {
                            Log.i(TAG, "Registered as ${id?.take(8)}…")
                            updateNotification()
                        }
                    } else {
                        if (api.syncAllServers(clientId)) {
                            Log.i(TAG, "Adopted session from server sync")
                            handleSessionStateChange()
                        }
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "Sync error: ${e.message}")
                    registered = false
                }
                val info = store.getSessionInfo()
                val expired = info == null || info.isExpired || info.remainingSeconds <= 0
                val base = store.syncInterval.coerceIn(5, 300)
                // Expirado + pantalla off: sync lento (batería); si hay sesión activa, ritmo normal
                val interval = when {
                    expired && !lockController.isScreenInteractive() -> maxOf(base, 60) * 1000L
                    expired -> minOf(base, 15) * 1000L
                    else -> base * 1000L
                }
                var slept = 0L
                while (running.get() && slept < interval) {
                    Thread.sleep(1000)
                    slept += 1000
                }
            }
        }, "client-sync").also { it.isDaemon = true; it.start() }
    }

    private fun handleSessionStateChange() {
        val info = store.getSessionInfo()
        if (info == null) {
            lastRemaining = null
            alertsShown.clear()
            lockController.dismissLockIfNeeded()
        } else if (info.isExpired || info.remainingSeconds <= 0) {
            lockController.lockWorkstation(forceSystemLock = true)
        } else {
            resetAlerts(info.remainingSeconds)
            lastRemaining = info.remainingSeconds
            lockController.dismissLockIfNeeded()
        }
        updateNotification()
    }

    private fun resetAlerts(remaining: Int) {
        store.getAlertThresholds().forEach { threshold ->
            alertsShown[threshold] = remaining <= threshold
        }
    }

    private fun checkAlerts(remaining: Int) {
        val previous = lastRemaining
        if (previous != null && previous - remaining > 120) {
            resetAlerts(remaining)
        }
        store.getAlertThresholds().forEach { threshold ->
            if (remaining <= threshold && alertsShown[threshold] != true) {
                alertsShown[threshold] = true
                val msg = when (threshold) {
                    600 -> "Quedan 10 minutos"
                    300 -> "Quedan 5 minutos"
                    120 -> "Quedan 2 minutos"
                    60 -> "Queda 1 minuto"
                    else -> "Quedan ${formatTime(remaining)}"
                }
                showAlertNotification("Tiempo restante", msg)
            }
        }
    }

    private fun updateNotification(text: String? = null) {
        val body = text ?: run {
            val info = store.getSessionInfo()
            when {
                info == null -> "Esperando sesión"
                info.isExpired || info.remainingSeconds <= 0 -> "Tiempo agotado"
                else -> formatTime(info.remainingSeconds)
            }
        }
        val notification = buildServiceNotification(body)
        NotificationManagerCompat.from(this).notify(NOTIFICATION_ID, notification)
    }

    private fun buildServiceNotification(content: String): Notification {
        val open = Intent(this, StatusActivity::class.java)
        val pending = PendingIntent.getActivity(
            this,
            0,
            open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CiberMondayApp.CHANNEL_SERVICE)
            .setContentTitle(getString(R.string.notification_running))
            .setContentText(content)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentIntent(pending)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun showAlertNotification(title: String, message: String) {
        val notification = NotificationCompat.Builder(this, CiberMondayApp.CHANNEL_ALERTS)
            .setContentTitle(title)
            .setContentText(message)
            .setSmallIcon(R.drawable.ic_launcher)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(this).notify(ALERT_NOTIFICATION_ID, notification)
    }

    private fun acquireWakeLock() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CiberMonday:Client").apply {
            setReferenceCounted(false)
            acquire(10 * 60 * 60 * 1000L) // up to 10h; refreshed by sticky service
        }
    }

    private fun releaseWakeLock() {
        try {
            if (wakeLock?.isHeld == true) wakeLock?.release()
        } catch (_: Exception) {
        }
        wakeLock = null
    }

    @Suppress("DEPRECATION")
    private fun acquireWifiLock() {
        try {
            val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "CiberMonday:Wifi").apply {
                setReferenceCounted(false)
                acquire()
            }
            Log.i(TAG, "WifiLock acquired")
        } catch (e: Exception) {
            Log.w(TAG, "WifiLock failed: ${e.message}")
        }
    }

    private fun releaseWifiLock() {
        try {
            if (wifiLock?.isHeld == true) wifiLock?.release()
        } catch (_: Exception) {
        }
        wifiLock = null
    }

    companion object {
        private const val TAG = "ClientService"
        private const val NOTIFICATION_ID = 1001
        private const val ALERT_NOTIFICATION_ID = 1002
        const val ACTION_SHUTDOWN = "com.cibermonday.client.SHUTDOWN"

        fun formatTime(totalSeconds: Int): String {
            val s = totalSeconds.coerceAtLeast(0)
            val h = s / 3600
            val m = (s % 3600) / 60
            val sec = s % 60
            return if (h > 0) {
                String.format("%d:%02d:%02d", h, m, sec)
            } else {
                String.format("%02d:%02d", m, sec)
            }
        }

        fun start(context: Context, enable: Boolean = false) {
            val app = try {
                CiberMondayApp.instance
            } catch (_: Exception) {
                null
            }
            if (app != null) {
                if (enable) {
                    app.store.serviceEnabled = true
                } else if (!app.store.serviceEnabled) {
                    val info = app.store.getSessionInfo()
                    val needsLock = info != null && (info.isExpired || info.remainingSeconds <= 0)
                    if (!needsLock) {
                        Log.i(TAG, "Skip start — disabled by admin stop")
                        return
                    }
                }
            }
            val intent = Intent(context, ClientService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }
}
