package com.cibermonday.client

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.util.Log
import com.cibermonday.client.lock.LockController
import com.cibermonday.client.service.ClientService
import com.cibermonday.client.service.SessionAlarmScheduler
import com.cibermonday.client.session.SessionStore

class CiberMondayApp : Application() {
    lateinit var store: SessionStore
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        store = SessionStore(this)
        createNotificationChannels()
        recoverIfNeeded()
    }

    /**
     * Si hay end_time local (activa o expirada), el proceso debe vigilar/bloquear
     * aunque no haya red ni servidor (paridad con SessionData de Windows).
     */
    fun recoverIfNeeded() {
        if (!store.shouldKeepAlive()) return
        val info = store.getSessionInfo()
        val expired = info != null && (info.isExpired || info.remainingSeconds <= 0)
        store.serviceEnabled = true
        try {
            SessionAlarmScheduler.rescheduleAll(this, store)
        } catch (e: Exception) {
            Log.w(TAG, "reschedule: ${e.message}")
        }
        ClientService.start(this, enable = true)
        if (expired) {
            try {
                LockController(this).lockWorkstation(forceSystemLock = true)
            } catch (e: Exception) {
                Log.w(TAG, "recover lock: ${e.message}")
            }
        }
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_SERVICE,
                getString(R.string.notification_channel_name),
                NotificationManager.IMPORTANCE_LOW
            )
        )
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ALERTS,
                getString(R.string.notification_channel_alerts),
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                enableVibration(true)
            }
        )
    }

    companion object {
        private const val TAG = "CiberMondayApp"
        const val CHANNEL_SERVICE = "cibermonday_service"
        const val CHANNEL_ALERTS = "cibermonday_alerts"

        lateinit var instance: CiberMondayApp
            private set
    }
}
