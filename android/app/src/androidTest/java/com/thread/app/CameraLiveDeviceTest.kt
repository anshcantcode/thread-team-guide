package com.thread.app

import android.Manifest
import android.content.Intent
import android.media.AudioRecord
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in: opens the physical rear camera and sends frames to the configured Gemini service. */
@RunWith(AndroidJUnit4::class)
class CameraLiveDeviceTest {
    @Test fun realCameraPermissionFramesStopAndBackground() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.RECORD_AUDIO)
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val model = activity.model
        val checks = JSONArray()
        val report = JSONObject().put("passed", false).put("device", android.os.Build.MODEL).put("checks", checks)
        fun field(owner: Any, name: String): Any? = owner.javaClass.getDeclaredField(name).apply { isAccessible = true }.get(owner)
        fun gate() = field(model, "cameraGate")!!
        fun sequence() = field(gate(), "sequence") as Long
        fun find(vararg labels: String): AccessibilityNodeInfo? {
            fun walk(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
                if (node == null) return null
                if (node.isVisibleToUser && (node.text?.toString() in labels || node.contentDescription?.toString() in labels || node.viewIdResourceName in labels)) return node
                for (i in 0 until node.childCount) walk(node.getChild(i))?.let { return it }
                return null
            }
            return walk(instrumentation.uiAutomation.rootInActiveWindow)
        }
        fun await(step: String, timeout: Long = 15000, condition: () -> Boolean) {
            val deadline = SystemClock.elapsedRealtime() + timeout
            while (!condition()) {
                if (SystemClock.elapsedRealtime() >= deadline) fail("Timed out: $step. App error: ${model.ui.error}")
                SystemClock.sleep(100)
            }
        }
        fun click(vararg labels: String) {
            await("click ${labels.joinToString()}") {
                var node = find(*labels)
                while (node != null && !node.isClickable && node.parent != null) node = node.parent
                node?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true
            }
        }
        fun startCamera() {
            click("Start camera")
            await("camera consent") { find("Share your camera?") != null }
            click("Start camera")
        }
        fun frames(after: Long) {
            await("frame delivery and current acknowledgment", 25000) {
                model.cameraSharing && sequence() >= after + 3 && field(gate(), "pending") == null
                    && field(model, "rejectedCameraFrames") == 0 && ((field(activity, "liveCamera") as? LiveCamera)?.previewFrames ?: 0) > 0
            }
            val audio = field(model, "audio")!!
            assertEquals(AudioRecord.RECORDSTATE_RECORDING, (field(audio, "record") as AudioRecord).recordingState)
            assertTrue((field(audio, "capture") as Thread).isAlive)
            assertNotNull(find("Camera active"))
            assertNotNull(find("Stop camera"))
            assertNull(model.ui.error)
        }
        fun stopped(check: String) {
            await(check) { !model.cameraSharing }
            val count = sequence()
            SystemClock.sleep(2500)
            assertEquals("No frames queued after $check", count, sequence())
            assertNull(field(activity, "liveCamera"))
            checks.put(check)
        }
        try {
            instrumentation.runOnMainSync {
                activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                model.newConversation()
            }
            click("Start talking")
            if (!model.consent) click("Continue")
            await("live voice ready", 60000) { model.ui.connected || model.ui.error != null }
            assertNull(model.ui.error); assertTrue(model.ui.connected)
            assertFalse(model.cameraSharing); assertEquals(0L, sequence())
            checks.put("voice starts with camera off")
            startCamera()
            click("Don't allow", "Don’t allow", "com.android.permissioncontroller:id/permission_deny_button")
            await("permission denial") { model.ui.error != null }
            assertFalse(model.cameraSharing); assertEquals(0L, sequence()); assertTrue(model.ui.connected)
            click("Continue conversation")
            checks.put("camera permission denial preserves voice")
            startCamera()
            click("While using the app", "com.android.permissioncontroller:id/permission_allow_foreground_only_button")
            frames(0)
            checks.put("camera grant and acknowledged JPEG delivery with live microphone")
            val expectedObject = InstrumentationRegistry.getArguments().getString("expected_object")
            if (!expectedObject.isNullOrBlank()) {
                val beforeRecognition = sequence()
                instrumentation.runOnMainSync { model.sendText("Look at my currently shared camera image and briefly name the main visible animal or object. If the image is unclear, say so. Do not perform any actions.") }
                frames(beforeRecognition)
                await("recognition of user supplied object", 45000) {
                    model.ui.captionRole == "assistant" && Regex("\\b${Regex.escape(expectedObject)}\\b", RegexOption.IGNORE_CASE).containsMatchIn(model.ui.caption)
                }
                checks.put("Gemini independently named the user supplied $expectedObject picture")
            }
            val camera = field(activity, "liveCamera") as LiveCamera
            val initialFrames = camera.previewFrames
            val initialTime = SystemClock.elapsedRealtime()
            SystemClock.sleep(3000)
            val windowMs = SystemClock.elapsedRealtime() - initialTime
            val displayedFrames = camera.previewFrames - initialFrames
            val fps = displayedFrames * 1000.0 / windowMs
            report.put("preview_fps", fps).put("preview_frames", displayedFrames).put("preview_window_ms", windowMs)
            assertTrue("Continuous native preview should exceed 20 fps, measured $fps", fps >= 20)
            checks.put("native preview exceeds 20 fps with live microphone and image uploads")
            val first = sequence()
            instrumentation.runOnMainSync { model.sendText("For this camera test, say only ready. Do not perform any actions.") }
            frames(first)
            assertSame("Speech correction keeps the native preview alive", camera, field(activity, "liveCamera"))
            assertTrue(camera.previewFrames > initialFrames + displayedFrames)
            await("Gemini spoken response", 30000) { (field(field(model, "audio")!!, "writtenFrames") as Long) > 0 }
            checks.put("fresh frames after typed correction and real AudioTrack output")
            instrumentation.runOnMainSync {
                model.openResult = JSONObject().put("id", "camera-check-result").put("domain", "calculate").put("source", "Device test fixture")
                    .put("items", JSONArray().put(JSONObject().put("title", "Camera dock test").put("value", 156)))
            }
            await("result dock") { find("End conversation") != null }
            assertSame("Result navigation keeps the native preview alive", camera, field(activity, "liveCamera"))
            val resultFrames = camera.previewFrames
            SystemClock.sleep(1000)
            assertTrue("Result preview continues rendering", camera.previewFrames - resultFrames >= 15)
            assertNotNull(find("Camera active")); click("Stop camera")
            stopped("stop on result screen prevents later frames")
            assertTrue(model.ui.connected)
            click("Back")
            val beforeRestart = sequence(); startCamera(); frames(beforeRestart)
            instrumentation.runOnMainSync { model.keyboard = true }
            stopped("covering sheet stops camera")
            instrumentation.runOnMainSync { model.keyboard = false }
            val beforeBackground = sequence(); startCamera(); frames(beforeBackground)
            instrumentation.uiAutomation.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_HOME)
            stopped("Home stops camera")
            instrumentation.runOnMainSync { activity.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            await("return from Home") { find("Start camera") != null }
            assertFalse(model.cameraSharing)
            val beforeEnd = sequence(); startCamera(); frames(beforeEnd)
            click("End")
            stopped("End stops camera")
            assertFalse(model.ui.connected)
            report.put("passed", true).put("frames_queued", sequence())
                .put("measurement", "Local enqueue count; latest frame acknowledgment accepted at each delivery checkpoint. Not a cumulative provider acceptance counter.")
        } catch (error: Throwable) {
            report.put("error", error.message); throw error
        } finally {
            instrumentation.runOnMainSync { model.disconnect(false) }
            activity.filesDir.resolve("qa-camera-live-device.json").writeText(report.toString(2))
        }
    }
}
