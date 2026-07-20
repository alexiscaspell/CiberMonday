package com.cibermonday.client.lock

import android.accessibilityservice.AccessibilityService
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.net.ConnectivityRestorer
import com.cibermonday.client.service.ClientService
import com.cibermonday.client.service.SessionAlarmScheduler

/**
 * Vigila ventanas y re-bloquea si la sesión expiró.
 * Incluye un check periódico suave (solo con pantalla encendida).
 */
class LockAccessibilityService : AccessibilityService() {

    private lateinit var lockController: LockController
    private var lastEnforceMs = 0L
    private var lastNetworkRestoreMs = 0L
    private var unlockReceiver: UnlockReceiver? = null
    private val handler = Handler(Looper.getMainLooper())
    private val softWatch = object : Runnable {
        override fun run() {
            try {
                if (::lockController.isInitialized) {
                    val store = try {
                        CiberMondayApp.instance.store
                    } catch (_: Exception) {
                        null
                    }
                    // Sesión activa offline: reabrir FGS; expirada: re-bloquear
                    if (store != null && store.shouldKeepAlive()) {
                        ClientService.start(this@LockAccessibilityService, enable = true)
                    }
                    if (lockController.isLockNeeded()) {
                        maybeRestoreNetwork()
                        if (lockController.isScreenInteractive()) {
                            lockController.enforceLock()
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "softWatch: ${e.message}")
            }
            handler.postDelayed(this, 3_000L)
        }
    }

    private fun maybeRestoreNetwork() {
        val now = System.currentTimeMillis()
        if (now - lastNetworkRestoreMs < 15_000L) return
        lastNetworkRestoreMs = now
        Thread({
            try {
                if (ConnectivityRestorer.hasUsableNetwork(this)) return@Thread
                ConnectivityRestorer.ensureOnline(this)
                if (!ConnectivityRestorer.hasUsableNetwork(this) &&
                    !ConnectivityRestorer.isWifiEnabled(this) &&
                    lockController.isScreenInteractive()
                ) {
                    handler.post { tryEnableWifiViaQuickSettings() }
                }
            } catch (e: Exception) {
                Log.w(TAG, "maybeRestoreNetwork: ${e.message}")
            }
        }, "cibermonday-net-restore").start()
    }

    /**
     * Fallback OEM: abrir ajustes rápidos y pulsar el tile Wi‑Fi si está apagado.
     * Requiere Accesibilidad (ya activa para el bloqueo).
     */
    private fun tryEnableWifiViaQuickSettings() {
        try {
            if (ConnectivityRestorer.isWifiEnabled(this)) return
            Log.i(TAG, "Trying Wi‑Fi via Quick Settings")
            performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS)
            handler.postDelayed({
                try {
                    clickWifiTileIfOff(rootInActiveWindow)
                    performGlobalAction(GLOBAL_ACTION_BACK)
                } catch (e: Exception) {
                    Log.w(TAG, "QS wifi click: ${e.message}")
                }
            }, 900L)
        } catch (e: Exception) {
            Log.w(TAG, "tryEnableWifiViaQuickSettings: ${e.message}")
        }
    }

    private fun clickWifiTileIfOff(root: AccessibilityNodeInfo?): Boolean {
        if (root == null) return false
        val keywords = listOf(
            "wi-fi", "wifi", "wlan", "wireless", "internet",
            "red", "conexión", "conexion"
        )
        val nodes = ArrayList<AccessibilityNodeInfo>()
        collectClickable(root, nodes)
        for (node in nodes) {
            val text = buildString {
                append(node.text ?: "")
                append(' ')
                append(node.contentDescription ?: "")
                append(' ')
                append(node.viewIdResourceName ?: "")
            }.lowercase()
            if (keywords.none { text.contains(it) }) continue
            // Si parece un switch apagado / tile desactivado, pulsar
            val looksOff = text.contains("off") || text.contains("apagad") ||
                text.contains("desactiv") || !node.isChecked
            if (node.isCheckable && node.isChecked) continue
            if (looksOff || node.isCheckable) {
                Log.i(TAG, "Clicking Wi‑Fi tile: $text")
                node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                return true
            }
        }
        return false
    }

    private fun collectClickable(node: AccessibilityNodeInfo, out: MutableList<AccessibilityNodeInfo>) {
        if (node.isClickable || node.isCheckable) out.add(node)
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            collectClickable(child, out)
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        try {
            lockController = LockController(this)
            instance = this
            Log.i(TAG, "Accessibility service connected")
            registerUnlockReceiver()
            val store = try {
                CiberMondayApp.instance.store
            } catch (_: Exception) {
                null
            }
            if (store != null && store.shouldKeepAlive()) {
                store.serviceEnabled = true
                SessionAlarmScheduler.rescheduleAll(this, store)
                ClientService.start(this, enable = true)
            }
            if (lockController.isLockNeeded()) {
                // Al conectar: imponer bloqueo (pantalla off o UI si ya está encendida)
                lockController.lockWorkstation(forceSystemLock = true)
                if (lockController.isScreenInteractive()) {
                    lockController.onUserUnlocked()
                }
            }
            handler.removeCallbacks(softWatch)
            handler.postDelayed(softWatch, 3_000L)
        } catch (e: Exception) {
            Log.e(TAG, "onServiceConnected failed: ${e.message}", e)
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        try {
            if (event == null) return
            if (event.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
                event.eventType != AccessibilityEvent.TYPE_WINDOWS_CHANGED
            ) {
                return
            }
            if (!::lockController.isInitialized) return
            if (!lockController.isLockNeeded()) return
            if (!lockController.isScreenInteractive()) return

            val pkg = event.packageName?.toString()
            val className = event.className?.toString().orEmpty()
            if (pkg == packageName && className.contains("LockActivity")) return

            val now = System.currentTimeMillis()
            if (now - lastEnforceMs < 1_000L) return
            lastEnforceMs = now

            Log.i(TAG, "Window change while expired ($pkg) — re-locking")
            ClientService.start(this, enable = true)
            lockController.enforceLock()
        } catch (e: Exception) {
            Log.w(TAG, "onAccessibilityEvent: ${e.message}")
        }
    }

    override fun onInterrupt() {
        // no-op
    }

    override fun onDestroy() {
        handler.removeCallbacks(softWatch)
        unregisterUnlockReceiver()
        instance = null
        super.onDestroy()
    }

    private fun registerUnlockReceiver() {
        if (unlockReceiver != null) return
        unlockReceiver = UnlockReceiver()
        val filter = IntentFilter().apply {
            addAction(android.content.Intent.ACTION_USER_PRESENT)
            addAction(android.content.Intent.ACTION_SCREEN_ON)
            addAction(android.content.Intent.ACTION_SCREEN_OFF)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                addAction(android.content.Intent.ACTION_USER_UNLOCKED)
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

    companion object {
        private const val TAG = "LockAccessibility"
        @Volatile
        var instance: LockAccessibilityService? = null
            private set

        fun isRunning(): Boolean = instance != null
    }
}
