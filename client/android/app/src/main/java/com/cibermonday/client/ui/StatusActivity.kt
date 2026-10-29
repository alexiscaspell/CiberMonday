package com.cibermonday.client.ui

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.cibermonday.client.CiberMondayApp
import com.cibermonday.client.R
import com.cibermonday.client.lock.LockController
import com.cibermonday.client.net.ApiClient
import com.cibermonday.client.net.NetworkFilterVpnService
import com.cibermonday.client.service.ClientService
import com.cibermonday.client.session.SessionStore
import com.google.android.material.button.MaterialButton

class StatusActivity : AppCompatActivity() {

    private lateinit var store: SessionStore
    private lateinit var lockController: LockController
    private lateinit var txtRemaining: TextView
    private lateinit var txtStatus: TextView
    private lateinit var txtClientId: TextView
    private lateinit var txtServerInfo: TextView

    private val handler = Handler(Looper.getMainLooper())
    private val ticker = object : Runnable {
        override fun run() {
            refreshUi()
            handler.postDelayed(this, 1000)
        }
    }

    private val storeListener = { runOnUiThread { refreshUi() } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        store = CiberMondayApp.instance.store
        lockController = LockController(this)

        if (!store.setupComplete) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }

        setContentView(R.layout.activity_status)
        txtRemaining = findViewById(R.id.txtRemaining)
        txtStatus = findViewById(R.id.txtStatusLabel)
        txtClientId = findViewById(R.id.txtClientId)
        txtServerInfo = findViewById(R.id.txtServerInfo)

        findViewById<MaterialButton>(R.id.btnOpenSetup).setOnClickListener {
            startActivity(
                Intent(this, SetupActivity::class.java).putExtra(SetupActivity.EXTRA_FORCE_SETUP, true)
            )
        }

        // Mientras la UI está abierta, el servicio recibe push.
        // Si hay end_time local y cierras la app, el watchdog reabre el FGS.
        // Tras Detener (sin sesión), onTaskRemoved deja el cliente cerrado.
        ClientService.start(this, enable = true)
        store.addListener(storeListener)
        maybeRequestVpnConsent()
        refreshUi()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra(NetworkFilterVpnService.EXTRA_REQUEST_VPN, false)) {
            maybeRequestVpnConsent()
        }
    }

    override fun onResume() {
        super.onResume()
        if (lockController.isLockNeeded()) {
            lockController.showLockActivity()
            return
        }
        maybeRequestVpnConsent()
        try {
            NetworkFilterVpnService.syncWithPolicy(this)
        } catch (_: Exception) {
        }
        handler.post(ticker)
    }

    private fun maybeRequestVpnConsent() {
        // VPN solo con sesión/tiempo activo — pedir permiso en ese momento.
        if (!NetworkFilterVpnService.needsVpnPreparation(store)) {
            store.vpnConsentNeeded = false
            NetworkFilterVpnService.syncWithPolicy(this)
            return
        }
        val prep = VpnService.prepare(this) ?: run {
            store.vpnConsentGranted = true
            store.vpnConsentNeeded = false
            NetworkFilterVpnService.syncWithPolicy(this)
            return
        }
        store.vpnConsentNeeded = true
        startActivityForResult(prep, REQ_VPN)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_VPN) {
            if (resultCode == Activity.RESULT_OK) {
                store.vpnConsentGranted = true
                store.vpnConsentNeeded = false
                NetworkFilterVpnService.syncWithPolicy(this)
            }
        }
    }

    override fun onPause() {
        handler.removeCallbacks(ticker)
        super.onPause()
    }

    override fun onDestroy() {
        store.removeListener(storeListener)
        super.onDestroy()
    }

    private fun refreshUi() {
        val id = store.clientId
        txtClientId.text = if (id.isNullOrBlank()) "Sin ID" else "ID: ${id.take(8)}…"

        val info = store.getSessionInfo()
        when {
            info == null -> {
                txtRemaining.text = "--"
                txtStatus.text = "Esperando sesión"
            }
            info.isExpired || info.remainingSeconds <= 0 -> {
                txtRemaining.text = "00:00"
                txtStatus.text = "Tiempo agotado"
            }
            else -> {
                txtRemaining.text = ClientService.formatTime(info.remainingSeconds)
                txtStatus.text = "Sesión activa"
            }
        }

        val inet = store.getInternetSessionInfo()
        val netMode = store.computeNetworkPolicyMode()
        val servers = store.loadServers().joinToString("\n") { "• ${it.url}" }
        txtServerInfo.text = buildString {
            append("Servidor: ${store.serverUrl}\n")
            append("IP local: ${ApiClient.localIpAddress() ?: "?"}\n")
            append("Push: :${ApiClient.DIAGNOSTIC_PORT}\n")
            append("Red: $netMode\n")
            if (inet != null) {
                append("Internet: ${ClientService.formatTime(inet.remainingSeconds)}\n")
            }
            if (store.vpnConsentNeeded) {
                append("\nSe requiere permiso VPN (internet control).\n")
            } else if (NetworkFilterVpnService.hasActiveTimedSession(store) && store.vpnConsentGranted) {
                append("VPN: activa\n")
            } else {
                append("VPN: apagada (sin tiempo)\n")
            }
            if (servers.isNotBlank()) {
                append("\nConocidos:\n$servers")
            }
        }
    }

    companion object {
        private const val REQ_VPN = 1001
    }
}
