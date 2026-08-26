package com.siteview.app

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import com.siteview.app.data.Store
import com.siteview.app.data.Updater
import com.siteview.app.ui.Capture360Screen
import com.siteview.app.ui.PlanScreen
import com.siteview.app.ui.ViewerScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed interface Screen {
    data object Plan : Screen
    data class Viewer(val captureId: Long) : Screen
    data class Capture360(val pointId: Long) : Screen
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = Store(applicationContext)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme()) {
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
                    var screen by remember { mutableStateOf<Screen>(Screen.Plan) }
                    when (val s = screen) {
                        is Screen.Plan -> PlanScreen(
                            store = store,
                            onOpenCapture = { screen = Screen.Viewer(it.id) },
                            onCapture360 = { pointId -> screen = Screen.Capture360(pointId) },
                        )
                        is Screen.Viewer -> ViewerScreen(
                            store = store,
                            captureId = s.captureId,
                            onBack = { screen = Screen.Plan },
                        )
                        is Screen.Capture360 -> Capture360Screen(
                            store = store,
                            pointId = s.pointId,
                            onDone = { screen = Screen.Plan },
                        )
                    }
                    UpdateChecker()
                }
            }
        }
    }
}

/** موقع باز شدن اپ، GitHub Releases را چک می‌کند و اگر نسخه‌ی جدیدی بود پیشنهاد بروزرسانی می‌دهد. */
@Composable
private fun UpdateChecker() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var update by remember { mutableStateOf<Updater.UpdateInfo?>(null) }
    var downloading by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        update = withContext(Dispatchers.IO) { Updater.checkForUpdate() }
    }

    val info = update
    if (info != null) {
        AlertDialog(
            onDismissRequest = { if (!downloading) update = null },
            title = { Text("بروزرسانی جدید") },
            text = {
                Text(
                    if (downloading) "در حال دانلود، صبر کنید…"
                    else "نسخه‌ی جدید اپ (${info.title}) آماده است. همین حالا بروزرسانی شود؟"
                )
            },
            confirmButton = {
                TextButton(
                    enabled = !downloading,
                    onClick = {
                        downloading = true
                        scope.launch {
                            val apk = withContext(Dispatchers.IO) {
                                Updater.downloadApk(context, info)
                            }
                            downloading = false
                            update = null
                            if (apk != null) {
                                Updater.promptInstall(context, apk)
                            } else {
                                Toast.makeText(context, "دانلود ناموفق بود", Toast.LENGTH_LONG).show()
                            }
                        }
                    },
                ) { Text(if (downloading) "در حال دانلود…" else "بروزرسانی") }
            },
            dismissButton = {
                TextButton(enabled = !downloading, onClick = { update = null }) { Text("بعداً") }
            },
        )
    }
}
