package com.thread.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class Fdb3ClientDeviceTest {
    @Test fun hostInterruptionBeforeLocalVadCancelsQueuedPlaybackWithAnHonestOffset() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val events = java.util.concurrent.CopyOnWriteArrayList<JSONObject>()
        val audio = LiveAudio(context, events::add, {}, { _, _ -> }, { error(it) })
        try {
            audio.start(false)
            audio.event(JSONObject().put("type", "audio").put("message_id", "queued-reply")
                .put("sample_rate", 24000).put("data", android.util.Base64.encodeToString(ByteArray(48000), android.util.Base64.NO_WRAP)))
            // No microphone onset or pause event precedes this SDK-originated interruption.
            audio.event(JSONObject().put("type", "interrupted").put("recoverable", false))
            val receipt = events.single { it.optString("status") == "interrupted" }
            assertEquals("queued-reply", receipt.getString("message_id"))
            assertTrue(receipt.getDouble("played_ms") in 0.0..1000.0)
            audio.event(JSONObject().put("type", "turn_complete").put("message_id", "queued-reply"))
            Thread.sleep(80)
            assertFalse(events.any { it.optString("status") == "played" })
        } finally { audio.close() }
    }

    @Test fun kitchenOpensWithoutCredentialsOrMicrophoneAndKeepsItsScopeVisible() {
        fun texts(view: android.view.View): List<String> = when (view) {
            is android.widget.TextView -> listOf(view.text.toString())
            is android.view.ViewGroup -> (0 until view.childCount).flatMap { texts(view.getChildAt(it)) }
            else -> emptyList()
        }
        ActivityScenario.launch(Fdb3Activity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val visible = texts(activity.window.decorView)
                assertTrue(visible.contains("Connect and talk"))
                assertTrue(visible.contains("Connect without microphone"))
                assertTrue(visible.contains("Saved on this phone"))
                assertTrue(visible.any { it.startsWith("Disconnected.") })
                assertTrue(visible.any { it.contains("does not use your saved Gemini key") })
            }
            val instrument = InstrumentationRegistry.getInstrumentation()
            instrument.uiAutomation.takeScreenshot().let { screenshot ->
                val file = instrument.targetContext.getExternalFilesDir(null)!!.resolve("checkpoint-kitchen.png")
                file.outputStream().use { screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
                screenshot.recycle()
            }
        }
    }

    @Test fun networkKitchenPersistsAndRejectsStaleInputsAndNonChecklistCommands() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        // This test uses a dedicated preferences namespace by preserving/restoring only its own setup.
        val clientPrefs = context.getSharedPreferences("fdb3-client", 0)
        val previous = clientPrefs.all.toMap()
        val session = UUID.randomUUID().toString().replace("-", "")
        check(clientPrefs.edit().clear().putString("session", session).commit())
        try {
            val store = Fdb3ClientStore(context)
            fun command(name: String, args: JSONObject = JSONObject()) = JSONObject()
                .put("session_id", session).put("request_id", UUID.randomUUID().toString().replace("-", ""))
                .put("input_token", store.inputToken).put("command", name).put("args", args)
            val add = command("add_checklist_item", JSONObject().put("text", "Rinse the mint"))
            val result = store.execute(add)
            assertEquals("success", result.getString("status"))
            assertEquals(result.toString(), store.execute(add).toString())
            assertEquals(1, result.getJSONArray("items").length())
            val stale = command("add_checklist_item", JSONObject().put("text", "Old request"))
            store.newInput()
            assertEquals("error", store.execute(stale).getString("status"))
            for (name in listOf("cleanup", "set_input", "request_timer_handoff"))
                assertEquals("error", store.execute(command(name)).getString("status"))
            val reopened = Fdb3ClientStore(context)
            assertEquals(session, reopened.sessionId)
            assertTrue(reopened.displayItems().contains("Rinse the mint"))
            assertFalse(reopened.displayItems().contains("Old request"))
            assertEquals("error", reopened.execute(add).getString("status"))
            assertTrue(reopened.lastReceipt().contains("Rinse the mint"))
        } finally {
            context.getSharedPreferences("fdb3-$session", 0).edit().clear().commit()
            val restore = clientPrefs.edit().clear()
            for ((key, value) in previous) when (value) {
                is String -> restore.putString(key, value)
                is Boolean -> restore.putBoolean(key, value)
                is Int -> restore.putInt(key, value)
                is Long -> restore.putLong(key, value)
            }
            check(restore.commit())
        }
    }

    @Test fun hostSelectionRejectsCredentialsAndUnprotectedRemoteEndpoints() {
        assertEquals("http://127.0.0.1:8768", Fdb3Activity.checkedHost("http://127.0.0.1:8768/"))
        assertEquals("https://example.org", Fdb3Activity.checkedHost("https://example.org"))
        for (host in listOf("http://192.168.1.4:8768", "https://user:secret@example.org", "https://example.org/path", "https://example.org?key=secret", "https://example.org:65536", "javascript:alert(1)")) {
            assertTrue(runCatching { Fdb3Activity.checkedHost(host) }.isFailure)
        }
    }
}
