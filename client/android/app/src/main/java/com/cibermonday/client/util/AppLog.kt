package com.cibermonday.client.util

import android.content.Context
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * Log a logcat + archivo persistente (filesDir/logs/CiberMondayClient.log).
 * Expuesto vía GET /api/logs en el PushServer.
 */
object AppLog {
    private const val FILE_NAME = "CiberMondayClient.log"
    private const val MAX_BYTES = 5L * 1024L * 1024L
    private val lock = ReentrantLock()
    private var logFile: File? = null
    private val ts = ThreadLocal.withInitial {
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)
    }

    fun init(context: Context) {
        val dir = File(context.filesDir, "logs").apply { mkdirs() }
        logFile = File(dir, FILE_NAME)
        i("AppLog", "file=${logFile?.absolutePath}")
    }

    fun path(): String? = logFile?.absolutePath

    fun v(tag: String, msg: String) = write(Log.VERBOSE, "V", tag, msg, null)
    fun d(tag: String, msg: String) = write(Log.DEBUG, "D", tag, msg, null)
    fun i(tag: String, msg: String) = write(Log.INFO, "I", tag, msg, null)
    fun w(tag: String, msg: String, tr: Throwable? = null) = write(Log.WARN, "W", tag, msg, tr)
    fun e(tag: String, msg: String, tr: Throwable? = null) = write(Log.ERROR, "E", tag, msg, tr)

    fun tail(lines: Int = 100): List<String> {
        val file = logFile ?: return emptyList()
        if (!file.isFile) return emptyList()
        val n = lines.coerceIn(1, 2000)
        return lock.withLock {
            try {
                RandomAccessFile(file, "r").use { raf ->
                    var pos = raf.length()
                    var count = 0
                    val buf = ArrayList<Byte>()
                    while (pos > 0L && count <= n) {
                        pos--
                        raf.seek(pos)
                        val b = raf.readByte()
                        if (b == '\n'.code.toByte() && buf.isNotEmpty()) {
                            count++
                            if (count > n) break
                        }
                        buf.add(b)
                    }
                    buf.reverse()
                    String(buf.toByteArray(), Charsets.UTF_8)
                        .split('\n')
                        .map { it.trimEnd('\r') }
                        .filter { it.isNotEmpty() }
                        .takeLast(n)
                }
            } catch (_: Exception) {
                emptyList()
            }
        }
    }

    private fun write(level: Int, levelChar: String, tag: String, msg: String, tr: Throwable?) {
        if (tr != null) {
            when (level) {
                Log.WARN -> Log.w(tag, msg, tr)
                Log.ERROR -> Log.e(tag, msg, tr)
                else -> Log.println(level, tag, msg)
            }
        } else {
            Log.println(level, tag, msg)
        }
        val file = logFile ?: return
        val stamp = ts.get()?.format(Date()) ?: ""
        val extra = if (tr != null) "\n" + Log.getStackTraceString(tr) else ""
        val line = "$stamp $levelChar/$tag: $msg$extra\n"
        lock.withLock {
            try {
                rotateIfNeeded(file)
                FileOutputStream(file, true).use { it.write(line.toByteArray(Charsets.UTF_8)) }
            } catch (_: Exception) {
            }
        }
    }

    private fun rotateIfNeeded(file: File) {
        if (file.length() <= MAX_BYTES) return
        val bak = File(file.parentFile, "$FILE_NAME.old")
        if (bak.exists()) bak.delete()
        file.renameTo(bak)
    }
}
