package com.thread.app

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in: real typed Gemini requests and real Google browser handoffs on the phone. */
@RunWith(AndroidJUnit4::class)
class SmartActionsLiveDeviceTest {
    @Test fun googleTabRepairSpotifyConnectionAndNativeTaskControl() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val activity = instrumentation.startActivitySync(Intent(instrumentation.targetContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val model = activity.model
        val report = JSONObject().put("passed", false).put("device", android.os.Build.MODEL).put("version", BuildConfig.VERSION_NAME)
        val stages = JSONArray()
        fun foreground() {
            // Use the same explicit launcher entry as the release-device check.
            // An app-originated start during an external browser transition is
            // not a reliable way for instrumentation to acquire the foreground.
            android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("am start -W -n com.thread.app/.MainActivity")).use { it.readBytes() }
            await(10000) { activity.lifecycle.currentState == androidx.lifecycle.Lifecycle.State.RESUMED }
        }
        fun request(words: String, predicate: () -> Boolean) {
            foreground()
            instrumentation.runOnMainSync { model.sendText(words) }
            await(90000) { predicate() || model.ui.error != null }
            assertNull(model.ui.error); assertTrue(predicate())
            stages.put(JSONObject().put("request", words).put("passed", true))
        }
        fun receiptIds() = model.ui.results.filter { it.optString("domain") == "phone" }.map { it.optString("id") }.toSet()
        try {
            instrumentation.runOnMainSync { activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); model.newConversation(); model.connect(false) }
            await(30000) { model.ui.connected || model.ui.error != null }; assertNull(model.ui.error)
            report.put("phone_session_id", model.sessionId)
            var before = receiptIds()
            request("On Google search for cat images and open the videos tab.") { (receiptIds() - before).isNotEmpty() }
            val videos = model.ui.results.last { it.optString("domain") == "phone" }
            assertEquals("handed_off", videos.optString("status")); assertEquals("videos", videos.getJSONObject("arguments").getString("tab"))
            val query = videos.getJSONObject("arguments").getString("query")
            assertTrue(query.contains("cat", true)); report.put("google_videos_receipt", videos)
            instrumentation.uiAutomation.takeScreenshot().let { bitmap -> activity.filesDir.resolve("qa-smart-google-videos.png").outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) } }
            before = receiptIds()
            request("Images instead.") { (receiptIds() - before).isNotEmpty() }
            val images = model.ui.results.last { it.optString("domain") == "phone" }
            assertEquals("handed_off", images.optString("status")); assertEquals("images", images.getJSONObject("arguments").getString("tab")); assertEquals(query, images.getJSONObject("arguments").getString("query"))
            report.put("google_images_receipt", images)
            if (model.prefs.getString("spotify-handle", null) == null) {
                before = receiptIds()
                request("Open my most played on Spotify and play it on loop.") { (receiptIds() - before).isNotEmpty() }
                assertEquals("needs_connection", model.ui.results.last { it.optString("domain") == "phone" }.optString("status"))
            }
            foreground()
            instrumentation.runOnMainSync { model.newConversation(); model.connect(false) }
            await(30000) { model.ui.connected || model.ui.error != null }; assertNull(model.ui.error)
            request("Show demo flights from Chennai to Delhi on September 15 2026 after 9 PM.") { model.ui.task?.optJSONObject("slots")?.optString("destination") == "Delhi" }
            request("Actually Mumbai. Keep the same date and time.") { model.ui.task?.optJSONObject("slots")?.optString("destination") == "Mumbai" }
            val slots = model.ui.task!!.getJSONObject("slots")
            assertEquals("Chennai", slots.getString("origin")); assertEquals("2026-09-15", slots.getString("date")); assertEquals("21:00", slots.getString("after"))
            instrumentation.runOnMainSync { model.controlTask("pause") }
            await(10000) { model.ui.task?.optBoolean("paused") == true }
            instrumentation.runOnMainSync { model.controlTask("resume") }
            await(10000) { model.ui.task?.optBoolean("paused") == false }
            instrumentation.runOnMainSync { model.taskExpanded = true }
            android.os.SystemClock.sleep(500)
            instrumentation.uiAutomation.takeScreenshot().let { bitmap -> activity.filesDir.resolve("qa-smart-live-task.png").outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) } }
            report.put("final_task", model.ui.task).put("passed", true)
        } catch (error: Throwable) { report.put("error", error.stackTraceToString()); throw error }
        finally {
            report.put("stages", stages).put("session_id", model.sessionId).put("activity_state", activity.lifecycle.currentState.name).put("phone_receipt_ids", JSONArray(receiptIds().toList())).put("scope", "Actual typed native Gemini, browser handoffs and controller controls. No microphone/acoustic claim. Spotify connection-needed check only when no account is configured; no Spotify playback test.")
            activity.filesDir.resolve("qa-smart-live-device.json").writeText(report.toString(2))
            instrumentation.runOnMainSync { model.taskExpanded = false; model.disconnect(false); activity.finishAndRemoveTask() }
        }
    }
    private fun await(timeout: Long, condition: () -> Boolean) {
        val until = android.os.SystemClock.elapsedRealtime() + timeout
        while (!condition()) { if (android.os.SystemClock.elapsedRealtime() > until) throw AssertionError("Smart action timed out"); android.os.SystemClock.sleep(100) }
    }
}
