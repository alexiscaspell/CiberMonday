package com.cibermonday.server

import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.google.android.material.floatingactionbutton.FloatingActionButton
import org.json.JSONObject

class MainActivity : AppCompatActivity() {

    private lateinit var recyclerClients: RecyclerView
    private lateinit var emptyState: View
    private lateinit var tvClientCount: TextView
    private lateinit var tvServerIp: TextView
    private lateinit var tvStatus: TextView
    private lateinit var fabRefresh: FloatingActionButton
    private lateinit var btnCopyUrl: TextView
    private lateinit var btnOpenBrowser: TextView
    private lateinit var clientAdapter: ClientAdapter
    private lateinit var serversSection: View
    private lateinit var serversList: LinearLayout
    private lateinit var broadcastConfigSection: View
    private lateinit var tvBroadcastInterval: TextView
    
    private var serverIp: String = ""

    private val handler = Handler(Looper.getMainLooper())
    private val refreshInterval = 5000L // 5 segundos
    
    private val refreshRunnable = object : Runnable {
        override fun run() {
            loadClients()
            loadServers()
            loadServerConfig()
            handler.postDelayed(this, refreshInterval)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Inicializar Python
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        initViews()
        setupRecyclerView()
        
        // Iniciar servidor Flask para clientes remotos
        startFlaskServer()
        
        loadServerIp()
        loadServerConfig()
        loadServers()
        loadClients()
        
        broadcastConfigSection.setOnClickListener {
            showBroadcastConfigDialog()
        }
    }
    
    private fun startFlaskServer() {
        tvStatus.text = "Iniciando..."
        tvStatus.setBackgroundResource(R.drawable.status_inactive_bg)
        
        // Iniciar el servicio del servidor
        val intent = Intent(this, FlaskServerService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        
        // Verificar el estado del servidor después de un delay
        handler.postDelayed({
            checkServerStatus()
        }, 5000)
    }
    
    private fun checkServerStatus() {
        Thread {
            var connected = false
            
            // Intentar primero con localhost
            try {
                val socket = java.net.Socket()
                socket.connect(java.net.InetSocketAddress("127.0.0.1", 5000), 2000)
                socket.close()
                connected = true
            } catch (e: Exception) {
                // Si falla localhost, intentar con la IP local de WiFi
                try {
                    val py = Python.getInstance()
                    val module = py.getModule("cibermonday_android")
                    val localIp = module.callAttr("get_local_ip").toString()
                    
                    if (localIp.isNotEmpty() && localIp != "127.0.0.1" && localIp != "No conectado") {
                        val socket = java.net.Socket()
                        socket.connect(java.net.InetSocketAddress(localIp, 5000), 2000)
                        socket.close()
                        connected = true
                    }
                } catch (e2: Exception) {
                    // Ambas conexiones fallaron
                }
            }
            
            runOnUiThread {
                if (connected) {
                    tvStatus.text = "Servidor Activo"
                    tvStatus.setBackgroundResource(R.drawable.status_active_bg)
                } else {
                    tvStatus.text = "Error"
                    tvStatus.setBackgroundResource(R.drawable.status_inactive_bg)
                }
            }
        }.start()
    }

    private fun initViews() {
        recyclerClients = findViewById(R.id.recyclerClients)
        emptyState = findViewById(R.id.emptyState)
        tvClientCount = findViewById(R.id.tvClientCount)
        tvServerIp = findViewById(R.id.tvServerIp)
        tvStatus = findViewById(R.id.tvStatus)
        fabRefresh = findViewById(R.id.fabRefresh)
        btnCopyUrl = findViewById(R.id.btnCopyUrl)
        btnOpenBrowser = findViewById(R.id.btnOpenBrowser)
        serversSection = findViewById(R.id.serversSection)
        serversList = findViewById(R.id.serversList)
        broadcastConfigSection = findViewById(R.id.broadcastConfigSection)
        tvBroadcastInterval = findViewById(R.id.tvBroadcastInterval)
        broadcastConfigSection = findViewById(R.id.broadcastConfigSection)
        tvBroadcastInterval = findViewById(R.id.tvBroadcastInterval)

        fabRefresh.setOnClickListener {
            loadClients()
            Toast.makeText(this, "Actualizado", Toast.LENGTH_SHORT).show()
        }
        
        btnCopyUrl.setOnClickListener {
            if (serverIp.isNotEmpty()) {
                val url = "http://$serverIp:5000"
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val clip = ClipData.newPlainText("Server URL", url)
                clipboard.setPrimaryClip(clip)
                Toast.makeText(this, "URL copiada: $url", Toast.LENGTH_SHORT).show()
            }
        }
        
        btnOpenBrowser.setOnClickListener {
            if (serverIp.isNotEmpty()) {
                val url = "http://$serverIp:5000"
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                startActivity(intent)
            }
        }
    }

    private fun setupRecyclerView() {
        clientAdapter = ClientAdapter(
            onSetTime = { clientId, time, unit -> setClientTime(clientId, time, unit) },
            onStopSession = { clientId -> stopClientSession(clientId) },
            onDeleteClient = { clientId -> confirmDeleteClient(clientId) },
            onEditName = { clientId, newName -> editClientName(clientId, newName) },
            onSaveConfig = { clientId, syncInterval, alertThresholds -> saveClientConfig(clientId, syncInterval, alertThresholds) }
        )

        recyclerClients.apply {
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = clientAdapter
        }
    }

    private fun loadServerIp() {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                val ip = module.callAttr("get_local_ip").toString()
                
                runOnUiThread {
                    serverIp = ip
                    tvServerIp.text = ip
                }
            } catch (e: Exception) {
                runOnUiThread {
                    tvServerIp.text = "No disponible"
                }
            }
        }.start()
    }

    private fun loadServers() {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                val serversJson = module.callAttr("get_servers_json").toString()
                
                val serversArray = org.json.JSONArray(serversJson)
                val currentServerUrl = "http://$serverIp:5000"
                
                runOnUiThread {
                    serversList.removeAllViews()
                    
                    var hasOtherServers = false
                    for (i in 0 until serversArray.length()) {
                        val serverObj = serversArray.getJSONObject(i)
                        val serverUrl = serverObj.optString("url", "")
                        
                        // Filtrar el servidor actual
                        if (serverUrl != currentServerUrl && serverUrl.isNotEmpty()) {
                            hasOtherServers = true
                            
                            val serverView = layoutInflater.inflate(android.R.layout.simple_list_item_2, serversList, false)
                            val text1 = serverView.findViewById<TextView>(android.R.id.text1)
                            val text2 = serverView.findViewById<TextView>(android.R.id.text2)
                            
                            text1.text = serverUrl
                            val ip = serverObj.optString("ip", "")
                            val port = serverObj.optInt("port", 5000)
                            val lastSeen = serverObj.optString("last_seen", "")
                            
                            val details = buildString {
                                if (ip.isNotEmpty()) append("IP: $ip:$port")
                                if (lastSeen.isNotEmpty()) {
                                    if (isNotEmpty()) append(" • ")
                                    append("Visto: ${formatDate(lastSeen)}")
                                }
                            }
                            text2.text = details
                            
                            serverView.setOnClickListener {
                                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(serverUrl))
                                startActivity(intent)
                            }
                            
                            serversList.addView(serverView)
                        }
                    }
                    
                    serversSection.visibility = if (hasOtherServers) View.VISIBLE else View.GONE
                }
            } catch (e: Exception) {
                e.printStackTrace()
                runOnUiThread {
                    serversSection.visibility = View.GONE
                }
            }
        }.start()
    }
    
    private fun formatDate(isoDate: String): String {
        return try {
            val inputFormat = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.getDefault())
            val outputFormat = java.text.SimpleDateFormat("dd/MM HH:mm", java.util.Locale.getDefault())
            val date = inputFormat.parse(isoDate.split(".")[0])
            outputFormat.format(date!!)
        } catch (e: Exception) {
            isoDate
        }
    }
    
    private fun loadServerConfig() {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                val response = module.callAttr("get_server_config_json").toString()
                
                val configObj = org.json.JSONObject(response)
                val success = configObj.optBoolean("success", false)
                
                if (success) {
                    val config = configObj.getJSONObject("config")
                    val interval = config.optInt("broadcast_interval", 1)
                    
                    runOnUiThread {
                        tvBroadcastInterval.text = "$interval segundo(s)"
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }.start()
    }
    
    private fun showBroadcastConfigDialog() {
        val currentInterval = tvBroadcastInterval.text.toString().replace(" segundo(s)", "").toIntOrNull() ?: 1
        
        val input = android.widget.EditText(this)
        input.inputType = android.text.InputType.TYPE_CLASS_NUMBER
        input.setText(currentInterval.toString())
        input.selectAll()
        
        AlertDialog.Builder(this)
            .setTitle("Configurar Intervalo de Broadcast")
            .setMessage("Ingresa el intervalo de broadcast en segundos (1-300):")
            .setView(input)
            .setPositiveButton("Guardar") { _, _ ->
                val newInterval = input.text.toString().toIntOrNull()
                if (newInterval != null && newInterval >= 1 && newInterval <= 300) {
                    updateBroadcastInterval(newInterval)
                } else {
                    Toast.makeText(this, "Por favor ingresa un valor válido entre 1 y 300", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }
    
    private fun updateBroadcastInterval(interval: Int) {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                val resultJson = module.callAttr("set_server_config", interval).toString()
                
                val result = org.json.JSONObject(resultJson)
                val success = result.optBoolean("success", false)
                
                runOnUiThread {
                    if (success) {
                        tvBroadcastInterval.text = "$interval segundo(s)"
                        Toast.makeText(this, "Intervalo de broadcast actualizado a $interval segundo(s)", Toast.LENGTH_SHORT).show()
                    } else {
                        val message = result.optString("message", "Error al actualizar")
                        Toast.makeText(this, "Error: $message", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
                runOnUiThread {
                    Toast.makeText(this, "Error al actualizar configuración", Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }

    private fun loadClients() {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                val clientsJson = module.callAttr("get_clients_json").toString()
                
                val clients = ClientAdapter.parseClientsFromJson(clientsJson)
                
                runOnUiThread {
                    tvClientCount.text = clients.size.toString()
                    
                    if (clients.isEmpty()) {
                        recyclerClients.visibility = View.GONE
                        emptyState.visibility = View.VISIBLE
                    } else {
                        recyclerClients.visibility = View.VISIBLE
                        emptyState.visibility = View.GONE
                        clientAdapter.updateClients(clients)
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
                runOnUiThread {
                    Toast.makeText(this, "Error al cargar clientes", Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }

    private fun setClientTime(clientId: String, time: Int, unit: String) {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                val resultJson = module.callAttr("set_client_time", clientId, time, unit).toString()
                
                val result = JSONObject(resultJson)
                val success = result.optBoolean("success", false)
                val message = result.optString("message", "")
                
                runOnUiThread {
                    if (success) {
                        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
                        loadClients()
                    } else {
                        Toast.makeText(this, "Error: $message", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this, "Error al establecer tiempo", Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }

    private fun stopClientSession(clientId: String) {
        AlertDialog.Builder(this)
            .setTitle("Detener sesión")
            .setMessage("¿Detener la sesión de este cliente?")
            .setPositiveButton("Detener") { _, _ ->
                Thread {
                    try {
                        val py = Python.getInstance()
                        val module = py.getModule("cibermonday_android")
                        val resultJson = module.callAttr("stop_client_session", clientId).toString()
                        
                        val result = JSONObject(resultJson)
                        val success = result.optBoolean("success", false)
                        
                        runOnUiThread {
                            if (success) {
                                Toast.makeText(this, "Sesión detenida", Toast.LENGTH_SHORT).show()
                                loadClients()
                            } else {
                                Toast.makeText(this, "Error al detener sesión", Toast.LENGTH_SHORT).show()
                            }
                        }
                    } catch (e: Exception) {
                        runOnUiThread {
                            Toast.makeText(this, "Error", Toast.LENGTH_SHORT).show()
                        }
                    }
                }.start()
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun confirmDeleteClient(clientId: String) {
        AlertDialog.Builder(this)
            .setTitle("Eliminar cliente")
            .setMessage("¿Eliminar este cliente permanentemente?")
            .setPositiveButton("Eliminar") { _, _ ->
                deleteClient(clientId)
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun deleteClient(clientId: String) {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                val resultJson = module.callAttr("delete_client", clientId).toString()
                
                val result = JSONObject(resultJson)
                val success = result.optBoolean("success", false)
                
                runOnUiThread {
                    if (success) {
                        Toast.makeText(this, "Cliente eliminado", Toast.LENGTH_SHORT).show()
                        loadClients()
                    } else {
                        Toast.makeText(this, "Error al eliminar cliente", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this, "Error", Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }

    override fun onResume() {
        super.onResume()
        handler.post(refreshRunnable)
    }

    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(refreshRunnable)
    }

    private fun editClientName(clientId: String, newName: String) {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                val resultJson = module.callAttr("set_client_name", clientId, newName).toString()
                
                val result = JSONObject(resultJson)
                val success = result.optBoolean("success", false)
                val message = result.optString("message", "")
                
                runOnUiThread {
                    if (success) {
                        Toast.makeText(this, "Nombre actualizado", Toast.LENGTH_SHORT).show()
                        loadClients()
                    } else {
                        Toast.makeText(this, "Error: $message", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this, "Error al actualizar nombre", Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }

    private fun saveClientConfig(clientId: String, syncInterval: Int, alertThresholds: List<Int>) {
        Thread {
            try {
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                
                // Convertir la lista de Kotlin a una lista de Python
                // Chaquopy puede manejar listas directamente, pero mejor convertir a array
                val alertArray = alertThresholds.toTypedArray()
                
                // Llamar a la función wrapper set_client_config
                val resultJson = module.callAttr("set_client_config", 
                    clientId, 
                    syncInterval, 
                    alertArray
                ).toString()
                
                val result = JSONObject(resultJson)
                val success = result.optBoolean("success", false)
                val message = result.optString("message", "")
                
                runOnUiThread {
                    if (success) {
                        Toast.makeText(this, "Configuración guardada", Toast.LENGTH_SHORT).show()
                        loadClients()
                    } else {
                        Toast.makeText(this, "Error: $message", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
                runOnUiThread {
                    Toast.makeText(this, "Error al guardar configuración: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }
}
