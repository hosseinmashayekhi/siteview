package com.siteview.app.data

import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs

/** یک نقطه‌ی عکس‌برداری روی پلان. مختصات x و y نسبی هستند (۰ تا ۱). */
data class CapturePoint(val id: Long, val name: String, val x: Float, val y: Float)

/** یک عکس ثبت‌شده در یک نقطه، در یک تاریخ مشخص. */
data class Capture(
    val id: Long,
    val pointId: Long,
    val takenAt: Long,
    val fileName: String,
    val is360: Boolean,
)

fun formatDate(ts: Long): String =
    SimpleDateFormat("yyyy/MM/dd  HH:mm", Locale.getDefault()).format(Date(ts))

/**
 * ذخیره‌سازی محلی ساده با JSON — بعداً همین مدل بدون تغییر به سرور منتقل می‌شود.
 */
class Store(private val context: Context) {

    val points = mutableStateListOf<CapturePoint>()
    val captures = mutableStateListOf<Capture>()

    var planBitmap by mutableStateOf<ImageBitmap?>(null)
        private set

    private val dataFile = File(context.filesDir, "data.json")
    private val planFile = File(context.filesDir, "plan.png")
    val photosDir = File(context.filesDir, "photos").apply { mkdirs() }

    init {
        load()
        loadPlan()
    }

    fun photoFile(capture: Capture): File = File(photosDir, capture.fileName)

    fun newPhotoFile(): File = File(photosDir, "IMG_${System.currentTimeMillis()}.jpg")

    fun addPoint(name: String, x: Float, y: Float) {
        points.add(CapturePoint(System.currentTimeMillis(), name, x, y))
        save()
    }

    fun removePoint(point: CapturePoint) {
        captures.filter { it.pointId == point.id }.forEach { photoFile(it).delete() }
        captures.removeAll { it.pointId == point.id }
        points.remove(point)
        save()
    }

    fun addCapture(pointId: Long, file: File, is360: Boolean) {
        captures.add(
            Capture(
                id = System.currentTimeMillis(),
                pointId = pointId,
                takenAt = System.currentTimeMillis(),
                fileName = file.name,
                is360 = is360,
            )
        )
        save()
    }

    /**
     * ورود عکس از گالری. اگر نسبت تصویر ۲:۱ باشد، خودکار به‌عنوان
     * عکس 360 (equirectangular) علامت می‌خورد.
     */
    fun importImage(uri: Uri, pointId: Long) {
        val file = newPhotoFile()
        context.contentResolver.openInputStream(uri)?.use { input ->
            file.outputStream().use { input.copyTo(it) }
        } ?: return
        val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, opts)
        val is360 = opts.outWidth > 0 &&
            abs(opts.outWidth - 2 * opts.outHeight) <= opts.outWidth * 0.03f
        addCapture(pointId, file, is360)
    }

    /** تغییر دستی حالت ۳۶۰ یک عکس — برای وقتی تشخیص خودکار اشتباه می‌کند. */
    fun setIs360(capture: Capture, value: Boolean) {
        val i = captures.indexOfFirst { it.id == capture.id }
        if (i >= 0) {
            captures[i] = captures[i].copy(is360 = value)
            save()
        }
    }

    fun setPlan(uri: Uri) {
        context.contentResolver.openInputStream(uri)?.use { input ->
            planFile.outputStream().use { input.copyTo(it) }
        } ?: return
        loadPlan()
    }

    private fun loadPlan() {
        planBitmap = if (planFile.exists()) {
            BitmapFactory.decodeFile(planFile.absolutePath)?.asImageBitmap()
        } else {
            context.assets.open("sample_plan.png").use { stream ->
                BitmapFactory.decodeStream(stream)?.asImageBitmap()
            }
        }
    }

    private fun load() {
        if (!dataFile.exists()) return
        try {
            val root = JSONObject(dataFile.readText())
            val ps = root.getJSONArray("points")
            for (i in 0 until ps.length()) {
                val o = ps.getJSONObject(i)
                points.add(
                    CapturePoint(
                        id = o.getLong("id"),
                        name = o.getString("name"),
                        x = o.getDouble("x").toFloat(),
                        y = o.getDouble("y").toFloat(),
                    )
                )
            }
            val cs = root.getJSONArray("captures")
            for (i in 0 until cs.length()) {
                val o = cs.getJSONObject(i)
                captures.add(
                    Capture(
                        id = o.getLong("id"),
                        pointId = o.getLong("pointId"),
                        takenAt = o.getLong("takenAt"),
                        fileName = o.getString("fileName"),
                        is360 = o.getBoolean("is360"),
                    )
                )
            }
        } catch (_: Exception) {
            // فایل خراب — از صفر شروع می‌کنیم
        }
    }

    private fun save() {
        val root = JSONObject()
        root.put("points", JSONArray().apply {
            points.forEach { p ->
                put(
                    JSONObject()
                        .put("id", p.id)
                        .put("name", p.name)
                        .put("x", p.x.toDouble())
                        .put("y", p.y.toDouble())
                )
            }
        })
        root.put("captures", JSONArray().apply {
            captures.forEach { c ->
                put(
                    JSONObject()
                        .put("id", c.id)
                        .put("pointId", c.pointId)
                        .put("takenAt", c.takenAt)
                        .put("fileName", c.fileName)
                        .put("is360", c.is360)
                )
            }
        })
        dataFile.writeText(root.toString())
    }
}
