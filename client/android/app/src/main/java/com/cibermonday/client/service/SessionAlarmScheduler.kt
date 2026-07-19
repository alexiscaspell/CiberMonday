package com.cibermonday.client.service

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.cibermonday.client.session.SessionStore

/**
 * Alarmas exactas para bloquear al expirar aunque el proceso de la app haya sido
 * matado (cierre desde recientes / OEM agresivos como MIUI).
 */
object SessionAlarmScheduler {

    const val ACTION_SESSION_EXPIRED = "com.cibermonday.client.SESSION_EXPIRED"
    const val ACTION_WATCHDOG = "com.cibermonday.client.WATCHDOG"

    private const val REQ_EXPIRED = 4101
    private const val REQ_WATCHDOG = 4102
    private const val WATCHDOG_INTERVAL_MS = 45_000L
    private const val WATCHDOG_EXPIRED_MS = 180_000L
    private const val TAG = "SessionAlarm"

    fun rescheduleAll(context: Context, store: SessionStore) {
        if (!store.serviceEnabled) {
            cancelAll(context)
            return
        }
        val expired = store.getSessionInfo()?.let { it.isExpired || it.remainingSeconds <= 0 } == true
        scheduleWatchdog(context, store.setupComplete, expiredInterval = expired)
        val endMs = store.endTimeMillis()
        if (endMs == null) {
            cancelExpiry(context)
            return
        }
        scheduleExpiry(context, endMs)
    }

    fun scheduleExpiry(context: Context, endTimeMs: Long) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pi = pending(context, ACTION_SESSION_EXPIRED, REQ_EXPIRED)
        val triggerAt = maxOf(endTimeMs, System.currentTimeMillis() + 1_000L)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pi)
            } else {
                @Suppress("DEPRECATION")
                am.setExact(AlarmManager.RTC_WAKEUP, triggerAt, pi)
            }
            Log.i(TAG, "Expiry alarm at $triggerAt")
        } catch (e: Exception) {
            Log.w(TAG, "setExact failed, fallback: ${e.message}")
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pi)
        }
    }

    fun cancelExpiry(context: Context) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        am.cancel(pending(context, ACTION_SESSION_EXPIRED, REQ_EXPIRED))
    }

    fun cancelAll(context: Context) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        am.cancel(pending(context, ACTION_SESSION_EXPIRED, REQ_EXPIRED))
        am.cancel(pending(context, ACTION_WATCHDOG, REQ_WATCHDOG))
        // Reintentos de boot (BootReceiver)
        for (code in 4201..4203) {
            val intent = Intent(context, SessionAlarmReceiver::class.java)
                .setAction(ACTION_WATCHDOG)
            am.cancel(
                PendingIntent.getBroadcast(
                    context,
                    code,
                    intent,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
            )
        }
        Log.i(TAG, "All alarms cancelled")
    }

    fun scheduleWatchdog(context: Context, enabled: Boolean, expiredInterval: Boolean = false) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pi = pending(context, ACTION_WATCHDOG, REQ_WATCHDOG)
        if (!enabled) {
            am.cancel(pi)
            return
        }
        val interval = if (expiredInterval) WATCHDOG_EXPIRED_MS else WATCHDOG_INTERVAL_MS
        val triggerAt = System.currentTimeMillis() + interval
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                if (expiredInterval) {
                    // Menos agresivo con batería cuando ya expiró
                    am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pi)
                } else {
                    am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pi)
                }
            } else {
                @Suppress("DEPRECATION")
                am.setExact(AlarmManager.RTC_WAKEUP, triggerAt, pi)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Watchdog exact failed: ${e.message}")
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pi)
        }
    }

    private fun pending(context: Context, action: String, requestCode: Int): PendingIntent {
        val intent = Intent(context, SessionAlarmReceiver::class.java).setAction(action)
        return PendingIntent.getBroadcast(
            context,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }
}
