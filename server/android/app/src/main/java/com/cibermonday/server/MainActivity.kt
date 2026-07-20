package com.cibermonday.server

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.app.AlertDialog
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * Shell del servidor Android: el HTTP solo corre en primer plano (ahorro de batería).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var overlay: FrameLayout
    private lateinit var loading: ProgressBar
    private lateinit var statusText: TextView
    private lateinit var retryButton: Button

    private val handler = Handler(Looper.getMainLooper())
    private var healthAttempts = 0
    private val maxHealthAttempts = 60
    private val panelUrl = "http://127.0.0.1:5000/"

    /** true mientras la Activity está visible (entre onStart y onStop). */
    private var inForeground = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.parseColor("#F0F2F5"))
        }
        webView = WebView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
            visibility = View.INVISIBLE
        }
        loading = ProgressBar(this).apply { isIndeterminate = true }
        statusText = TextView(this).apply {
            text = "Iniciando servidor…"
            setTextColor(Color.parseColor("#5F6368"))
            textSize = 14f
            gravity = Gravity.CENTER
        }
        retryButton = Button(this).apply {
            text = "Reintentar"
            isVisible = false
            setOnClickListener {
                if (!inForeground) return@setOnClickListener
                isVisible = false
                loading.isVisible = true
                healthAttempts = 0
                startServerService()
                waitForHealthThenLoad()
            }
        }

        val centerColumn = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            addView(
                loading,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = 24 }
            )
            addView(
                statusText,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply {
                    leftMargin = 48
                    rightMargin = 48
                }
            )
            addView(
                retryButton,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = 32 }
            )
        }

        overlay = FrameLayout(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
            addView(
                centerColumn,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.CENTER
                )
            )
        }

        root.addView(webView)
        root.addView(overlay)
        setContentView(root)

        val settings: WebSettings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.cacheMode = WebSettings.LOAD_NO_CACHE
        webView.setBackgroundColor(Color.parseColor("#F0F2F5"))
        // Sin WebChromeClient, alert/confirm de JS fallan en WebView (Detener, Eliminar, etc.)
        webView.webChromeClient = object : WebChromeClient() {
            override fun onJsAlert(
                view: WebView?,
                url: String?,
                message: String?,
                result: JsResult?,
            ): Boolean {
                AlertDialog.Builder(this@MainActivity)
                    .setMessage(message ?: "")
                    .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                    .setOnCancelListener { result?.cancel() }
                    .show()
                return true
            }

            override fun onJsConfirm(
                view: WebView?,
                url: String?,
                message: String?,
                result: JsResult?,
            ): Boolean {
                AlertDialog.Builder(this@MainActivity)
                    .setMessage(message ?: "")
                    .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                    .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                    .setOnCancelListener { result?.cancel() }
                    .show()
                return true
            }
        }
        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                if (!inForeground) return
                webView.visibility = View.VISIBLE
                overlay.isVisible = false
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?,
            ) {
                if (!inForeground) return
                if (request?.isForMainFrame == true) {
                    statusText.text = "Error cargando panel. Reintentando…"
                    overlay.isVisible = true
                    handler.postDelayed({
                        if (inForeground) webView.loadUrl(panelUrl)
                    }, 1500)
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        inForeground = true
        showStartingUi()
        startServerService()
        waitForHealthThenLoad()
    }

    override fun onStop() {
        inForeground = false
        handler.removeCallbacksAndMessages(null)
        stopServerService()
        webView.visibility = View.INVISIBLE
        overlay.isVisible = true
        loading.isVisible = false
        retryButton.isVisible = false
        statusText.text =
            "Servidor apagado (ahorro de batería).\nVolvé a abrir la app para reactivarlo."
        super.onStop()
    }

    private fun startServerService() {
        startForegroundService(Intent(this, FlaskServerService::class.java))
    }

    private fun stopServerService() {
        stopService(Intent(this, FlaskServerService::class.java))
    }

    private fun showStartingUi() {
        healthAttempts = 0
        webView.visibility = View.INVISIBLE
        overlay.isVisible = true
        loading.isVisible = true
        retryButton.isVisible = false
        statusText.text = "Iniciando servidor…"
    }

    private fun waitForHealthThenLoad() {
        if (!inForeground) return
        healthAttempts++
        statusText.text = "Esperando API… ($healthAttempts)"
        thread {
            val ok = try {
                val conn = URL("http://127.0.0.1:5000/api/health")
                    .openConnection() as HttpURLConnection
                conn.connectTimeout = 1500
                conn.readTimeout = 1500
                conn.requestMethod = "GET"
                val code = conn.responseCode
                conn.disconnect()
                code in 200..299
            } catch (_: Exception) {
                false
            }
            handler.post {
                if (!inForeground) return@post
                if (ok) {
                    statusText.text = "Cargando panel…"
                    webView.loadUrl(panelUrl)
                } else if (healthAttempts < maxHealthAttempts) {
                    handler.postDelayed({ waitForHealthThenLoad() }, 500)
                } else {
                    statusText.text =
                        "No se pudo iniciar el servidor en el puerto 5000.\nTocá Reintentar."
                    loading.isVisible = false
                    retryButton.isVisible = true
                }
            }
        }
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        stopServerService()
        webView.destroy()
        super.onDestroy()
    }
}
