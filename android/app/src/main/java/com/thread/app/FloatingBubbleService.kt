package com.thread.app

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.database.ContentObserver
import android.graphics.PixelFormat
import android.os.*
import android.provider.Settings
import android.view.*
import android.view.WindowInsets as PlatformInsets
import android.widget.FrameLayout
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.*
import androidx.savedstate.*
import org.json.JSONArray
import kotlin.math.hypot
import kotlin.math.roundToInt

/** Overlay controls only. VoiceService owns the foreground microphone lifetime. */
class FloatingBubbleService : Service(), LifecycleOwner, SavedStateRegistryOwner {
    private val life = LifecycleRegistry(this)
    private val saved = SavedStateRegistryController.create(this)
    override val lifecycle: Lifecycle get() = life
    override val savedStateRegistry: SavedStateRegistry get() = saved.savedStateRegistry
    private val main = Handler(Looper.getMainLooper())
    private val model get() = ThreadApplication.model(this)
    private lateinit var windows: WindowManager
    private lateinit var windowContext: Context
    private var bubble: FrameLayout? = null
    private var chip: ComposeView? = null
    private var target: ComposeView? = null
    private var safe = BubbleBounds(0, 0, 0, 0)
    private var bounds = safe
    private var point = BubblePoint(0, 0)
    private var dragging = false
    private var overTarget by mutableStateOf(false)
    private var motionRevision by mutableIntStateOf(0)
    private var visible = false
    private val size get() = dp(64)
    private val chipHeight get() = dp(60)
    private val motionObserver = object : ContentObserver(main) {
        override fun onChange(selfChange: Boolean) { motionRevision++ }
    }
    private val permissionListener = AppOpsManager.OnOpChangedListener { _, packageName ->
        if (packageName == this.packageName) main.post { if (!allowed(this)) stopBubble(endVoice = true) }
    }
    private val screen = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) { updateVisibility() }
    }

    override fun onCreate() {
        super.onCreate()
        saved.performAttach(); saved.performRestore(null); life.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
        val display = getSystemService(android.hardware.display.DisplayManager::class.java).getDisplay(Display.DEFAULT_DISPLAY)
        windowContext = createWindowContext(display, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, null)
        windows = windowContext.getSystemService(WindowManager::class.java)
        contentResolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, motionObserver)
        getSystemService(AppOpsManager::class.java).startWatchingMode(AppOpsManager.OPSTR_SYSTEM_ALERT_WINDOW, packageName, permissionListener)
        val filter = IntentFilter().apply { addAction(Intent.ACTION_SCREEN_OFF); addAction(Intent.ACTION_SCREEN_ON); addAction(Intent.ACTION_USER_PRESENT) }
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(screen, filter, RECEIVER_NOT_EXPORTED) else registerReceiver(screen, filter)
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) { stopBubble(endVoice = true); return START_NOT_STICKY }
        if (!BubblePermissionGate.canShow(model.floatingBubble, Settings.canDrawOverlays(this), notificationsAllowed(this))) {
            stopBubble(endVoice = false); return START_NOT_STICKY
        }
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "Floating bubble", NotificationManager.IMPORTANCE_LOW))
            val open = PendingIntent.getActivity(this, 310, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            val stop = PendingIntent.getService(this, 311, Intent(this, FloatingBubbleService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
            val notification = Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_thread)
                .setContentTitle("THREAD floating bubble").setContentText("Tap the bubble to talk · Stop ends voice and removes the bubble")
                .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).setVisibility(Notification.VISIBILITY_PRIVATE)
                .addAction(Notification.Action.Builder(null, "Stop", stop).build()).build()
            startForeground(11, notification, if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0)
            if (bubble == null) attachWindows()
            updateVisibility()
        } catch (_: RuntimeException) {
            stopBubble(endVoice = false)
            model.bubbleUnavailable("Floating bubble could not be shown. Check Display over other apps and notification permissions.")
        }
        return START_NOT_STICKY // No boot receiver, background resurrection or automatic recording.
    }

    private fun dp(value: Int) = (value * windowContext.resources.displayMetrics.density).roundToInt()
    private fun recalculateBounds(insets: PlatformInsets? = null) {
        val metrics = windows.currentWindowMetrics
        val area = metrics.bounds
        val currentInsets = insets ?: metrics.windowInsets
        val bars = currentInsets.getInsetsIgnoringVisibility(PlatformInsets.Type.systemBars() or PlatformInsets.Type.displayCutout() or PlatformInsets.Type.systemGestures())
        val ime = currentInsets.getInsets(PlatformInsets.Type.ime())
        safe = BubbleBounds(bars.left + dp(8), bars.top + dp(8), area.width() - bars.right - dp(8), area.height() - maxOf(bars.bottom, ime.bottom) - dp(8))
        bounds = safe.copy(top = minOf(safe.top + chipHeight + dp(4), maxOf(safe.top, safe.bottom - size)))
    }
    private fun params(width: Int, height: Int, touch: Boolean = true) = WindowManager.LayoutParams(
        width, height, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED or (if (touch) 0 else WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE), PixelFormat.TRANSLUCENT
    ).apply {
        gravity = Gravity.TOP or Gravity.LEFT
        setFitInsetsTypes(0) // Explicit physical safe bounds above avoid double-counting system insets.
        layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
        // No snap/entrance animation; motion is entirely the existing orb's Android setting.
        windowAnimations = 0
        // Android 12+ permits touch-through untrusted overlays only below its opacity limit.
        if (!touch) alpha = .79f
    }
    private fun compose(content: @Composable () -> Unit) = ComposeView(windowContext).apply {
        setViewTreeLifecycleOwner(this@FloatingBubbleService)
        setViewTreeSavedStateRegistryOwner(this@FloatingBubbleService)
        setContent { ThreadTheme(content) }
    }
    private fun attachWindows() {
        recalculateBounds()
        val prefs = model.prefs
        point = bounds.snap(if (prefs.getBoolean("bubble-right", true)) bounds.right else bounds.left,
            bounds.top + ((bounds.bottom - bounds.top - size).coerceAtLeast(0) * prefs.getFloat("bubble-y", .4f).coerceIn(0f, 1f)).roundToInt(), size)
        val orb = compose {
            val ui = model.ui
            LaunchedEffect(ui.caption) { updateCaptionVisibility() }
            val receipt = StoredWidgetText.receipt(JSONArray(ui.results))?.takeIf { it.confirmed }?.id
            val listening = orbPhaseFor(ui.connected, ui.connecting, ui.muted, ui.error != null, ui.mode, ui.activeAction != null) == OrbPhase.Listening
            val feedback = remember { BubbleFeedback(receipt, listening) }
            LaunchedEffect(listening, receipt, model.haptics) {
                val change = feedback.update(listening, receipt, model.haptics)
                if (visible) {
                    if (change.confirm) bubble?.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
                    else if (change.tick) bubble?.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)
                }
            }
            Box(Modifier.fillMaxSize().semantics {
                role = Role.Button
                contentDescription = "THREAD: ${if (ui.muted && ui.connected) "Microphone muted" else ui.mode}"
                onClick("Talk or interrupt") { tap(); true }
                onLongClick("Open THREAD") { openThread(false); true }
                customActions = listOf(CustomAccessibilityAction("Dismiss bubble and end voice") { stopBubble(true); true },
                    CustomAccessibilityAction("Move to left edge") { moveTo(bounds.left, point.y, true); true },
                    CustomAccessibilityAction("Move to right edge") { moveTo(bounds.right, point.y, true); true })
            }) {
                key(motionRevision) {
                    LivingSphere(model, Modifier.fillMaxSize(), motionEnabled = android.animation.ValueAnimator.areAnimatorsEnabled())
                }
            }
        }
        bubble = object : FrameLayout(windowContext) {
            override fun onInterceptTouchEvent(event: MotionEvent) = true
            override fun onTouchEvent(event: MotionEvent) = touch(event)
        }.apply {
            // Compose resolves its window recomposer from the window's root view, so the owners must live here too.
            setViewTreeLifecycleOwner(this@FloatingBubbleService)
            setViewTreeSavedStateRegistryOwner(this@FloatingBubbleService)
            addView(orb, FrameLayout.LayoutParams(-1, -1))
            setOnApplyWindowInsetsListener { _, insets ->
                val before = safe
                recalculateBounds(insets)
                if (before != safe) main.post { point = bounds.clamp(point.x, point.y, size); placeWindows() }
                insets
            }
        }
        chip = compose {
            if (model.ui.caption.isNotBlank()) Surface(shape = RoundedCornerShape(16.dp), color = Panel) {
                Text(model.ui.caption.take(400), color = White, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp).semantics { liveRegion = LiveRegionMode.Polite })
            }
        }
        target = compose {
            Surface(shape = RoundedCornerShape(32.dp), color = if (overTarget) Blue else Panel) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("×", color = White, fontSize = 28.sp) }
            }
        }.apply { contentDescription = "Drop here to dismiss and end voice"; visibility = View.GONE }
        windows.addView(bubble, params(size, size))
        windows.addView(chip, params(minOf(dp(240), (safe.right - safe.left).coerceAtLeast(1)), chipHeight, false))
        windows.addView(target, params(size, size, false))
        placeWindows()
    }

    private var downX = 0f
    private var downY = 0f
    private var origin = BubblePoint(0, 0)
    private var longPressed = false
    private val longPress = Runnable { if (!dragging) { longPressed = true; openThread(false) } }
    private fun touch(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.rawX; downY = event.rawY; origin = point; dragging = false; longPressed = false
                main.postDelayed(longPress, ViewConfiguration.getLongPressTimeout().toLong())
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.rawX - downX; val dy = event.rawY - downY
                if (!longPressed && hypot(dx.toDouble(), dy.toDouble()) > ViewConfiguration.get(this).scaledTouchSlop) {
                    main.removeCallbacks(longPress); dragging = true
                    target?.visibility = if (visible) View.VISIBLE else View.GONE
                    point = bounds.clamp(origin.x + dx.roundToInt(), origin.y + dy.roundToInt(), size)
                    overTarget = onDismissTarget(point, safe.dismissTarget(size), size); placeWindows()
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                main.removeCallbacks(longPress)
                val released = event.actionMasked == MotionEvent.ACTION_UP
                if (dragging && released && overTarget) { stopBubble(true); return true }
                if (dragging) moveTo(point.x, point.y, true) else if (released && !longPressed) tap()
                dragging = false; overTarget = false; target?.visibility = View.GONE
            }
        }
        return true
    }
    private fun moveTo(x: Int, y: Int, snap: Boolean) {
        point = if (snap) bounds.snap(x, y, size) else bounds.clamp(x, y, size)
        model.prefs.edit().putBoolean("bubble-right", point.x > (bounds.left + bounds.right - size) / 2)
            .putFloat("bubble-y", (point.y - bounds.top).toFloat() / (bounds.bottom - bounds.top - size).coerceAtLeast(1)).apply()
        placeWindows()
    }
    private fun placeWindows() {
        fun place(view: View?, x: Int, y: Int) {
            if (view?.isAttachedToWindow != true) return
            val layout = view.layoutParams as WindowManager.LayoutParams
            layout.x = x; layout.y = y
            try { windows.updateViewLayout(view, layout) } catch (_: RuntimeException) { stopBubble(true) }
        }
        place(bubble, point.x, point.y)
        val width = chip?.layoutParams?.width ?: dp(240)
        place(chip, (point.x + size / 2 - width / 2).coerceIn(safe.left, maxOf(safe.left, safe.right - width)), maxOf(safe.top, point.y - chipHeight - dp(4)))
        val dismiss = safe.dismissTarget(size); place(target, dismiss.x, dismiss.y)
    }
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (bubble != null) {
            // Recreate only the views for density/font/inset changes, retaining the same model/audio.
            detachWindows(); attachWindows(); updateVisibility()
        }
    }
    private fun updateVisibility() {
        visible = getSystemService(PowerManager::class.java).isInteractive && !getSystemService(KeyguardManager::class.java).isKeyguardLocked
        bubble?.visibility = if (visible) View.VISIBLE else View.GONE
        updateCaptionVisibility()
        target?.visibility = if (visible && dragging) View.VISIBLE else View.GONE
        life.currentState = if (visible) Lifecycle.State.RESUMED else Lifecycle.State.CREATED
    }
    private fun updateCaptionVisibility() {
        chip?.visibility = if (visible && model.ui.caption.isNotBlank()) View.VISIBLE else View.GONE
    }
    private fun tap() {
        if (!allowed(this)) { stopBubble(true); return }
        when (BubblePermissionGate.tap(model.consent, checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED,
            model.microphoneServiceReady, model.ui.connected, model.ui.connecting)) {
            BubbleTap.TALK_IN_SESSION -> model.talk()
            BubbleTap.OPEN_THREAD -> openThread(true)
            BubbleTap.NONE -> Unit
        }
    }
    private fun openThread(talk: Boolean) {
        try { startActivity(Intent(this, MainActivity::class.java).putExtra("talk", talk).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)) }
        catch (_: RuntimeException) { stopBubble(false); model.bubbleUnavailable("Open THREAD from its notification to continue.") }
    }
    private fun stopBubble(endVoice: Boolean) {
        model.updateFloatingBubble(false)
        if (endVoice) model.disconnect()
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
    }
    private fun detachWindows() {
        listOf(bubble, chip, target).forEach { view ->
            if (view is ComposeView) view.disposeComposition()
            if (view is FrameLayout) (view.getChildAt(0) as? ComposeView)?.disposeComposition()
            if (view?.isAttachedToWindow == true) runCatching { windows.removeViewImmediate(view) }
        }
        bubble = null; chip = null; target = null
    }
    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        contentResolver.unregisterContentObserver(motionObserver)
        getSystemService(AppOpsManager::class.java).stopWatchingMode(permissionListener)
        unregisterReceiver(screen); detachWindows(); life.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY)
        super.onDestroy()
    }
    companion object {
        private const val CHANNEL = "floating-bubble"
        private const val STOP = "com.thread.app.STOP_BUBBLE"
        private fun notificationsAllowed(context: Context): Boolean {
            val manager = context.getSystemService(NotificationManager::class.java)
            return manager.areNotificationsEnabled() && manager.getNotificationChannel(CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE &&
                (Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
        }
        fun allowed(context: Context) = Settings.canDrawOverlays(context) && notificationsAllowed(context)
        fun start(context: Context) {
            try { context.startForegroundService(Intent(context, FloatingBubbleService::class.java)) }
            catch (_: RuntimeException) {
                ThreadApplication.model(context).bubbleUnavailable("Open THREAD to enable the floating bubble.")
            }
        }
    }
}
