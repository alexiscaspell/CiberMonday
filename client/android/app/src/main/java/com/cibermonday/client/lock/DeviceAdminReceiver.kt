package com.cibermonday.client.lock

import android.app.admin.DeviceAdminReceiver as AndroidDeviceAdminReceiver
import android.content.Context
import android.content.Intent
import com.cibermonday.client.util.AppLog

class DeviceAdminReceiver : AndroidDeviceAdminReceiver() {
    override fun onEnabled(context: Context, intent: Intent) {
        AppLog.i(TAG, "Device admin enabled")
    }

    override fun onDisabled(context: Context, intent: Intent) {
        AppLog.w(TAG, "Device admin disabled")
    }

    companion object {
        private const val TAG = "DeviceAdminReceiver"
    }
}
