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
            // No reiniciar en background: solo mientras la Activity lo pide
            return START_NOT_STICKY
        }
        
        // Iniciar como servicio foreground
        val notification = createNotification("Servidor activo en puerto 5000")
        startForeground(NOTIFICATION_ID, notification)

        // Wake lock solo mientras el servidor corre (se libera al salir de primer plano)
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        if (wakeLock?.isHeld != true) {
            wakeLock = powerManager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "CiberMonday::ServerWakeLock"
            )
            wakeLock?.acquire(60 * 60 * 1000L) // máximo 1h por sesión en primer plano
        }

        startServer()

        return START_NOT_STICKY
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
                
                android.util.Log.i("CiberMonday", "Módulo Python cargado, llamando start_server...")
                
                // Siempre 0.0.0.0: accesible por LAN y por 127.0.0.1 (WebView / health check)
                val host = "0.0.0.0"
                android.util.Log.i("CiberMonday", "Iniciando servidor en $host:5000 (wifi=$localIp)")
                module.callAttr("start_server", host, 5000, filesDir.absolutePath)
                
                android.util.Log.i("CiberMonday", "start_server terminó (no debería pasar)")
                
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
            Thread.sleep(2000)
            
            if (isRunning) {
                var serverReady = false
                for (attempt in 1..15) {
                    try {
                        android.util.Log.i("CiberMonday", "Verificando servidor en 127.0.0.1:5000, intento $attempt...")
                        val socket = java.net.Socket()
                        socket.connect(java.net.InetSocketAddress("127.0.0.1", 5000), 1000)
                        socket.close()
                        serverReady = true
                        android.util.Log.i("CiberMonday", "Servidor respondiendo en 127.0.0.1:5000")
                        break
                    } catch (e: Exception) {
                        android.util.Log.w("CiberMonday", "Servidor no listo aún: ${e.message}")
                        Thread.sleep(1000)
                    }
                }
                
                if (serverReady) {
                    sendBroadcast(Intent(ACTION_SERVER_STARTED))
                    updateNotification("Servidor activo en puerto 5000")
                } else {
                    android.util.Log.e("CiberMonday", "Servidor no respondió después de 15 intentos")
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

    private fun releaseWakeLock() {
        try {
            wakeLock?.let { lock ->
                if (lock.isHeld) lock.release()
            }
        } catch (_: Exception) {
        }
        wakeLock = null
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
        stopServer()
        releaseWakeLock()
        sendBroadcast(Intent(ACTION_SERVER_STOPPED))
        super.onDestroy()
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
