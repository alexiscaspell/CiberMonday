package com.cibermonday.client.lock

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.service.ClientService
import com.cibermonday.client.service.SessionAlarmScheduler

/**
 * - SCREEN_OFF: limpiar overlay (ahorro; no despertar).
 * - USER_PRESENT / USER_UNLOCKED: mostrar bloqueo de sesión.
 * - SCREEN_ON: no hacer nada (esperar al PIN / USER_PRESENT).
 */
class UnlockReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        val appContext = context.applicationContext
        val store = try {
            CiberMondayApp.instance.store
        } catch (_: Exception) {
            return
        }
        if (!store.setupComplete) return

        val lock = LockController(appContext)

        when (action) {
            Intent.ACTION_SCREEN_OFF -> {
                if (lock.isLockNeeded()) {
                    Log.d(TAG, "Screen off while expired — stay asleep")
                    lock.onScreenOff()
                }
                return
            }
            Intent.ACTION_SCREEN_ON -> {
                Log.d(TAG, "Screen on — waiting for unlock")
                return
            }
            Intent.ACTION_USER_PRESENT,
            Intent.ACTION_USER_UNLOCKED -> {
                if (!store.serviceEnabled && !lock.isLockNeeded()) return
                ClientService.start(appContext)
                SessionAlarmScheduler.rescheduleAll(appContext, store)
                if (!lock.isLockNeeded()) return
                Log.i(TAG, "User unlocked while expired — lock UI ($action)")
                lock.onUserUnlocked()
            }
        }
    }

    companion object {
        private const val TAG = "UnlockReceiver"
    }
}
