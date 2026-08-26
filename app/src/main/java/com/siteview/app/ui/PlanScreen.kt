package com.siteview.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import coil.compose.AsyncImage
import com.siteview.app.data.Capture
import com.siteview.app.data.Store
import com.siteview.app.data.formatDate
import java.io.File
import kotlin.math.min
import kotlin.math.roundToInt

/** وضعیت زوم/جابجایی پلان + تبدیل بین مختصات صفحه و مختصات نسبی پلان. */
private class PlanTransform {
    var scale by mutableFloatStateOf(1f)
    var offset by mutableStateOf(Offset.Zero)
    var viewSize by mutableStateOf(IntSize.Zero)
    var planSize by mutableStateOf(IntSize.Zero)

    val baseScale: Float
        get() {
            if (viewSize == IntSize.Zero || planSize == IntSize.Zero) return 1f
            return min(
                viewSize.width.toFloat() / planSize.width,
                viewSize.height.toFloat() / planSize.height,
            )
        }

    val drawSize: Size
        get() = Size(planSize.width * baseScale * scale, planSize.height * baseScale * scale)

    fun planToScreen(x: Float, y: Float): Offset {
        val ds = drawSize
        return Offset(offset.x + x * ds.width, offset.y + y * ds.height)
    }

    fun screenToPlan(p: Offset): Offset {
        val ds = drawSize
        if (ds.width <= 0f || ds.height <= 0f) return Offset(-1f, -1f)
        return Offset((p.x - offset.x) / ds.width, (p.y - offset.y) / ds.height)
    }

    fun resetToCenter() {
        scale = 1f
        val ds = drawSize
        offset = Offset(
            (viewSize.width - ds.width) / 2f,
            (viewSize.height - ds.height) / 2f,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlanScreen(store: Store, onOpenCapture: (Capture) -> Unit) {
    val context = LocalContext.current
    val density = LocalDensity.current
    val plan = store.planBitmap

    val t = remember { PlanTransform() }
    var selectedPointId by remember { mutableStateOf<Long?>(null) }
    var newPointPos by remember { mutableStateOf<Offset?>(null) }
    var newPointName by remember { mutableStateOf("") }

    var pendingPointId by remember { mutableStateOf<Long?>(null) }
    var pendingFile by remember { mutableStateOf<File?>(null) }

    val cameraLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture()
    ) { ok ->
        val f = pendingFile
        val pid = pendingPointId
        if (ok && f != null && pid != null) store.addCapture(pid, f, is360 = false)
        else f?.delete()
        pendingFile = null
    }

    val importLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia()
    ) { uri ->
        val pid = pendingPointId
        if (uri != null && pid != null) store.importImage(uri, pid)
    }

    val planLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia()
    ) { uri ->
        if (uri != null) store.setPlan(uri)
    }

    val hitRadiusPx = with(density) { 28.dp.toPx() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("بازدید پروژه") },
                actions = {
                    TextButton(onClick = {
                        planLauncher.launch(
                            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                        )
                    }) { Text("تغییر پلان") }
                },
            )
        },
    ) { padding ->
        Box(
            Modifier
                .padding(padding)
                .fillMaxSize()
        ) {
            if (plan == null) {
                Text("پلان یافت نشد", Modifier.align(Alignment.Center))
            } else {
                LaunchedEffect(plan) {
                    t.planSize = IntSize(plan.width, plan.height)
                }
                LaunchedEffect(t.planSize, t.viewSize) {
                    if (t.planSize != IntSize.Zero && t.viewSize != IntSize.Zero) t.resetToCenter()
                }

                Canvas(
                    Modifier
                        .fillMaxSize()
                        .onSizeChanged { t.viewSize = it }
                        .pointerInput(Unit) {
                            detectTransformGestures { centroid, pan, zoom, _ ->
                                val newScale = (t.scale * zoom).coerceIn(0.5f, 15f)
                                t.offset = centroid - (centroid - t.offset) * (newScale / t.scale) + pan
                                t.scale = newScale
                            }
                        }
                        .pointerInput(Unit) {
                            detectTapGestures(
                                onTap = { pos ->
                                    val hit = store.points.minByOrNull {
                                        (t.planToScreen(it.x, it.y) - pos).getDistance()
                                    }
                                    if (hit != null &&
                                        (t.planToScreen(hit.x, hit.y) - pos).getDistance() < hitRadiusPx
                                    ) {
                                        selectedPointId = hit.id
                                    }
                                },
                                onLongPress = { pos ->
                                    val rel = t.screenToPlan(pos)
                                    if (rel.x in 0f..1f && rel.y in 0f..1f) {
                                        newPointName = "نقطه ${store.points.size + 1}"
                                        newPointPos = rel
                                    }
                                },
                            )
                        }
                ) {
                    val ds = t.drawSize
                    if (ds.width > 0f && ds.height > 0f) {
                        drawImage(
                            image = plan,
                            dstOffset = IntOffset(t.offset.x.roundToInt(), t.offset.y.roundToInt()),
                            dstSize = IntSize(ds.width.roundToInt(), ds.height.roundToInt()),
                        )
                    }
                    store.points.forEach { p ->
                        val c = t.planToScreen(p.x, p.y)
                        val hasCaptures = store.captures.any { it.pointId == p.id }
                        drawCircle(
                            color = if (hasCaptures) Color(0xFF1E88E5) else Color(0xFFE53935),
                            radius = 11.dp.toPx(),
                            center = c,
                        )
                        drawCircle(color = Color.White, radius = 4.dp.toPx(), center = c)
                    }
                }

                Text(
                    "برای افزودن نقطه، روی پلان لمس طولانی کنید — برای دیدن عکس‌ها روی نقطه بزنید",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(12.dp),
                )
            }
        }
    }

    // دیالوگ ثبت نقطه‌ی جدید
    val pos = newPointPos
    if (pos != null) {
        AlertDialog(
            onDismissRequest = { newPointPos = null },
            title = { Text("نقطه‌ی جدید") },
            text = {
                OutlinedTextField(
                    value = newPointName,
                    onValueChange = { newPointName = it },
                    label = { Text("نام نقطه") },
                    singleLine = true,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    store.addPoint(newPointName.ifBlank { "نقطه" }, pos.x, pos.y)
                    newPointPos = null
                }) { Text("ثبت") }
            },
            dismissButton = {
                TextButton(onClick = { newPointPos = null }) { Text("انصراف") }
            },
        )
    }

    // برگه‌ی پایین: تایم‌لاین عکس‌های یک نقطه
    val selectedPoint = store.points.find { it.id == selectedPointId }
    if (selectedPoint != null) {
        ModalBottomSheet(onDismissRequest = { selectedPointId = null }) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        selectedPoint.name,
                        style = MaterialTheme.typography.titleLarge,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = {
                        store.removePoint(selectedPoint)
                        selectedPointId = null
                    }) { Text("حذف نقطه", color = MaterialTheme.colorScheme.error) }
                }
                Spacer(Modifier.height(8.dp))
                Row {
                    Button(
                        onClick = {
                            val f = store.newPhotoFile()
                            pendingFile = f
                            pendingPointId = selectedPoint.id
                            val uri = FileProvider.getUriForFile(
                                context, context.packageName + ".fileprovider", f
                            )
                            cameraLauncher.launch(uri)
                        },
                        modifier = Modifier.weight(1f),
                    ) { Text("عکس با دوربین") }
                    Spacer(Modifier.width(8.dp))
                    OutlinedButton(
                        onClick = {
                            pendingPointId = selectedPoint.id
                            importLauncher.launch(
                                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                            )
                        },
                        modifier = Modifier.weight(1f),
                    ) { Text("از گالری (360)") }
                }
                Spacer(Modifier.height(12.dp))

                val pointCaptures = store.captures
                    .filter { it.pointId == selectedPoint.id }
                    .sortedByDescending { it.takenAt }

                if (pointCaptures.isEmpty()) {
                    Text(
                        "هنوز عکسی برای این نقطه ثبت نشده",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 24.dp),
                    )
                } else {
                    LazyColumn(Modifier.heightIn(max = 420.dp)) {
                        items(pointCaptures, key = { it.id }) { c ->
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable { onOpenCapture(c) }
                                    .padding(vertical = 6.dp),
                            ) {
                                AsyncImage(
                                    model = store.photoFile(c),
                                    contentDescription = null,
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier
                                        .size(64.dp)
                                        .clip(RoundedCornerShape(8.dp)),
                                )
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(formatDate(c.takenAt))
                                    if (c.is360) {
                                        Text(
                                            "عکس ۳۶۰ درجه",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.primary,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(32.dp))
            }
        }
    }
}
