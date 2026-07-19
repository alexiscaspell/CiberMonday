package com.cibermonday.client.ui

import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity
import com.cibermonday.client.R
import com.cibermonday.client.lock.LockController
import com.cibermonday.client.lock.LockOverlayService

/**
 * Pantalla de "tiempo agotado". No mantiene la pantalla encendida:
 * el usuario puede apagarla; al volver a desbloquear se reabre.
 */
class LockActivity : AppCompatActivity() {

    private lateinit var lockController: LockController
    private val handler = Handler(Looper.getMainLooper())
    private val sessionCheck = object : Runnable {
        override fun run() {
            if (!lockController.isLockNeeded()) {
                LockOverlayService.stop(this@LockActivity)
                finish()
                return
            }
            handler.postDelayed(this, 2_000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lockController = LockController(this)

        // Mostrar sobre el keyguard, pero SIN encender ni mantener la pantalla
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(false)
        }
        @Suppress("DEPRECATION")
        window.addFlags(
            WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_FULLSCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
        )
        window.clearFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
        )
        window.decorView.systemUiVisibility =
            (View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE)

        setContentView(R.layout.activity_lock)

        if (!lockController.isLockNeeded()) {
            finish()
            return
        }
        LockOverlayService.start(this)
    }

    override fun onResume() {
        super.onResume()
        if (!lockController.isLockNeeded()) {
            finish()
            return
        }
        handler.removeCallbacks(sessionCheck)
        handler.post(sessionCheck)
    }

    override fun onPause() {
        // No re-lanzar al pausar: eso despierta la pantalla al apagarla
        handler.removeCallbacks(sessionCheck)
        super.onPause()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            window.decorView.systemUiVisibility =
                (View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_FULLSCREEN)
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        // Bloquear atrás
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_HOME,
            KeyEvent.KEYCODE_APP_SWITCH,
            KeyEvent.KEYCODE_BACK,
            KeyEvent.KEYCODE_MENU -> true
            else -> super.onKeyDown(keyCode, event)
        }
    }

    override fun onDestroy() {
        handler.removeCallbacks(sessionCheck)
        super.onDestroy()
    }
}
