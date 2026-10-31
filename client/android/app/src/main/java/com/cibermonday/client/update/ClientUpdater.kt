package com.cibermonday.client.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * Descarga el APK del cliente desde GitHub Releases e inicia el instalador del sistema.
 */
object ClientUpdater {

    const val GITHUB_REPO = "alexiscaspell/CiberMonday"
    private const val API_RELEASES = "https://api.github.com/repos/$GITHUB_REPO/releases"
    private const val UA = "CiberMondayClient-Updater/1.0"

    data class ReleaseInfo(
        val tag: String,
        val version: String,
        val prerelease: Boolean,
        val apkName: String,
        val downloadUrl: String,
    )

    fun tagToVersion(tag: String): String =
        tag.trim().removePrefix("v").removePrefix("V")

    fun pickRelease(allowPrerelease: Boolean): ReleaseInfo {
        val arr = getJsonArray("$API_RELEASES?per_page=30")
        for (i in 0 until arr.length()) {
            val rel = arr.getJSONObject(i)
            if (rel.optBoolean("draft", false)) continue
            if (!allowPrerelease && rel.optBoolean("prerelease", false)) continue
            val assets = rel.optJSONArray("assets") ?: continue
            val apk = findApkAsset(assets) ?: continue
            val tag = rel.optString("tag_name", "")
            return ReleaseInfo(
                tag = tag,
                version = tagToVersion(tag),
                prerelease = rel.optBoolean("prerelease", false),
                apkName = apk.getString("name"),
                downloadUrl = apk.getString("browser_download_url"),
            )
        }
        val kind = if (allowPrerelease) "prerelease o stable" else "stable"
        throw IllegalStateException("No hay release $kind con APK en GitHub")
    }

    private fun findApkAsset(assets: JSONArray): JSONObject? {
        for (i in 0 until assets.length()) {
            val a = assets.getJSONObject(i)
            val name = a.optString("name", "")
            if (name.startsWith("CiberMondayClient-") && name.endsWith(".apk") &&
                !name.contains("Server", ignoreCase = true)
            ) {
                return a
            }
        }
        return null
    }

    fun downloadApk(context: Context, info: ReleaseInfo, onProgress: ((String) -> Unit)? = null): File {
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        val dest = File(dir, info.apkName)
        if (dest.exists()) dest.delete()
        onProgress?.invoke("Descargando ${info.apkName}…")
        val conn = (URL(info.downloadUrl).openConnection() as HttpURLConnection).apply {
            connectTimeout = 30_000
            readTimeout = 120_000
            setRequestProperty("User-Agent", UA)
            instanceFollowRedirects = true
        }
        try {
            if (conn.responseCode !in 200..299) {
                throw IllegalStateException("HTTP ${conn.responseCode} al descargar APK")
            }
            val total = conn.contentLengthLong.takeIf { it > 0 } ?: 0L
            var done = 0L
            conn.inputStream.use { input ->
                FileOutputStream(dest).use { out ->
                    val buf = ByteArray(256 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        out.write(buf, 0, n)
                        done += n
                        if (total > 0) {
                            val pct = (100 * done / total).toInt()
                            onProgress?.invoke("Descargando… $pct%")
                        }
                    }
                }
            }
        } finally {
            conn.disconnect()
        }
        onProgress?.invoke("Descarga completa")
        return dest
    }

    fun canRequestInstallPermission(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return true
        return context.packageManager.canRequestPackageInstalls()
    }

    fun installPermissionSettingsIntent(context: Context): Intent {
        return Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:${context.packageName}"),
        )
    }

    fun launchInstaller(context: Context, apkFile: File) {
        val uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            apkFile,
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    fun runUpdateAsync(
        context: Context,
        allowPrerelease: Boolean,
        onProgress: (String) -> Unit,
        onDone: (ReleaseInfo?, File?, Exception?) -> Unit,
    ) {
        val appCtx = context.applicationContext
        Executors.newSingleThreadExecutor().execute {
            try {
                onProgress("Buscando release…")
                val info = pickRelease(allowPrerelease)
                onProgress("Release: ${info.tag}")
                val file = downloadApk(appCtx, info, onProgress)
                onDone(info, file, null)
            } catch (e: Exception) {
                onDone(null, null, e)
            }
        }
    }

    private fun getJsonArray(url: String): JSONArray {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 20_000
            readTimeout = 30_000
            setRequestProperty("User-Agent", UA)
            setRequestProperty("Accept", "application/vnd.github+json")
        }
        try {
            if (conn.responseCode !in 200..299) {
                throw IllegalStateException("GitHub API HTTP ${conn.responseCode}")
            }
            val text = conn.inputStream.bufferedReader().use { it.readText() }
            return JSONArray(text)
        } finally {
            conn.disconnect()
        }
    }
}
