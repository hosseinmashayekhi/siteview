package com.siteview.app.data

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import java.io.File
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan

/** یک فریم گرفته‌شده به‌همراه جهت دقیق گوشی در لحظه‌ی عکاسی. */
data class PanoShot(
    val file: File,
    val yawDeg: Float,
    val pitchDeg: Float,
    val rollDeg: Float,
)

/**
 * ساخت پانورامای 360 (equirectangular) از فریم‌های همپوشان.
 *
 * پایه: زاویه‌های ژیروسکوپ. سپس تطبیق ریز با خود تصاویر:
 * فریم‌های مجاور در فضای استوانه‌ای با همبستگی نرمال‌شده (NCC) تراز می‌شوند تا
 * زاویه‌ی دید واقعی دوربین و خطای ژیروسکوپ اصلاح شود؛ اختلاف روشنایی هم
 * با ضریب بهره‌ی هر فریم جبران می‌شود.
 */
object PanoramaComposer {

    sealed class Result {
        data object Ok : Result()
        data class Failed(val message: String) : Result()
    }

    private const val CANVAS_W = 3072
    private const val CANVAS_H = CANVAS_W / 2
    private const val SHOT_MAX_DIM = 1280
    private const val GRAY_W = 288
    private const val MIN_NCC = 0.30f
    private val MAX_ROLL = Math.toRadians(10.0).toFloat()

    // ---------- ساختارهای داخلی ----------

    private class SrcFrame(
        val px: IntArray, val w: Int, val h: Int,
        val yawGyro: Float, val pitchGyro: Float, val rollGyro: Float,
    )

    private class GrayImg(val g: FloatArray, val w: Int, val h: Int)

    private class MatchResult(
        val dx: Int, val dy: Int, val ncc: Float,
        val meanA: Float, val meanB: Float,
    )

    private class Placement(
        val yaw: Float, val pitch: Float, val roll: Float, val gain: Float,
    )

    // ---------- ورودی اصلی ----------

    suspend fun compose(
        shots: List<PanoShot>,
        hfovDegHint: Float,
        @Suppress("UNUSED_PARAMETER") vfovDegHint: Float,
        output: File,
    ): Result {
        if (shots.size < 2) return Result.Failed("حداقل دو عکس لازم است")

        // ردیف وسط (تراز افق) زنجیره‌ی تطبیق را می‌سازد؛ ردیف‌های بالا/پایین/سقف
        // فقط با زاویه‌های ژیروسکوپ جاگذاری می‌شوند.
        val middleShots = shots.filter { abs(it.pitchDeg) < 20f }.ifEmpty { shots }
        val extraShots = shots.filterNot { it in middleShots }

        val refYaw = middleShots.first().yawDeg
        fun decode(s: PanoShot): SrcFrame? {
            val bmp = decodeUpright(s.file, SHOT_MAX_DIM) ?: return null
            val px = IntArray(bmp.width * bmp.height)
            bmp.getPixels(px, 0, bmp.width, 0, 0, bmp.width, bmp.height)
            val f = SrcFrame(
                px, bmp.width, bmp.height,
                yawGyro = Math.toRadians(unwrapDeg(s.yawDeg - refYaw).toDouble()).toFloat(),
                pitchGyro = Math.toRadians(s.pitchDeg.toDouble()).toFloat(),
                rollGyro = Math.toRadians(s.rollDeg.toDouble())
                    .toFloat().coerceIn(-MAX_ROLL, MAX_ROLL),
            )
            bmp.recycle()
            return f
        }

        val middlePairs = middleShots.mapNotNull { s -> decode(s)?.let { s.file to it } }
        val frames = middlePairs.map { it.second }
        if (frames.size < 2) return Result.Failed("عکس‌ها قابل خواندن نبودند")

        // ---- تطبیق ریز و برآورد زاویه‌ی دید ----
        val grays = frames.map { toGray(it, GRAY_W) }
        var fGray = (GRAY_W / 2f) / tan(Math.toRadians(hfovDegHint / 2.0)).toFloat()

        val n = frames.size
        val fullCircle = n >= 8 &&
            abs(frames.last().yawGyro - frames.first().yawGyro) > Math.toRadians(280.0)
        val pairCount = if (fullCircle) n else n - 1

        var matches: List<MatchResult?> = emptyList()
        var dPsiGyro = FloatArray(0)

        repeat(2) { pass ->
            val cyls = grays.map { cylWarp(it, fGray) }
            dPsiGyro = FloatArray(pairCount)
            val ms = arrayOfNulls<MatchResult>(pairCount)
            for (k in 0 until pairCount) {
                val i = k
                val j = (k + 1) % n
                val dPsi = if (j == 0) {
                    (2.0 * PI - (frames[i].yawGyro - frames[0].yawGyro)).toFloat()
                } else {
                    frames[j].yawGyro - frames[i].yawGyro
                }
                dPsiGyro[k] = dPsi
                val dxExp = (fGray * dPsi).roundToInt()
                if (dxExp <= 0 || dxExp >= cyls[i].w - 8) continue
                // در گذر اول جستجوی وسیع (زاویه‌ی دید هنوز نامطمئن است)
                ms[k] = matchPair(cyls[i], cyls[j], dxExp, wide = pass == 0)
                ms[k]?.let { m ->
                    Log.d(
                        "PanoComposer",
                        "pass=$pass pair=$k gyro=${Math.toDegrees(dPsi.toDouble()).toInt()} " +
                            "dxExp=$dxExp dx=${m.dx} dy=${m.dy} ncc=${"%.2f".format(m.ncc)}"
                    )
                }
            }
            matches = ms.toList()

            // برآورد مقاوم فاصله‌ی کانونی: میانه‌ی نسبت جابجایی به زاویه
            // (میانه در برابر جفت‌های بدتطبیق مقاوم است)
            val ratios = ArrayList<Float>()
            for (k in 0 until pairCount) {
                val m = matches[k] ?: continue
                if (m.ncc < 0.45f || dPsiGyro[k] < 0.05f) continue
                ratios.add(m.dx / dPsiGyro[k])
            }
            if (ratios.size >= 3) {
                ratios.sort()
                val fNew = ratios[ratios.size / 2]
                if (fNew > GRAY_W / 4f && fNew < GRAY_W * 4f) fGray = fNew
            }
            Log.d("PanoComposer", "pass=$pass fGray=$fGray (از ${ratios.size} جفت)")
        }

        // ---- زاویه‌ها و بهره‌ی نهایی هر فریم ----
        val dPsi = FloatArray(pairCount)
        val dTheta = FloatArray(pairCount)
        val gainRatio = FloatArray(pairCount) { 1f }
        val maxYawDev = Math.toRadians(3.0).toFloat()
        val maxPitchDev = Math.toRadians(2.0).toFloat()
        for (k in 0 until pairCount) {
            val m = matches[k]
            val j = (k + 1) % n
            val gyroTheta = frames[j].pitchGyro - frames[k].pitchGyro
            if (m != null && m.ncc >= MIN_NCC) {
                // انحراف از ژیروسکوپ محدود می‌شود تا جفت‌های بدتطبیق خراب‌کاری نکنند
                dPsi[k] = (m.dx / fGray)
                    .coerceIn(dPsiGyro[k] - maxYawDev, dPsiGyro[k] + maxYawDev)
                dTheta[k] = (-m.dy / fGray)
                    .coerceIn(gyroTheta - maxPitchDev, gyroTheta + maxPitchDev)
                if (m.meanB > 1f) gainRatio[k] = (m.meanA / m.meanB).coerceIn(0.5f, 2f)
            } else {
                dPsi[k] = dPsiGyro[k]
                dTheta[k] = gyroTheta
            }
        }

        // بستن حلقه: مجموع چرخش‌ها باید دقیقاً ۳۶۰ درجه شود
        if (fullCircle) {
            val total = dPsi.sum()
            if (total > 1f) {
                val scale = (2.0 * PI).toFloat() / total
                for (k in dPsi.indices) dPsi[k] *= scale
            }
        }

        val yaw = FloatArray(n)
        val pitch = FloatArray(n)
        val logGain = FloatArray(n)
        pitch[0] = frames[0].pitchGyro
        for (k in 0 until pairCount) {
            val j = (k + 1) % n
            if (j == 0) break
            yaw[j] = yaw[k] + dPsi[k]
            pitch[j] = pitch[k] + dTheta[k]
            logGain[j] = logGain[k] + ln(gainRatio[k])
        }
        if (fullCircle) {
            // حذف رانش تجمعی pitch و بهره در طول حلقه
            val pitchDrift = pitch[n - 1] + dTheta[pairCount - 1] - pitch[0]
            val gainDrift = logGain[n - 1] + ln(gainRatio[pairCount - 1]) - logGain[0]
            for (i in 0 until n) {
                pitch[i] -= pitchDrift * i / n
                logGain[i] -= gainDrift * i / n
            }
        }
        val meanLog = logGain.average().toFloat()
        val placements = List(n) { i ->
            Placement(
                yaw = yaw[i],
                pitch = pitch[i],
                roll = frames[i].rollGyro,
                gain = exp(logGain[i] - meanLog).coerceIn(0.6f, 1.7f),
            )
        }

        // زاویه‌ی دید نهایی از فاصله‌ی کانونی برآوردشده
        val fFull = fGray * (frames[0].w.toFloat() / GRAY_W)
        val tanH = (frames[0].w / 2f) / fFull
        val tanV = (frames[0].h / 2f) / fFull

        // ردیف‌های بالا/پایین/سقف: جاگذاری مستقیم با ژیروسکوپ
        val extraPairs = extraShots.mapNotNull { s -> decode(s)?.let { s.file to it } }
        val extraFrames = extraPairs.map { it.second }
        val extraPlacements = extraFrames.map { f ->
            Placement(yaw = f.yawGyro, pitch = f.pitchGyro, roll = f.rollGyro, gain = 1f)
        }
        val allFrames = frames + extraFrames
        val allPlacements = placements + extraPlacements

        // ---- مسیر اصلی: ترکیب حرفه‌ای native (جبران نور + خط درز + ادغام چندباندی) ----
        val allFiles = middlePairs.map { it.first } + extraPairs.map { it.first }
        val fRel = fFull / frames[0].w
        if (NativeStitcher.isAvailable) {
            val ypr = FloatArray(allPlacements.size * 3)
            allPlacements.forEachIndexed { i, p ->
                ypr[i * 3] = p.yaw
                ypr[i * 3 + 1] = p.pitch
                ypr[i * 3 + 2] = p.roll
            }
            if (NativeStitcher.compose(allFiles, ypr, fRel, output)) return Result.Ok
        }

        // ---- مسیر جایگزین: رندر داخلی ----
        val basis = allPlacements.map { buildBasis(it) }
        val out = IntArray(CANVAS_W * CANVAS_H)
        val yawWindow = (2.2f * atan(tanH))

        coroutineScope {
            val threads = Runtime.getRuntime().availableProcessors().coerceIn(2, 8)
            val rowsPerJob = (CANVAS_H + threads - 1) / threads
            for (t in 0 until threads) {
                val yStart = t * rowsPerJob
                val yEnd = minOf(yStart + rowsPerJob, CANVAS_H)
                launch(Dispatchers.Default) {
                    renderRows(out, allFrames, basis, allPlacements, yStart, yEnd, tanH, tanV, yawWindow)
                }
            }
        }

        val bmp = Bitmap.createBitmap(out, CANVAS_W, CANVAS_H, Bitmap.Config.ARGB_8888)
        output.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 88, it) }
        bmp.recycle()
        return Result.Ok
    }

    // ---------- رندر ----------

    /** بردارهای forward/right/up دوربین: X شرق، Y بالا، Z شمال. */
    private class Basis(
        val fx: Float, val fy: Float, val fz: Float,
        val rx: Float, val ry: Float, val rz: Float,
        val ux: Float, val uy: Float, val uz: Float,
        val yaw: Float,
    )

    private fun buildBasis(p: Placement): Basis {
        val cy = cos(p.yaw); val sy = sin(p.yaw)
        val cp = cos(p.pitch); val sp = sin(p.pitch)
        val fx = sy * cp; val fy = sp; val fz = cy * cp
        var rx = cy; var ry = 0f; var rz = -sy
        // up = forward × right  (تا بردار «بالا» واقعاً رو به بالا باشد)
        var ux = fy * rz - fz * ry
        var uy = fz * rx - fx * rz
        var uz = fx * ry - fy * rx
        val cr = cos(p.roll); val sr = sin(p.roll)
        val nrx = rx * cr + ux * sr
        val nry = ry * cr + uy * sr
        val nrz = rz * cr + uz * sr
        ux = -rx * sr + ux * cr
        uy = -ry * sr + uy * cr
        uz = -rz * sr + uz * cr
        rx = nrx; ry = nry; rz = nrz
        return Basis(fx, fy, fz, rx, ry, rz, ux, uy, uz, p.yaw)
    }

    private fun renderRows(
        out: IntArray,
        frames: List<SrcFrame>,
        basis: List<Basis>,
        placements: List<Placement>,
        yStart: Int, yEnd: Int,
        tanH: Float, tanV: Float, yawWindow: Float,
    ) {
        for (j in yStart until yEnd) {
            val lat = ((0.5f - (j + 0.5f) / CANVAS_H) * PI).toFloat()
            val cosLat = cos(lat)
            val sinLat = sin(lat)
            // نزدیک قطب‌ها هر فریم بازه‌ی طول جغرافیایی وسیع‌تری را می‌پوشاند
            val rowWindow = yawWindow / maxOf(0.25f, cosLat)
            val rowBase = j * CANVAS_W
            for (i in 0 until CANVAS_W) {
                val lon = (((i + 0.5f) / CANVAS_W - 0.5f) * 2f * PI).toFloat()
                val dx = sin(lon) * cosLat
                val dy = sinLat
                val dz = cos(lon) * cosLat

                var accR = 0f; var accG = 0f; var accB = 0f; var accW = 0f
                for (fIdx in frames.indices) {
                    val b = basis[fIdx]
                    // فریم‌های نزدیک به سقف/کف همه‌ی طول‌های جغرافیایی را می‌پوشانند
                    val steep = abs(placements[fIdx].pitch) > 1.05f
                    if (!steep && abs(angleWrap(lon - b.yaw)) > rowWindow) continue
                    val tDot = dx * b.fx + dy * b.fy + dz * b.fz
                    if (tDot <= 0.15f) continue
                    val px = (dx * b.rx + dy * b.ry + dz * b.rz) / tDot
                    val py = (dx * b.ux + dy * b.uy + dz * b.uz) / tDot
                    val u = 0.5f + px / (2f * tanH)
                    val v = 0.5f - py / (2f * tanV)
                    if (u < 0f || u >= 1f || v < 0f || v >= 1f) continue

                    val f = frames[fIdx]
                    val sx = u * (f.w - 1)
                    val sy = v * (f.h - 1)
                    val x0 = sx.toInt().coerceAtMost(f.w - 2)
                    val y0 = sy.toInt().coerceAtMost(f.h - 2)
                    val fx1 = sx - x0
                    val fy1 = sy - y0
                    val c00 = f.px[y0 * f.w + x0]
                    val c10 = f.px[y0 * f.w + x0 + 1]
                    val c01 = f.px[(y0 + 1) * f.w + x0]
                    val c11 = f.px[(y0 + 1) * f.w + x0 + 1]

                    val gain = placements[fIdx].gain
                    val wu = 0.5f - abs(u - 0.5f)
                    val wv = 0.5f - abs(v - 0.5f)
                    val w = wu * wv + 1e-4f

                    accR += bilerp(c00 shr 16, c10 shr 16, c01 shr 16, c11 shr 16, fx1, fy1) * gain * w
                    accG += bilerp(c00 shr 8, c10 shr 8, c01 shr 8, c11 shr 8, fx1, fy1) * gain * w
                    accB += bilerp(c00, c10, c01, c11, fx1, fy1) * gain * w
                    accW += w
                }
                out[rowBase + i] = if (accW > 0f) {
                    (0xFF shl 24) or
                        (((accR / accW).toInt().coerceIn(0, 255)) shl 16) or
                        (((accG / accW).toInt().coerceIn(0, 255)) shl 8) or
                        ((accB / accW).toInt().coerceIn(0, 255))
                } else {
                    0xFF000000.toInt()
                }
            }
        }
    }

    private fun bilerp(a: Int, b: Int, c: Int, d: Int, fx: Float, fy: Float): Float {
        val top = (a and 0xFF) + ((b and 0xFF) - (a and 0xFF)) * fx
        val bot = (c and 0xFF) + ((d and 0xFF) - (c and 0xFF)) * fx
        return top + (bot - top) * fy
    }

    // ---------- تطبیق در فضای استوانه‌ای ----------

    private fun toGray(src: SrcFrame, targetW: Int): GrayImg {
        val scale = targetW.toFloat() / src.w
        val gw = targetW
        val gh = (src.h * scale).toInt()
        val g = FloatArray(gw * gh)
        for (j in 0 until gh) {
            val sy = (j / scale).toInt().coerceAtMost(src.h - 1)
            for (i in 0 until gw) {
                val sx = (i / scale).toInt().coerceAtMost(src.w - 1)
                val c = src.px[sy * src.w + sx]
                g[j * gw + i] =
                    0.299f * ((c shr 16) and 0xFF) +
                    0.587f * ((c shr 8) and 0xFF) +
                    0.114f * (c and 0xFF)
            }
        }
        return GrayImg(g, gw, gh)
    }

    /** نگاشت تصویر پرسپکتیو به فضای استوانه‌ای؛ چرخش خالص = جابجایی افقی. */
    private fun cylWarp(gray: GrayImg, fPx: Float): GrayImg {
        val halfAngle = atan((gray.w / 2f) / fPx)
        val cw = (2f * halfAngle * fPx).toInt().coerceAtLeast(16)
        val ch = gray.h
        val out = FloatArray(cw * ch) { -1f }
        for (i in 0 until cw) {
            val phi = (i - cw / 2f + 0.5f) / fPx
            val xp = fPx * tan(phi) + gray.w / 2f
            if (xp < 0f || xp > gray.w - 1f) continue
            val cosPhi = cos(phi)
            for (j in 0 until ch) {
                val yn = (j - ch / 2f + 0.5f) / fPx
                val yp = fPx * yn / cosPhi + gray.h / 2f
                if (yp < 0f || yp > gray.h - 1f) continue
                val x0 = xp.toInt().coerceAtMost(gray.w - 2)
                val y0 = yp.toInt().coerceAtMost(gray.h - 2)
                val fx = xp - x0
                val fy = yp - y0
                val base = y0 * gray.w + x0
                val top = gray.g[base] + (gray.g[base + 1] - gray.g[base]) * fx
                val bot = gray.g[base + gray.w] + (gray.g[base + gray.w + 1] - gray.g[base + gray.w]) * fx
                out[j * cw + i] = top + (bot - top) * fy
            }
        }
        return GrayImg(out, cw, ch)
    }

    /**
     * یافتن جابجایی (dx, dy) که فریم بعدی را بهترین شکل روی فریم قبلی می‌اندازد.
     * مقایسه: A(x + dx, y + dy) با B(x, y) روی ناحیه‌ی همپوشان، با معیار NCC.
     */
    private fun matchPair(a: GrayImg, b: GrayImg, dxExp: Int, wide: Boolean): MatchResult {
        // وقتی زاویه‌ی دید نامطمئن است، جابجایی واقعی می‌تواند خیلی دورتر از انتظار باشد
        val searchX = if (wide) maxOf(16, (dxExp * 0.45f).toInt()) else maxOf(10, (a.w * 0.05f).toInt())
        val searchY = 14
        val coarseStep = if (wide) 4 else 3

        var best = Triple(dxExp, 0, -2f)
        // جستجوی درشت
        var dyC = -searchY
        while (dyC <= searchY) {
            var dxC = dxExp - searchX
            while (dxC <= dxExp + searchX) {
                val s = ncc(a, b, dxC, dyC, 3)
                if (s > best.third) best = Triple(dxC, dyC, s)
                dxC += coarseStep
            }
            dyC += 3
        }
        // پالایش
        var refined = best
        for (dy2 in best.second - 2..best.second + 2) {
            for (dx2 in best.first - 3..best.first + 3) {
                val s = ncc(a, b, dx2, dy2, 1)
                if (s > refined.third) refined = Triple(dx2, dy2, s)
            }
        }
        val (dx, dy, score) = refined
        val (ma, mb) = overlapMeans(a, b, dx, dy)
        return MatchResult(dx, dy, score, ma, mb)
    }

    private fun ncc(a: GrayImg, b: GrayImg, dx: Int, dy: Int, step: Int): Float {
        var nrm = 0; var sa = 0f; var sb = 0f; var saa = 0f; var sbb = 0f; var sab = 0f
        val xStart = maxOf(0, -dx)
        val xEnd = minOf(b.w, a.w - dx)
        if (xEnd - xStart < 8) return -2f
        var y = maxOf(0, -dy)
        val yEnd = minOf(b.h, a.h - dy)
        while (y < yEnd) {
            var x = xStart
            val aRow = (y + dy) * a.w
            val bRow = y * b.w
            while (x < xEnd) {
                val va = a.g[aRow + x + dx]
                val vb = b.g[bRow + x]
                if (va >= 0f && vb >= 0f) {
                    nrm++; sa += va; sb += vb
                    saa += va * va; sbb += vb * vb; sab += va * vb
                }
                x += step
            }
            y += step
        }
        if (nrm < 64) return -2f
        val cov = nrm * sab - sa * sb
        val varA = nrm * saa - sa * sa
        val varB = nrm * sbb - sb * sb
        if (varA <= 0f || varB <= 0f) return -2f
        return cov / sqrt(varA * varB)
    }

    private fun overlapMeans(a: GrayImg, b: GrayImg, dx: Int, dy: Int): Pair<Float, Float> {
        var nrm = 0; var sa = 0f; var sb = 0f
        val xStart = maxOf(0, -dx)
        val xEnd = minOf(b.w, a.w - dx)
        var y = maxOf(0, -dy)
        val yEnd = minOf(b.h, a.h - dy)
        while (y < yEnd) {
            var x = xStart
            while (x < xEnd) {
                val va = a.g[(y + dy) * a.w + x + dx]
                val vb = b.g[y * b.w + x]
                if (va >= 0f && vb >= 0f) { nrm++; sa += va; sb += vb }
                x += 2
            }
            y += 2
        }
        if (nrm == 0) return 1f to 1f
        return (sa / nrm) to (sb / nrm)
    }

    // ---------- کمکی ----------

    private fun angleWrap(a: Float): Float {
        var x = a % (2f * PI.toFloat())
        if (x > PI) x -= 2f * PI.toFloat()
        if (x < -PI) x += 2f * PI.toFloat()
        return x
    }

    /** زاویه به بازه‌ی ۰ تا ۳۶۰ (برای دنباله‌ی صعودی چرخش به راست). */
    private fun unwrapDeg(d: Float): Float {
        var x = d % 360f
        if (x < 0f) x += 360f
        return x
    }

    /** دیکد با کاهش رزولوشن + اعمال چرخش EXIF تا فریم عمودی باشد. */
    private fun decodeUpright(file: File, maxDim: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0) return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxDim) sample *= 2
        val bmp = BitmapFactory.decodeFile(
            file.absolutePath,
            BitmapFactory.Options().apply { inSampleSize = sample },
        ) ?: return null

        val rotation = when (
            ExifInterface(file.absolutePath)
                .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        ) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
        if (rotation == 0f) return bmp
        val rotated = Bitmap.createBitmap(
            bmp, 0, 0, bmp.width, bmp.height,
            Matrix().apply { postRotate(rotation) }, true,
        )
        if (rotated != bmp) bmp.recycle()
        return rotated
    }
}
