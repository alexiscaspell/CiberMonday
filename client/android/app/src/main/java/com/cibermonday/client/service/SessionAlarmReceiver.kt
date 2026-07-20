package com.cibermonday.client.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.PowerManager
import android.util.Log
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.lock.LockController

/**
 * Despierta el proceso cuando expira la sesión o el watchdog periódico dispara,
 * aunque el usuario haya cerrado la app desde recientes.
 */
class SessionAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        val appContext = context.applicationContext
        val wakeLock = (appContext.getSystemService(Context.POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CiberMonday:Alarm").apply {
                setReferenceCounted(false)
                acquire(30_000L)
            }
        try {
            val store = try {
                CiberMondayApp.instance.store
            } catch (_: Exception) {
                return
            }
            if (!store.setupComplete) return

            // Revivir si hay end_time local (activa o expirada), aunque el proceso haya muerto
            if (!store.shouldKeepAlive()) {
                SessionAlarmScheduler.cancelAll(appContext)
                return
            }

            store.serviceEnabled = true
            val lock = LockController(appContext)
            if (lock.isLockNeeded()) {
                try {
                    com.cibermonday.client.net.ConnectivityRestorer.ensureOnline(appContext)
                } catch (_: Exception) {
                }
            }
            ClientService.start(appContext, enable = true)
            val expired = lock.isLockNeeded()
            SessionAlarmScheduler.scheduleWatchdog(appContext, true, expiredInterval = expired)

            when (action) {
                SessionAlarmScheduler.ACTION_SESSION_EXPIRED -> {
                    Log.i(TAG, "Session expiry alarm → restore network + lock")
                    if (lock.isLockNeeded()) {
                        lock.lockWorkstation(forceSystemLock = true)
                    }
                }
                SessionAlarmScheduler.ACTION_WATCHDOG -> {
                    if (!store.shouldKeepAlive()) {
                        SessionAlarmScheduler.cancelAll(appContext)
                        return
                    }
                    Log.d(TAG, "Watchdog tick — keep client alive offline")
                    SessionAlarmScheduler.rescheduleAll(appContext, store)
                    if (lock.isLockNeeded()) {
                        try {
                            com.cibermonday.client.net.ConnectivityRestorer.ensureOnline(appContext)
                        } catch (_: Exception) {
                        }
                        if (lock.isScreenInteractive()) {
                            lock.enforceLock()
                        }
                    }
                }
            }
        } finally {
            try {
                if (wakeLock.isHeld) wakeLock.release()
            } catch (_: Exception) {
            }
        }
    }

    companion object {
        private const val TAG = "SessionAlarmReceiver"
    }
}
