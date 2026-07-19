package com.cibermonday.client.lock

import android.accessibilityservice.AccessibilityService
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.service.ClientService
import com.cibermonday.client.service.SessionAlarmScheduler

/**
 * Vigila ventanas y re-bloquea si la sesión expiró.
 * Incluye un check periódico suave (solo con pantalla encendida).
 */
class LockAccessibilityService : AccessibilityService() {

    private lateinit var lockController: LockController
    private var lastEnforceMs = 0L
    private var unlockReceiver: UnlockReceiver? = null
    private val handler = Handler(Looper.getMainLooper())
    private val softWatch = object : Runnable {
        override fun run() {
            try {
                if (::lockController.isInitialized && lockController.isLockNeeded()) {
                    ClientService.start(this@LockAccessibilityService, enable = true)
                    if (lockController.isScreenInteractive()) {
                        lockController.enforceLock()
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "softWatch: ${e.message}")
            }
            handler.postDelayed(this, 3_000L)
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
            if (store != null) {
                if (lockController.isLockNeeded()) {
                    store.serviceEnabled = true
                }
                if (store.serviceEnabled || lockController.isLockNeeded()) {
                    SessionAlarmScheduler.rescheduleAll(this, store)
                    ClientService.start(this, enable = lockController.isLockNeeded())
                }
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
