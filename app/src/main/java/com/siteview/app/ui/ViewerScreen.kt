package com.siteview.app.ui

import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.viewinterop.AndroidView
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import coil.compose.AsyncImage
import com.siteview.app.data.Store
import com.siteview.app.data.formatDate
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ViewerScreen(store: Store, captureId: Long, onBack: () -> Unit) {
    BackHandler(onBack = onBack)

    var currentId by remember { mutableStateOf(captureId) }
    val capture = store.captures.find { it.id == currentId }
    if (capture == null) {
        LaunchedEffect(Unit) { onBack() }
        return
    }

    // تایم‌لاین همین نقطه، از قدیم به جدید
    val siblings = store.captures
        .filter { it.pointId == capture.pointId }
        .sortedBy { it.takenAt }
    val index = siblings.indexOfFirst { it.id == capture.id }
    val point = store.points.find { it.id == capture.pointId }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(point?.name ?: "")
                        Text(
                            formatDate(capture.takenAt) + if (capture.is360) "  —  ۳۶۰°" else "",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "بازگشت")
                    }
                },
                actions = {
                    TextButton(
                        onClick = { store.setIs360(capture, !capture.is360) },
                    ) { Text(if (capture.is360) "عادی" else "۳۶۰") }
                    TextButton(
                        enabled = index > 0,
                        onClick = { currentId = siblings[index - 1].id },
                    ) { Text("قدیمی‌تر") }
                    TextButton(
                        enabled = index in 0 until siblings.size - 1,
                        onClick = { currentId = siblings[index + 1].id },
                    ) { Text("جدیدتر") }
                },
            )
        },
    ) { padding ->
        Box(
            Modifier
                .padding(padding)
                .fillMaxSize()
                .background(Color.Black)
        ) {
            val file = store.photoFile(capture)
            if (capture.is360) Panorama360(store, file) else ZoomableImage(file)
        }
    }
}

/**
 * نمایشگر 360: یک WebView که عکس equirectangular را روی کره رندر می‌کند (کاملاً آفلاین).
 * فایل‌ها از طریق WebViewAssetLoader سرو می‌شوند تا هم‌مبدأ باشند و WebGL بتواند
 * تصویر را به‌عنوان تکسچر استفاده کند (با file:// خطای امنیتی می‌داد).
 */
@Composable
private fun Panorama360(store: Store, file: File) {
    AndroidView(
        factory = { ctx ->
            val assetLoader = WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(ctx))
                .addPathHandler(
                    "/photos/",
                    WebViewAssetLoader.InternalStoragePathHandler(ctx, store.photosDir),
                )
                .build()
            WebView(ctx).apply {
                settings.javaScriptEnabled = true
                webViewClient = object : WebViewClientCompat() {
                    override fun shouldInterceptRequest(
                        view: WebView,
                        request: WebResourceRequest,
                    ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)
                }
                setBackgroundColor(android.graphics.Color.BLACK)
            }
        },
        update = { web ->
            val url = "https://appassets.androidplatform.net/assets/viewer.html?img=" +
                Uri.encode("/photos/" + file.name)
            if (web.url != url) web.loadUrl(url)
        },
        modifier = Modifier.fillMaxSize(),
    )
}

/** نمایش عکس معمولی با زوم و جابجایی. */
@Composable
private fun ZoomableImage(file: File) {
    var scale by remember(file) { mutableFloatStateOf(1f) }
    var offset by remember(file) { mutableStateOf(Offset.Zero) }
    AsyncImage(
        model = file,
        contentDescription = null,
        contentScale = ContentScale.Fit,
        modifier = Modifier
            .fillMaxSize()
            .pointerInput(file) {
                detectTransformGestures { _, pan, zoom, _ ->
                    scale = (scale * zoom).coerceIn(1f, 8f)
                    offset += pan
                }
            }
            .graphicsLayer(
                scaleX = scale,
                scaleY = scale,
                translationX = offset.x,
                translationY = offset.y,
            ),
    )
}
