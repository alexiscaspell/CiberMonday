package com.cibermonday.client.lock

import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.ui.LockActivity

class LockController(private val context: Context) {

    private val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
    private val adminComponent = ComponentName(context, DeviceAdminReceiver::class.java)

    @Volatile
    private var didSystemLock = false

    fun isDeviceAdminActive(): Boolean = dpm.isAdminActive(adminComponent)

    fun isAccessibilityEnabled(): Boolean {
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false
        val expected = ComponentName(context, LockAccessibilityService::class.java).flattenToString()
        return enabled.split(':').any { it.equals(expected, ignoreCase = true) }
    }

    fun canDrawOverlays(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Settings.canDrawOverlays(context)
        } else {
            true
        }
    }

    fun overlaySettingsIntent(): Intent {
        return Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            Uri.parse("package:${context.packageName}")
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    fun isScreenInteractive(): Boolean {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        return pm.isInteractive
    }

    fun isLockNeeded(): Boolean {
        val info = CiberMondayApp.instance.store.getSessionInfo() ?: return false
        return info.isExpired || info.remainingSeconds <= 0
    }

    /**
     * Al expirar: apaga/bloquea el sistema (pantalla off, bajo consumo).
     * La UI de "tiempo agotado" solo se muestra al desbloquear ([onUserUnlocked]).
     */
    fun lockWorkstation(forceSystemLock: Boolean = false) {
        if (!isLockNeeded()) return
        Log.i(TAG, "Session lock → screen off (no UI yet)")

        // Quitar overlay/activity que puedan mantener o despertar la pantalla
        LockOverlayService.stop(context)

        if ((forceSystemLock || !didSystemLock) && isDeviceAdminActive()) {
            try {
                dpm.lockNow()
                didSystemLock = true
            } catch (e: Exception) {
                Log.w(TAG, "lockNow failed: ${e.message}")
                // Sin Device Admin: si la pantalla ya está encendida, mostrar UI
                if (isScreenInteractive()) {
                    showLockUi()
                }
            }
        } else if (isScreenInteractive()) {
            showLockUi()
        }
    }

    /**
     * Re-bloquear solo con pantalla encendida (no despertar).
     */
    fun enforceLock() {
        if (!isLockNeeded()) {
            didSystemLock = false
            LockOverlayService.stop(context)
            return
        }
        if (!isScreenInteractive()) return
        val now = SystemClock.elapsedRealtime()
        if (now - lastEnforceElapsed < ENFORCE_DEBOUNCE_MS) return
        lastEnforceElapsed = now
        showLockUi()
        bringLockTaskToFront()
    }

    /** Usuario desbloqueó el PIN: mostrar bloqueo de sesión. */
    fun onUserUnlocked() {
        if (!isLockNeeded()) return
        Log.i(TAG, "User unlocked while expired — showing lock UI")
        showLockUi()
    }

    /** Pantalla apagada: asegurar que no quede overlay activo. */
    fun onScreenOff() {
        if (!isLockNeeded()) return
        LockOverlayService.stop(context)
    }

    private fun showLockUi() {
        showLockActivity()
        LockOverlayService.start(context)
    }

    fun showLockActivity() {
        val intent = Intent(context, LockActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
            addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
            addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
            addFlags(Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS)
            addFlags(Intent.FLAG_ACTIVITY_NO_USER_ACTION)
        }
        context.startActivity(intent)
    }

    fun dismissLockIfNeeded() {
        if (isLockNeeded()) return
        didSystemLock = false
        LockOverlayService.stop(context)
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            am.appTasks.forEach { task ->
                val name = task.taskInfo.topActivity?.className
                if (name == LockActivity::class.java.name) {
                    task.finishAndRemoveTask()
                }
            }
        }
    }

    fun ensureLockedIfExpired() {
        if (!isLockNeeded()) return
        enforceLock()
    }

    private fun bringLockTaskToFront() {
        try {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                am.appTasks.forEach { task ->
                    val name = task.taskInfo.topActivity?.className
                    if (name == LockActivity::class.java.name) {
                        task.moveToFront()
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "moveToFront failed: ${e.message}")
        }
    }

    companion object {
        private const val TAG = "LockController"
        private const val ENFORCE_DEBOUNCE_MS = 1_200L

        @Volatile
        private var lastEnforceElapsed = 0L
    }
}
