package com.siteview.app.data

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import com.siteview.app.BuildConfig
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * بروزرسانی خودکار از GitHub Releases.
 * تگ هر انتشار باید عدد versionCode باشد (مثلاً "3") و فایل APK ضمیمه شود.
 */
object Updater {

    // مخزن گیت‌هاب — بعد از ساخت مخزن مقداردهی شده
    const val REPO = "hosseinmashayekhi/siteview"

    data class UpdateInfo(val versionCode: Int, val apkUrl: String, val title: String)

    /** null یعنی نسخه‌ی جدیدی موجود نیست یا خطا رخ داده. */
    fun checkForUpdate(): UpdateInfo? {
        return try {
            val conn = URL("https://api.github.com/repos/$REPO/releases/latest")
                .openConnection() as HttpURLConnection
            conn.setRequestProperty("User-Agent", "SiteView-App")
            conn.setRequestProperty("Accept", "application/vnd.github+json")
            conn.connectTimeout = 10_000
            conn.readTimeout = 10_000
            val body = conn.inputStream.use { it.readBytes().decodeToString() }
            conn.disconnect()

            val json = JSONObject(body)
            val versionCode = json.getString("tag_name").trim().toIntOrNull() ?: return null
            if (versionCode <= BuildConfig.VERSION_CODE) return null

            val assets = json.getJSONArray("assets")
            var apkUrl: String? = null
            for (i in 0 until assets.length()) {
                val asset = assets.getJSONObject(i)
                if (asset.getString("name").endsWith(".apk")) {
                    apkUrl = asset.getString("browser_download_url")
                    break
                }
            }
            if (apkUrl == null) return null
            UpdateInfo(versionCode, apkUrl, json.optString("name", "نسخه‌ی جدید"))
        } catch (_: Exception) {
            null
        }
    }

    /** دانلود APK در حافظه‌ی داخلی اپ. */
    fun downloadApk(context: Context, info: UpdateInfo): File? {
        return try {
            val dir = File(context.filesDir, "updates").apply { mkdirs() }
            dir.listFiles()?.forEach { it.delete() }
            val file = File(dir, "update-${info.versionCode}.apk")
            val conn = URL(info.apkUrl).openConnection() as HttpURLConnection
            conn.setRequestProperty("User-Agent", "SiteView-App")
            conn.connectTimeout = 15_000
            conn.readTimeout = 60_000
            conn.inputStream.use { input ->
                file.outputStream().use { input.copyTo(it) }
            }
            conn.disconnect()
            file
        } catch (_: Exception) {
            null
        }
    }

    /** باز کردن نصب‌کننده‌ی اندروید برای APK دانلودشده. */
    fun promptInstall(context: Context, apk: File) {
        val uri = FileProvider.getUriForFile(
            context, context.packageName + ".fileprovider", apk
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }
}
