package com.thread.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.lifecycle.Lifecycle
import org.json.JSONObject
import java.io.ByteArrayOutputStream

class MainActivity : ComponentActivity() {
    val model: ThreadModel by viewModels()
    private var showConsent by mutableStateOf(false)
    private var consentAction: (() -> Unit)? = null
    private val microphone = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (it[Manifest.permission.RECORD_AUDIO] == true || checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) model.connect(true)
        else { model.keyboard = true; model.showError("Microphone permission is off. You can type, or allow it in Android app permissions.") }
    }
    private val cameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { allowed -> if (allowed) camera.launch(null) }
    private val camera = registerForActivityResult(ActivityResultContracts.TakePicturePreview()) { bitmap -> bitmap?.let { shareBitmap(it) } }
    private val image = registerForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> uri?.let { readImage(it) } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        model.deviceAction = { request ->
            if (!lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) PhoneActions.outcome("failed", "Open THREAD to continue this phone action.")
            else PhoneActions(this) { model.widget = it }.execute(request).also {
                if (model.haptics && it.optString("status") in listOf("completed", "handed_off", "prepared")) window.decorView.performHapticFeedback(android.view.HapticFeedbackConstants.CONFIRM)
            }
        }
        setContent {
            ThreadTheme {
                ThreadApp(model, ::startVoice, { image.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, ::takePhoto,
                    { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))) })
                if (showConsent) AlertDialog(onDismissRequest = { showConsent = false; consentAction = null },
                    title = { Text("Your voice, with your permission.") },
                    text = { Text("Audio, messages, shared images and relevant task context go to Google Gemini over the internet. THREAD's task engine runs on this phone. Searches use their named providers. Text, notes and results are kept on this phone; raw microphone audio is not saved. The microphone is active only in a conversation you start.") },
                    confirmButton = { TextButton(onClick = { model.preference("consent", true); showConsent = false; consentAction?.invoke(); consentAction = null }) { Text("Continue") } },
                    dismissButton = { TextButton(onClick = { showConsent = false; consentAction = null }) { Text("Not now") } })
            }
        }
        if (savedInstanceState == null) incoming(intent)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); incoming(intent) }
    override fun onResume() { super.onResume(); model.refreshSpotifyConnection() }
    private fun incoming(intent: Intent) {
        if (intent.getBooleanExtra("talk", false) || intent.action == Intent.ACTION_ASSIST) { model.route = "voice"; startVoice() }
        if (intent.hasExtra("widget_id")) {
            val id = intent.getIntExtra("widget_id", -1)
            val config = getSharedPreferences("widgets", 0).getString("widget-$id", null)
            val result = config?.let { JSONObject(it).optJSONArray("results")?.optJSONObject(intent.getIntExtra("result_index", 0)) }
            if (result != null) model.openResult = result else startActivity(Intent(this, WidgetConfigurationActivity::class.java).putExtra(android.appwidget.AppWidgetManager.EXTRA_APPWIDGET_ID, id))
        }
        if (intent.action == Intent.ACTION_SEND) {
            if (intent.type == "text/plain") { model.sharedText = intent.getStringExtra(Intent.EXTRA_TEXT)?.take(12000) ?: ""; model.keyboard = true }
            else if (intent.type?.startsWith("image/") == true) {
                @Suppress("DEPRECATION") val uri = intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
                uri?.let { readImage(it) }
            }
        }
    }
    private fun withConsent(action: () -> Unit) { if (model.consent) action() else { consentAction = action; showConsent = true } }
    private fun startVoice() = withConsent {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) model.connect(true)
        else microphone.launch(if (android.os.Build.VERSION.SDK_INT >= 33) arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS) else arrayOf(Manifest.permission.RECORD_AUDIO))
    }
    private fun takePhoto() {
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) camera.launch(null) else cameraPermission.launch(Manifest.permission.CAMERA)
    }
    private fun readImage(uri: Uri) {
        try {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
            require(bounds.outWidth > 0 && bounds.outHeight > 0)
            val options = BitmapFactory.Options().apply { inSampleSize = maxOf(1, maxOf(bounds.outWidth, bounds.outHeight) / 1280) }
            contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }?.let { shareBitmap(it) }
        } catch (_: Exception) { model.showError("That image couldn’t be read. Choose a photo or screenshot.") }
    }
    private fun shareBitmap(bitmap: Bitmap) = withConsent {
        val ratio = minOf(1f, 1280f / maxOf(bitmap.width, bitmap.height))
        val scaled = Bitmap.createScaledBitmap(bitmap, (bitmap.width * ratio).toInt(), (bitmap.height * ratio).toInt(), true)
        val buffer = ByteArrayOutputStream(); scaled.compress(Bitmap.CompressFormat.JPEG, 88, buffer)
        model.queueImage(buffer.toByteArray())
    }
    override fun onDestroy() { model.deviceAction = null; super.onDestroy() }
}
