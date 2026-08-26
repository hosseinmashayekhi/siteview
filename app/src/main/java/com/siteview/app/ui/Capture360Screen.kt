package com.siteview.app.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import android.hardware.camera2.CameraCharacteristics
import androidx.core.content.ContextCompat
import com.siteview.app.data.PanoShot
import com.siteview.app.data.PanoramaComposer
import com.siteview.app.data.Store
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.math.abs
import kotlin.math.atan

private const val SHOT_COUNT = 12
private const val STEP_DEG = 360f / SHOT_COUNT
private const val ALIGN_TOLERANCE_DEG = 5f
private const val PITCH_TOLERANCE_DEG = 10f

/** اختلاف زاویه در بازه‌ی ‎-180..180 */
private fun angleDiff(a: Float, b: Float): Float {
    var d = (a - b) % 360f
    if (d > 180f) d -= 360f
    if (d < -180f) d += 360f
    return d
}

/**
 * عکاسی 360 با گوشی: کاربر سر جای خود می‌چرخد و اپ در ۱۲ زاویه (هر ۳۰ درجه)
 * خودکار عکس می‌گیرد؛ سپس فریم‌ها بر پایه‌ی زاویه‌های ژیروسکوپ
 * به پانورامای 360 تبدیل می‌شوند.
 */
@OptIn(ExperimentalCamera2Interop::class)
@Composable
fun Capture360Screen(store: Store, pointId: Long, onDone: () -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()

    val shotsDir = remember { File(context.cacheDir, "pano_shots").apply { mkdirs() } }
    val shots = remember { mutableListOf<PanoShot>() }

    fun cleanup() = shotsDir.listFiles()?.forEach { it.delete() }

    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { hasPermission = it }
    LaunchedEffect(Unit) {
        cleanup()
        if (!hasPermission) permLauncher.launch(Manifest.permission.CAMERA)
    }

    var shotsTaken by remember { mutableIntStateOf(0) }
    var capturing by remember { mutableStateOf(false) }
    var stitching by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var startYaw by remember { mutableStateOf<Float?>(null) }

    var yawDeg by remember { mutableFloatStateOf(0f) }
    var pitchDeg by remember { mutableFloatStateOf(0f) }
    var rollDeg by remember { mutableFloatStateOf(0f) }
    var hasSensor by remember { mutableStateOf(true) }
    // زاویه‌ی دید دوربین — اگر مشخصات سنسور در دسترس بود دقیق می‌شود
    var hfovDeg by remember { mutableFloatStateOf(55f) }
    var vfovDeg by remember { mutableFloatStateOf(70f) }

    BackHandler {
        cleanup()
        onDone()
    }

    // ژیروسکوپ: جهت دوربین (yaw) و شیب (pitch) — برای گوشی عمودی رو به افق
    DisposableEffect(Unit) {
        val sm = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val sensor = sm.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        if (sensor == null) {
            hasSensor = false
            onDispose { }
        } else {
            val listener = object : SensorEventListener {
                private val rot = FloatArray(9)
                private val remapped = FloatArray(9)
                private val orientation = FloatArray(3)
                override fun onSensorChanged(e: SensorEvent) {
                    SensorManager.getRotationMatrixFromVector(rot, e.values)
                    SensorManager.remapCoordinateSystem(
                        rot, SensorManager.AXIS_X, SensorManager.AXIS_Z, remapped
                    )
                    SensorManager.getOrientation(remapped, orientation)
                    yawDeg = Math.toDegrees(orientation[0].toDouble()).toFloat()
                    pitchDeg = -Math.toDegrees(orientation[1].toDouble()).toFloat()
                    rollDeg = Math.toDegrees(orientation[2].toDouble()).toFloat()
                }

                override fun onAccuracyChanged(s: Sensor?, a: Int) {}
            }
            sm.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_GAME)
            onDispose { sm.unregisterListener(listener) }
        }
    }

    val imageCapture = remember {
        ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
            .build()
    }

    fun takeShot() {
        if (capturing || stitching) return
        capturing = true
        val file = File(shotsDir, "shot_${shotsTaken}.jpg")
        val yawAt = yawDeg
        val pitchAt = pitchDeg
        val rollAt = rollDeg
        imageCapture.takePicture(
            ImageCapture.OutputFileOptions.Builder(file).build(),
            ContextCompat.getMainExecutor(context),
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(res: ImageCapture.OutputFileResults) {
                    shots.add(PanoShot(file, yawAt, pitchAt, rollAt))
                    if (startYaw == null) startYaw = yawAt
                    shotsTaken += 1
                    capturing = false
                }

                override fun onError(e: ImageCaptureException) {
                    error = "خطای دوربین: ${e.message}"
                    capturing = false
                }
            },
        )
    }

    fun finishAndStitch() {
        if (stitching || shots.size < 2) return
        stitching = true
        scope.launch {
            val out = store.newPhotoFile()
            val result = withContext(Dispatchers.Default) {
                PanoramaComposer.compose(shots.toList(), hfovDeg, vfovDeg, out)
            }
            cleanup()
            when (result) {
                is PanoramaComposer.Result.Ok -> {
                    store.addCapture(pointId, out, is360 = true)
                    onDone()
                }
                is PanoramaComposer.Result.Failed -> {
                    out.delete()
                    stitching = false
                    error = result.message
                }
            }
        }
    }

    // زاویه‌ی هدف بعدی نسبت به اولین عکس
    val target = startYaw?.let { it + shotsTaken * STEP_DEG }
    val yawOff = target?.let { angleDiff(it, yawDeg) } ?: 0f
    val pitchOk = abs(pitchDeg) < PITCH_TOLERANCE_DEG
    val aligned = target != null && abs(yawOff) < ALIGN_TOLERANCE_DEG && pitchOk

    // عکس خودکار وقتی زاویه درست شد (عکس اول با دکمه گرفته می‌شود)
    LaunchedEffect(aligned, shotsTaken, stitching) {
        if (aligned && !stitching && shotsTaken in 1 until SHOT_COUNT) {
            kotlinx.coroutines.delay(350) // مکث کوتاه برای ثابت شدن دست
            if (aligned) takeShot()
        }
    }
    LaunchedEffect(shotsTaken) {
        if (shotsTaken >= SHOT_COUNT) finishAndStitch()
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (!hasPermission) {
            Text(
                "برای عکاسی ۳۶۰ به دسترسی دوربین نیاز است",
                color = Color.White,
                modifier = Modifier.align(Alignment.Center),
            )
            return@Box
        }

        AndroidView(
            factory = { ctx ->
                PreviewView(ctx).also { pv ->
                    val future = ProcessCameraProvider.getInstance(ctx)
                    future.addListener({
                        val provider = future.get()
                        val preview = androidx.camera.core.Preview.Builder().build()
                            .also { it.surfaceProvider = pv.surfaceProvider }
                        provider.unbindAll()
                        val camera = provider.bindToLifecycle(
                            lifecycleOwner,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            imageCapture,
                        )
                        // زاویه‌ی دید واقعی دوربین از مشخصات سنسور
                        val info = Camera2CameraInfo.from(camera.cameraInfo)
                        val focal = info.getCameraCharacteristic(
                            CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS
                        )?.firstOrNull()
                        val sensorSize = info.getCameraCharacteristic(
                            CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE
                        )
                        if (focal != null && focal > 0f && sensorSize != null) {
                            // عکس عمودی: بعد افقیِ عکس = بعد کوتاه سنسور
                            hfovDeg = Math.toDegrees(
                                2.0 * atan(sensorSize.height / (2f * focal)).toDouble()
                            ).toFloat()
                            vfovDeg = Math.toDegrees(
                                2.0 * atan(sensorSize.width / (2f * focal)).toDouble()
                            ).toFloat()
                        }
                    }, ContextCompat.getMainExecutor(ctx))
                }
            },
            modifier = Modifier.fillMaxSize(),
        )

        // راهنمای هدف‌گیری
        Canvas(Modifier.fillMaxSize()) {
            val cx = size.width / 2f
            val cy = size.height / 2f
            // حلقه‌ی مرکزی
            drawCircle(
                color = if (aligned) Color(0xFF4CAF50) else Color.White,
                radius = 46f,
                center = Offset(cx, cy),
                style = androidx.compose.ui.graphics.drawscope.Stroke(width = 6f),
            )
            // نقطه‌ی هدف: فاصله‌ی افقی متناسب با خطای زاویه، عمودی متناسب با شیب
            if (target != null && shotsTaken < SHOT_COUNT) {
                val px = cx + (yawOff / 40f) * (size.width / 2f)
                val py = cy + (pitchDeg / 40f) * (size.height / 2f)
                drawCircle(
                    color = Color(0xFFFFC107),
                    radius = 30f,
                    center = Offset(px.coerceIn(40f, size.width - 40f), py.coerceIn(40f, size.height - 40f)),
                )
            }
        }

        // نوار وضعیت بالا
        Column(
            Modifier
                .align(Alignment.TopCenter)
                .padding(16.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(Color.Black.copy(alpha = 0.55f))
                .padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                if (!hasSensor) "این گوشی حسگر چرخش ندارد — با دکمه عکس بگیرید"
                else if (shotsTaken == 0) "گوشی را عمودی رو به‌جلو بگیرید و دکمه را بزنید"
                else if (shotsTaken < SHOT_COUNT) "به راست بچرخید تا نقطه‌ی زرد وارد حلقه شود"
                else "در حال ساخت پانوراما…",
                color = Color.White,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                "عکس $shotsTaken از $SHOT_COUNT",
                color = Color(0xFFFFC107),
                style = MaterialTheme.typography.titleMedium,
            )
        }

        // پیام خطا
        val err = error
        if (err != null) {
            Column(
                Modifier
                    .align(Alignment.Center)
                    .padding(24.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(Color.Black.copy(alpha = 0.8f))
                    .padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(err, color = Color.White, textAlign = TextAlign.Center)
                Spacer(Modifier.height(12.dp))
                Button(onClick = {
                    error = null
                    shots.clear()
                    shotsTaken = 0
                    startYaw = null
                    cleanup()
                }) { Text("از اول") }
            }
        }

        // در حال دوخت
        if (stitching) {
            Column(
                Modifier
                    .align(Alignment.Center)
                    .clip(RoundedCornerShape(12.dp))
                    .background(Color.Black.copy(alpha = 0.8f))
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                CircularProgressIndicator()
                Spacer(Modifier.height(12.dp))
                Text("در حال دوخت پانوراما — چند لحظه صبر کنید", color = Color.White)
            }
        }

        // دکمه‌های پایین
        if (!stitching) {
            Row(
                Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .padding(24.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedButton(onClick = {
                    cleanup()
                    onDone()
                }) { Text("انصراف", color = Color.White) }

                // شاتر دستی (برای عکس اول یا وقتی حسگر نیست)
                Button(
                    onClick = { takeShot() },
                    enabled = !capturing && shotsTaken < SHOT_COUNT,
                    shape = CircleShape,
                    modifier = Modifier.size(76.dp),
                ) { Text("📷") }

                OutlinedButton(
                    onClick = { finishAndStitch() },
                    enabled = shots.size >= 2,
                ) { Text("اتمام", color = Color.White) }
            }
        }
    }
}
