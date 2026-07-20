package com.cibermonday.client.net

import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import android.provider.Settings
import android.telephony.TelephonyManager
import android.util.Log
import java.lang.reflect.Method

/**
 * Al expirar la sesión, si el usuario apaga Wi‑Fi/datos el teléfono queda
 * bloqueado sin poder recibir tiempo nuevo. Intenta reactivar la red.
 *
 * En Android 10+ el sistema restringe el toggle; se prueban varias vías
 * (API pública, Settings.Global, reflection Telephony).
 */
object ConnectivityRestorer {

    private const val TAG = "ConnectivityRestorer"

    fun hasUsableNetwork(context: Context): Boolean {
        return try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val network = cm.activeNetwork ?: return false
            val caps = cm.getNetworkCapabilities(network) ?: return false
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        } catch (_: Exception) {
            false
        }
    }

    fun isWifiEnabled(context: Context): Boolean {
        return try {
            val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            wifi.isWifiEnabled
        } catch (_: Exception) {
            false
        }
    }

    fun isAirplaneModeOn(context: Context): Boolean {
        return try {
            Settings.Global.getInt(context.contentResolver, Settings.Global.AIRPLANE_MODE_ON, 0) == 1
        } catch (_: Exception) {
            false
        }
    }

    /**
     * @return true si hay red usable tras el intento (o ya la había).
     */
    fun ensureOnline(context: Context): Boolean {
        val app = context.applicationContext
        if (hasUsableNetwork(app)) return true

        Log.i(TAG, "No usable network — restoring Wi‑Fi / mobile data")
        var changed = false

        if (isAirplaneModeOn(app)) {
            if (setAirplaneMode(app, false)) changed = true
        }

        if (!isWifiEnabled(app)) {
            if (enableWifi(app)) changed = true
        }

        if (enableMobileData(app)) changed = true

        // Pequeña espera si tocamos radios
        if (changed) {
            try {
                Thread.sleep(1_200L)
            } catch (_: InterruptedException) {
            }
        }

        val ok = hasUsableNetwork(app)
        Log.i(TAG, "ensureOnline → network=$ok wifi=${isWifiEnabled(app)} airplane=${isAirplaneModeOn(app)}")
        return ok
    }

    @Suppress("DEPRECATION")
    fun enableWifi(context: Context): Boolean {
        return try {
            val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            if (wifi.isWifiEnabled) return true
            val ok = wifi.setWifiEnabled(true)
            Log.i(TAG, "setWifiEnabled(true) → $ok")
            ok || wifi.isWifiEnabled
        } catch (e: Exception) {
            Log.w(TAG, "enableWifi: ${e.message}")
            false
        }
    }

    fun enableMobileData(context: Context): Boolean {
        val app = context.applicationContext
        // 1) TelephonyManager.setDataEnabled (API 26+, suele requerir privilegio)
        try {
            val tm = app.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val method: Method? = try {
                    tm.javaClass.getDeclaredMethod("setDataEnabled", Boolean::class.javaPrimitiveType)
                } catch (_: NoSuchMethodException) {
                    null
                }
                if (method != null) {
                    method.isAccessible = true
                    method.invoke(tm, true)
                    Log.i(TAG, "TelephonyManager.setDataEnabled(true)")
                    return true
                }
            }
        } catch (e: Exception) {
            Log.d(TAG, "setDataEnabled: ${e.message}")
        }

        // 2) Settings.Global.mobile_data (WRITE_SECURE_SETTINGS)
        try {
            val cr = app.contentResolver
            val before = Settings.Global.getInt(cr, "mobile_data", 1)
            if (before == 0) {
                Settings.Global.putInt(cr, "mobile_data", 1)
                Log.i(TAG, "Settings.Global mobile_data=1")
                return true
            }
        } catch (e: Exception) {
            Log.d(TAG, "mobile_data setting: ${e.message}")
        }

        // 3) Reflection ConnectivityManager (APIs antiguas)
        try {
            val cm = app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val field = cm.javaClass.getDeclaredField("mService")
            field.isAccessible = true
            val service = field.get(cm) ?: return false
            val method = service.javaClass.getDeclaredMethod(
                "setMobileDataEnabled",
                Boolean::class.javaPrimitiveType
            )
            method.isAccessible = true
            method.invoke(service, true)
            Log.i(TAG, "ConnectivityManager.setMobileDataEnabled(true)")
            return true
        } catch (e: Exception) {
            Log.d(TAG, "setMobileDataEnabled: ${e.message}")
        }
        return false
    }

    private fun setAirplaneMode(context: Context, enabled: Boolean): Boolean {
        return try {
            val cr = context.contentResolver
            Settings.Global.putInt(
                cr,
                Settings.Global.AIRPLANE_MODE_ON,
                if (enabled) 1 else 0
            )
            val intent = Intent(Intent.ACTION_AIRPLANE_MODE_CHANGED).apply {
                putExtra("state", enabled)
            }
            context.sendBroadcast(intent)
            Log.i(TAG, "airplane_mode → $enabled")
            true
        } catch (e: Exception) {
            Log.d(TAG, "airplane_mode: ${e.message}")
            false
        }
    }
}
