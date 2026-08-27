package com.siteview.app.data

import android.util.Log
import java.io.File

/**
 * پل به خط لوله‌ی ترکیب پانورامای OpenCV (کد native):
 * نگاشت کروی + جبران نور + خط درز بهینه + ادغام چندباندی.
 * زاویه‌های دوربین از [PanoramaComposer] می‌آیند.
 */
object NativeStitcher {

    private val loaded: Boolean = try {
        System.loadLibrary("panostitch")
        true
    } catch (e: UnsatisfiedLinkError) {
        Log.e("NativeStitcher", "native lib not available", e)
        false
    }

    private external fun nativeCompose(
        paths: Array<String>,
        yprRadians: FloatArray,
        fRel: Float,
        outPath: String,
        canvasW: Int,
        maxDim: Int,
    ): Int

    val isAvailable: Boolean get() = loaded

    /**
     * ترکیب فریم‌ها با زاویه‌های داده‌شده (رادیان، ۳تایی به‌ازای هر فریم)
     * و ذخیره‌ی equirectangular کامل در [output]. false یعنی برو سراغ روش جایگزین.
     */
    fun compose(
        files: List<File>,
        yprRadians: FloatArray,
        fRel: Float,
        output: File,
        canvasW: Int = 4096,
    ): Boolean {
        if (!loaded || files.size < 2) return false
        val status = try {
            nativeCompose(
                files.map { it.absolutePath }.toTypedArray(),
                yprRadians, fRel, output.absolutePath, canvasW, 1280,
            )
        } catch (e: Throwable) {
            Log.e("NativeStitcher", "compose crashed", e)
            -999
        }
        Log.d("NativeStitcher", "compose status=$status")
        return status == 0 && output.exists()
    }
}
