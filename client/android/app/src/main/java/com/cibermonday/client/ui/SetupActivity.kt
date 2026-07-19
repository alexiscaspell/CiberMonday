package com.cibermonday.client.ui

import android.Manifest
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.R
import com.cibermonday.client.lock.DeviceAdminReceiver
import com.cibermonday.client.lock.LockAccessibilityService
import com.cibermonday.client.lock.LockController
import com.cibermonday.client.net.ApiClient
import com.cibermonday.client.net.DiscoveryListener
import com.cibermonday.client.service.ClientService
import com.cibermonday.client.service.SessionAlarmScheduler
import com.google.android.material.button.MaterialButton
import kotlin.concurrent.thread

class SetupActivity : AppCompatActivity() {

    private lateinit var store: com.cibermonday.client.session.SessionStore
    private lateinit var lockController: LockController

    private lateinit var txtDeviceAdmin: TextView
    private lateinit var txtAccessibility: TextView
    private lateinit var txtBattery: TextView
    private lateinit var txtOverlay: TextView
    private lateinit var editServerUrl: EditText
    private lateinit var txtMessage: TextView
    private lateinit var btnDeviceAdmin: MaterialButton
    private lateinit var btnAccessibility: MaterialButton
    private lateinit var btnBattery: MaterialButton
    private lateinit var btnOverlay: MaterialButton

    private var discovery: DiscoveryListener? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        store = CiberMondayApp.instance.store
        lockController = LockController(this)

        if (store.setupComplete && intent?.getBooleanExtra(EXTRA_FORCE_SETUP, false) != true) {
            startActivity(Intent(this, StatusActivity::class.java))
            finish()
            return
        }

        setContentView(R.layout.activity_setup)

        txtDeviceAdmin = findViewById(R.id.txtDeviceAdminStatus)
        txtAccessibility = findViewById(R.id.txtAccessibilityStatus)
        txtBattery = findViewById(R.id.txtBatteryStatus)
        txtOverlay = findViewById(R.id.txtOverlayStatus)
        editServerUrl = findViewById(R.id.editServerUrl)
        txtMessage = findViewById(R.id.txtSetupMessage)
        btnDeviceAdmin = findViewById(R.id.btnDeviceAdmin)
        btnAccessibility = findViewById(R.id.btnAccessibility)
        btnBattery = findViewById(R.id.btnBattery)
        btnOverlay = findViewById(R.id.btnOverlay)

        editServerUrl.setText(store.serverUrl)

        btnDeviceAdmin.setOnClickListener { requestDeviceAdmin() }
        btnAccessibility.setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        btnBattery.setOnClickListener { requestBatteryExemption() }
        btnOverlay.setOnClickListener {
            startActivity(lockController.overlaySettingsIntent())
        }

        findViewById<MaterialButton>(R.id.btnDiscover).setOnClickListener { startDiscovery() }
        findViewById<MaterialButton>(R.id.btnSaveStart).setOnClickListener { saveAndStart() }

        requestNotificationPermissionIfNeeded()
        requestExactAlarmIfNeeded()
        refreshPermissionUi()
    }

    private fun requestExactAlarmIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        val am = getSystemService(android.app.AlarmManager::class.java) ?: return
        if (am.canScheduleExactAlarms()) return
        try {
            startActivity(
                Intent(
                    Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                    Uri.parse("package:$packageName")
                )
            )
        } catch (_: Exception) {
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            == PackageManager.PERMISSION_GRANTED
        ) return
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            1001
        )
    }

    override fun onResume() {
        super.onResume()
        refreshPermissionUi()
    }

    override fun onDestroy() {
        discovery?.stop()
        super.onDestroy()
    }

    private fun refreshPermissionUi() {
        val adminOk = lockController.isDeviceAdminActive()
        txtDeviceAdmin.text = if (adminOk) "Device Admin — activo" else "Device Admin — pendiente"
        btnDeviceAdmin.isEnabled = !adminOk
        btnDeviceAdmin.text = if (adminOk) "OK" else "Activar"

        val accessOk = lockController.isAccessibilityEnabled() || LockAccessibilityService.isRunning()
        txtAccessibility.text = if (accessOk) "Accesibilidad — activa" else "Accesibilidad — pendiente"
        btnAccessibility.isEnabled = !accessOk
        btnAccessibility.text = if (accessOk) "OK" else "Activar"

        val batteryOk = isBatteryOptimizedExempt()
        txtBattery.text = if (batteryOk) "Batería — exenta" else "Batería — puede limitar el servicio"
        btnBattery.isEnabled = !batteryOk
        btnBattery.text = if (batteryOk) "OK" else "Eximir"

        val overlayOk = lockController.canDrawOverlays()
        txtOverlay.text = if (overlayOk) "Sobre otras apps — activo" else "Sobre otras apps — pendiente"
        btnOverlay.isEnabled = !overlayOk
        btnOverlay.text = if (overlayOk) "OK" else "Activar"
    }

    private fun requestDeviceAdmin() {
        val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN).apply {
            putExtra(
                DevicePolicyManager.EXTRA_DEVICE_ADMIN,
                ComponentName(this@SetupActivity, DeviceAdminReceiver::class.java)
            )
            putExtra(
                DevicePolicyManager.EXTRA_ADD_EXPLANATION,
                getString(R.string.device_admin_description)
            )
        }
        startActivity(intent)
    }

    private fun requestBatteryExemption() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
            data = Uri.parse("package:$packageName")
        }
        try {
            startActivity(intent)
        } catch (_: Exception) {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun isBatteryOptimizedExempt(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    private fun startDiscovery() {
        txtMessage.text = "Buscando servidores…"
        discovery?.stop()
        val discoverBtn = findViewById<MaterialButton>(R.id.btnDiscover)
        discoverBtn.isEnabled = false
        discovery = DiscoveryListener(
            context = this,
            store = store,
            onServerFound = { url ->
                runOnUiThread {
                    editServerUrl.setText(url)
                    txtMessage.text = "Servidor encontrado: $url"
                    discoverBtn.isEnabled = true
                }
            },
            onStatus = { msg ->
                runOnUiThread { txtMessage.text = msg }
            }
        ).also { listener ->
            listener.start(timeoutMs = 6_000L)
            // Re-habilitar botón cuando termine (aunque no encuentre)
            thread {
                Thread.sleep(14_000)
                runOnUiThread {
                    discoverBtn.isEnabled = true
                    if (txtMessage.text.toString().startsWith("Buscando") ||
                        txtMessage.text.toString().startsWith("Escuchando")
                    ) {
                        txtMessage.text = "No se encontró servidor. Ingresá la URL manualmente."
                    }
                }
            }
        }
    }

    private fun saveAndStart() {
        val url = editServerUrl.text.toString().trim().trimEnd('/')
        if (url.isBlank() || !url.startsWith("http")) {
            Toast.makeText(this, "Ingresá una URL válida (http://…)", Toast.LENGTH_SHORT).show()
            return
        }
        if (!lockController.isDeviceAdminActive()) {
            Toast.makeText(this, "Activá Device Admin primero", Toast.LENGTH_SHORT).show()
            return
        }
        if (!lockController.isAccessibilityEnabled() && !LockAccessibilityService.isRunning()) {
            Toast.makeText(this, "Activá el servicio de Accesibilidad", Toast.LENGTH_SHORT).show()
            return
        }
        if (!lockController.canDrawOverlays()) {
            Toast.makeText(this, "Activá 'Mostrar sobre otras apps'", Toast.LENGTH_SHORT).show()
            return
        }

        store.serverUrl = url
        store.addServer(url)
        txtMessage.text = "Registrando en el servidor…"

        thread {
            val api = ApiClient(store)
            val id = api.register(url, store.ensureClientId())
            runOnUiThread {
                if (id == null) {
                    txtMessage.text = "No se pudo registrar. Se iniciará igual y reintentará."
                } else {
                    txtMessage.text = "Registrado: ${id.take(8)}…"
                }
                store.setupComplete = true
                store.serviceEnabled = true
                SessionAlarmScheduler.rescheduleAll(this@SetupActivity, store)
                ClientService.start(this, enable = true)
                startActivity(Intent(this, StatusActivity::class.java))
                finish()
            }
        }
    }

    companion object {
        const val EXTRA_FORCE_SETUP = "force_setup"
    }
}
