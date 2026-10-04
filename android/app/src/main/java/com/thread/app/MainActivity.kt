package com.thread.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
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
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.lifecycle.Lifecycle
import org.json.JSONObject
import java.io.ByteArrayOutputStream

class MainActivity : ComponentActivity() {
    val model: ThreadModel by lazy { ThreadApplication.model(this) }
    private var pendingTalk = false
    private var bubbleEnablePending = false
    private val overlayPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { completeBubbleEnable() }
    private val bubbleNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { allowed ->
        if (allowed) requestOverlayPermission() else { bubbleEnablePending = false; model.bubbleUnavailable("Floating bubble is off. Allow notifications so its Stop control stays available.") }
    }
    private var showConsent by mutableStateOf(false)
    private var consentAction: (() -> Unit)? = null
    private var liveCamera: LiveCamera? = null
    private var cameraPreview by mutableStateOf<android.view.TextureView?>(null)
    private var cameraRequestGeneration: Int? = null
    private val watchNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private val liveCameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { allowed ->
        val current = cameraRequestGeneration; cameraRequestGeneration = null
        if (current == model.connectionGeneration && model.ui.connected && lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
            if (allowed) startCamera() else model.showError("Camera permission is off. You can keep talking or allow Camera in Android app permissions.")
        }
    }
    private val microphone = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (it[Manifest.permission.RECORD_AUDIO] == true || checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) model.talk() else pendingTalk = true
        }
        else { model.keyboard = true; model.showError("Microphone permission is off. You can type, or allow it in Android app permissions.") }
    }
    private val cameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { allowed -> if (allowed) camera.launch(null) }
    private val camera = registerForActivityResult(ActivityResultContracts.TakePicturePreview()) { bitmap -> bitmap?.let { shareBitmap(it) } }
    private val image = registerForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> uri?.let { readImage(it) } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        bubbleEnablePending = savedInstanceState?.getBoolean("bubble-enable-pending") == true
        pendingTalk = savedInstanceState?.getBoolean("pending-talk") == true
        model.requestFloatingBubble = ::updateFloatingBubble
        model.requestWatchNotifications = {
            if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
                val requested = model.prefs.getBoolean("watch-notification-asked", false)
                if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
                    (!requested || shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS))) {
                    model.prefs.edit().putBoolean("watch-notification-asked", true).apply()
                    watchNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                } else startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
            }
        }
        model.closeCamera = { liveCamera?.close(); liveCamera = null; cameraPreview = null }
        model.deviceAction = { request ->
            if (!lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) PhoneActions.outcome("failed", "Open THREAD to continue this phone action.")
            else PhoneActions(this) { model.widget = it }.execute(request).also {
                if (model.haptics && it.optString("status") in listOf("completed", "handed_off", "prepared")) window.decorView.performHapticFeedback(android.view.HapticFeedbackConstants.CONFIRM)
            }
        }
        setContent {
            ThreadTheme {
                ThreadApp(model, ::startVoice, { image.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, ::toggleCamera,
                    { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))) }, ::takePhoto, cameraPreview)
                if (showConsent) AlertDialog(onDismissRequest = { showConsent = false; consentAction = null },
                    title = { Text("Your voice, with your permission.") },
                    text = { Text("Audio, messages, shared images and relevant task context go to Google Gemini over the internet. Camera sharing is optional: Start camera sends rear-camera images until you stop or leave THREAD. Raw audio and camera frames are not saved. THREAD's task engine runs on this phone. Text, notes and results are kept on this phone.") },
                    confirmButton = { TextButton(onClick = { model.preference("consent", true); showConsent = false; consentAction?.invoke(); consentAction = null }) { Text("Continue") } },
                    dismissButton = { TextButton(onClick = { showConsent = false; consentAction = null }) { Text("Not now") } })
            }
        }
        if (savedInstanceState == null) incoming(intent)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); incoming(intent) }
    override fun onResume() {
        super.onResume(); model.refreshSpotifyConnection()
        if (model.floatingBubble) {
            if (FloatingBubbleService.allowed(this)) FloatingBubbleService.start(this)
            else { model.updateFloatingBubble(false); stopService(Intent(this, FloatingBubbleService::class.java)) }
        }
    }
    override fun onPostResume() {
        super.onPostResume()
        if (pendingTalk) { pendingTalk = false; startVoice() }
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("bubble-enable-pending", bubbleEnablePending)
        outState.putBoolean("pending-talk", pendingTalk)
        super.onSaveInstanceState(outState)
    }
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        liveCamera?.updateRotation((display?.rotation ?: 0) * 90)
    }
    override fun onPause() { model.stopCameraSharing(); super.onPause() }
    override fun onStop() { cameraRequestGeneration = null; super.onStop() }
    private fun incoming(intent: Intent) {
        if (intent.getBooleanExtra("show_task", false)) { model.route = "home"; model.taskExpanded = hasTask(model.ui) }
        if (intent.hasExtra("watch_id")) { model.watchId = intent.getStringExtra("watch_id").orEmpty(); model.route = "watches" }
        if (intent.getBooleanExtra("talk", false) || intent.action == Intent.ACTION_ASSIST) { model.route = "voice"; if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) startVoice() else pendingTalk = true }
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
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) model.talk()
        else microphone.launch(if (android.os.Build.VERSION.SDK_INT >= 33) arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS) else arrayOf(Manifest.permission.RECORD_AUDIO))
    }
    private fun updateFloatingBubble(enabled: Boolean) {
        if (!enabled) {
            bubbleEnablePending = false; model.updateFloatingBubble(false)
            stopService(Intent(this, FloatingBubbleService::class.java)); return
        }
        bubbleEnablePending = true
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            bubbleNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        else requestOverlayPermission()
    }
    private fun requestOverlayPermission() {
        if (!bubbleEnablePending) return
        if (Settings.canDrawOverlays(this)) completeBubbleEnable()
        else overlayPermission.launch(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
    }
    private fun completeBubbleEnable() {
        if (!bubbleEnablePending) return
        bubbleEnablePending = false
        if (!FloatingBubbleService.allowed(this)) {
            model.bubbleUnavailable("Floating bubble is off. Allow Display over other apps and notifications, then turn it on again.")
            return
        }
        model.updateFloatingBubble(true)
        FloatingBubbleService.start(this)
    }
    private fun takePhoto() {
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) camera.launch(null) else cameraPermission.launch(Manifest.permission.CAMERA)
    }
    private fun toggleCamera() {
        if (model.cameraSharing) { model.stopCameraSharing(); return }
        if (!model.ui.connected) return
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) startCamera()
        else { cameraRequestGeneration = model.connectionGeneration; liveCameraPermission.launch(Manifest.permission.CAMERA) }
    }
    private fun startCamera() {
        if (!model.startCameraSharing()) return
        val rotation = (display?.rotation ?: 0) * 90
        lateinit var capture: LiveCamera
        capture = LiveCamera(this, model, rotation) {
            runOnUiThread { if (liveCamera === capture) {
                model.stopCameraSharing(); model.showError("Camera sharing stopped. Check camera access and try Start camera again. Your voice conversation can continue.")
            } }
        }
        liveCamera = capture; capture.start(); cameraPreview = capture.preview
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
    override fun onDestroy() { model.stopCameraSharing(); model.closeCamera = null; model.deviceAction = null; model.requestWatchNotifications = null; model.requestFloatingBubble = null; super.onDestroy() }
}
