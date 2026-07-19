package com.cibermonday.client.service

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.PowerManager
import android.util.Log
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.lock.LockController

/**
 * Restaura servicio, alarmas y bloqueo tras reinicio del teléfono
 * (y reinicios rápidos de MIUI / actualización de la app).
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        if (action !in BOOT_ACTIONS) return

        val appContext = context.applicationContext
        val pending = goAsync()
        val wakeLock = (appContext.getSystemService(Context.POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CiberMonday:Boot").apply {
                setReferenceCounted(false)
                acquire(20_000L)
            }

        Thread({
            try {
                restoreAfterBoot(appContext, action)
                // Reintentos vía AlarmManager (más fiable que Handler tras boot en MIUI)
                scheduleBootRetry(appContext, 15_000L, 4201)
                scheduleBootRetry(appContext, 60_000L, 4202)
                scheduleBootRetry(appContext, 120_000L, 4203)
            } catch (e: Exception) {
                Log.e(TAG, "Boot restore failed: ${e.message}")
            } finally {
                try {
                    if (wakeLock.isHeld) wakeLock.release()
                } catch (_: Exception) {
                }
                pending.finish()
            }
        }, "cibermonday-boot").start()
    }

    companion object {
        private const val TAG = "BootReceiver"

        val BOOT_ACTIONS = setOf(
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_LOCKED_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            "android.intent.action.QUICKBOOT_POWERON",
            "com.htc.intent.action.QUICKBOOT_POWERON"
        )

        fun restoreAfterBoot(context: Context, reason: String) {
            val store = try {
                CiberMondayApp.instance.store
            } catch (_: Exception) {
                Log.w(TAG, "App not ready ($reason)")
                return
            }
            if (!store.setupComplete) {
                Log.i(TAG, "Setup incomplete — skip ($reason)")
                return
            }
            // Tras "Detener" en el panel no reiniciar solo (ahorro batería),
            // salvo que haya sesión activa/expirada que haya que vigilar.
            val info = store.getSessionInfo()
            val needsLock = info != null && (info.isExpired || info.remainingSeconds <= 0)
            val hasActive = info != null && !info.isExpired && info.remainingSeconds > 0
            if (!store.serviceEnabled && !needsLock && !hasActive) {
                Log.i(TAG, "Service disabled by admin stop — skip ($reason)")
                SessionAlarmScheduler.cancelAll(context)
                return
            }
            Log.i(TAG, "Restoring client after boot ($reason)")
            store.serviceEnabled = true
            SessionAlarmScheduler.rescheduleAll(context, store)
            ClientService.start(context)

            val lock = LockController(context)
            if (lock.isLockNeeded()) {
                Log.i(TAG, "Session already expired after boot — locking")
                lock.lockWorkstation(forceSystemLock = true)
            }
        }

        private fun scheduleBootRetry(context: Context, delayMs: Long, requestCode: Int) {
            val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val intent = Intent(context, SessionAlarmReceiver::class.java)
                .setAction(SessionAlarmScheduler.ACTION_WATCHDOG)
            val pi = PendingIntent.getBroadcast(
                context,
                requestCode,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val triggerAt = System.currentTimeMillis() + delayMs
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pi)
                } else {
                    @Suppress("DEPRECATION")
                    am.setExact(AlarmManager.RTC_WAKEUP, triggerAt, pi)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Boot retry alarm failed: ${e.message}")
                am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pi)
            }
        }
    }
}
