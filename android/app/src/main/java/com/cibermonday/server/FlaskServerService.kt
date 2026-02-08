package com.cibermonday.server

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlin.concurrent.thread
import java.net.NetworkInterface
import java.net.InetAddress

class FlaskServerService : Service() {

    companion object {
        const val CHANNEL_ID = "CiberMondayServerChannel"
        const val NOTIFICATION_ID = 1
        const val ACTION_SERVER_STARTED = "com.cibermonday.server.SERVER_STARTED"
        const val ACTION_SERVER_STOPPED = "com.cibermonday.server.SERVER_STOPPED"
        const val ACTION_SERVER_ERROR = "com.cibermonday.server.SERVER_ERROR"
    }

    private var serverThread: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var isRunning = false

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        
        // Inicializar Python si no está inicializado
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (isRunning) {
            return START_STICKY
        }
        
        // Iniciar como servicio foreground
        val notification = createNotification("Servidor activo en puerto 5000")
        startForeground(NOTIFICATION_ID, notification)

        // Adquirir wake lock para mantener el servidor activo
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "CiberMonday::ServerWakeLock"
        )
        wakeLock?.acquire(10 * 60 * 60 * 1000L) // 10 horas máximo

        // Iniciar servidor en un thread separado
        startServer()

        return START_STICKY
    }

    private fun startServer() {
        if (isRunning) return
        isRunning = true

        serverThread = thread {
            try {
                android.util.Log.d("CiberMonday", "Iniciando servidor Flask...")
                
                val py = Python.getInstance()
                val module = py.getModule("cibermonday_android")
                
                // Obtener la IP local de la interfaz WiFi
                val localIp = getLocalIpAddress()
                android.util.Log.d("CiberMonday", "IP local detectada: $localIp")
                
                android.util.Log.d("CiberMonday", "Módulo Python cargado, llamando start_server...")
                
                // Iniciar el servidor en la IP local específica (no 0.0.0.0)
                // Esto permite que otros dispositivos en la red puedan conectarse
                val host = if (localIp.isNotEmpty() && localIp != "127.0.0.1") localIp else "0.0.0.0"
                android.util.Log.d("CiberMonday", "Iniciando servidor en $host:5000")
                module.callAttr("start_server", host, 5000, filesDir.absolutePath)
                
                android.util.Log.d("CiberMonday", "start_server terminó (no debería pasar)")
                
            } catch (e: Exception) {
                android.util.Log.e("CiberMonday", "Error al iniciar servidor: ${e.message}", e)
                e.printStackTrace()
                isRunning = false
                
                val errorIntent = Intent(ACTION_SERVER_ERROR)
                errorIntent.putExtra("error", e.message ?: "Error desconocido")
                sendBroadcast(errorIntent)
            }
        }
        
        // Verificar que el servidor realmente esté escuchando
        thread {
            Thread.sleep(3000) // Dar más tiempo a Flask para iniciar
            
            if (isRunning) {
                // Obtener la IP donde se inició el servidor
                val localIp = getLocalIpAddress()
                val host = if (localIp.isNotEmpty() && localIp != "127.0.0.1") localIp else "127.0.0.1"
                
                // Intentar conectar al servidor
                var serverReady = false
                for (attempt in 1..10) {
                    try {
                        android.util.Log.d("CiberMonday", "Verificando servidor en $host, intento $attempt...")
                        val socket = java.net.Socket()
                        socket.connect(java.net.InetSocketAddress(host, 5000), 1000)
                        socket.close()
                        serverReady = true
                        android.util.Log.d("CiberMonday", "Servidor respondiendo correctamente en $host")
                        break
                    } catch (e: Exception) {
                        android.util.Log.d("CiberMonday", "Servidor no listo aún: ${e.message}")
                        Thread.sleep(1000)
                    }
                }
                
                if (serverReady) {
                    sendBroadcast(Intent(ACTION_SERVER_STARTED))
                    updateNotification("Servidor activo en puerto 5000")
                } else {
                    android.util.Log.e("CiberMonday", "Servidor no respondió después de 10 intentos")
                    val errorIntent = Intent(ACTION_SERVER_ERROR)
                    errorIntent.putExtra("error", "El servidor no respondió")
                    sendBroadcast(errorIntent)
                }
            }
        }
    }

    private fun stopServer() {
        isRunning = false
        try {
            val py = Python.getInstance()
            val module = py.getModule("cibermonday_android")
            module.callAttr("stop_server")
        } catch (e: Exception) {
            e.printStackTrace()
        }
        serverThread?.interrupt()
        serverThread = null
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "CiberMonday Server",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Servidor CiberMonday activo"
                setShowBadge(false)
            }
            
            val notificationManager = getSystemService(NotificationManager::class.java)
            notificationManager.createNotificationChannel(channel)
        }
    }

    private fun createNotification(content: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("CiberMonday Server")
            .setContentText(content)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun updateNotification(content: String) {
        val notification = createNotification(content)
        val notificationManager = getSystemService(NotificationManager::class.java)
        notificationManager.notify(NOTIFICATION_ID, notification)
    }

    override fun onDestroy() {
        super.onDestroy()
        stopServer()
        wakeLock?.release()
        sendBroadcast(Intent(ACTION_SERVER_STOPPED))
    }

    override fun onBind(intent: Intent?): IBinder? = null
    
    private fun getLocalIpAddress(): String {
        var wifiIp: String? = null
        var mobileIp: String? = null
        
        try {
            val interfaces = NetworkInterface.getNetworkInterfaces()
            while (interfaces.hasMoreElements()) {
                val networkInterface = interfaces.nextElement()
                val addresses = networkInterface.inetAddresses
                
                while (addresses.hasMoreElements()) {
                    val address = addresses.nextElement()
                    // Filtrar solo IPv4 y excluir localhost
                    if (!address.isLoopbackAddress && address is InetAddress) {
                        val hostAddress = address.hostAddress
                        // Verificar que sea una dirección IPv4 válida
                        if (hostAddress != null && hostAddress.contains(".")) {
                            val interfaceName = networkInterface.name.lowercase()
                            android.util.Log.d("CiberMonday", "IP encontrada: $hostAddress en interfaz $interfaceName")
                            
                            // Priorizar WiFi sobre datos móviles
                            if (interfaceName.contains("wlan") || interfaceName.contains("wifi") || interfaceName.contains("eth")) {
                                wifiIp = hostAddress
                            } else if (interfaceName.contains("rmnet") || interfaceName.contains("pdp") || interfaceName.contains("ppp")) {
                                if (mobileIp == null) {
                                    mobileIp = hostAddress
                                }
                            } else {
                                // Si no es WiFi ni móvil conocido, guardarlo como fallback
                                if (wifiIp == null && mobileIp == null) {
                                    wifiIp = hostAddress
                                }
                            }
                        }
                    }
                }
            }
            
            // Retornar WiFi si está disponible, sino móvil, sino fallback a ""
            val selectedIp = wifiIp ?: mobileIp ?: ""
            if (selectedIp.isNotEmpty()) {
                android.util.Log.d("CiberMonday", "IP seleccionada para servidor: $selectedIp")
            }
            return selectedIp
            
        } catch (e: Exception) {
            android.util.Log.e("CiberMonday", "Error al obtener IP local: ${e.message}", e)
        }
        return ""
    }
}
