package com.thread.app

import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

/** Opt-in local-host integration; excluded from the default device suite. No microphone. */
@RunWith(AndroidJUnit4::class)
class Fdb3ClientHostTest {
    private fun views(view: View): List<View> = listOf(view) +
        if (view is ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()

    @Test fun realHostChangesNativeChecklistAndTheReceiptSurvivesReopening() {
        org.junit.Assume.assumeTrue("Opt in with -e thread_kitchen_host true", InstrumentationRegistry.getArguments().getString("thread_kitchen_host") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        check(android.os.Build.HARDWARE in setOf("ranchu", "goldfish")) { "Use an explicitly owned emulator" }
        val prefs = context.getSharedPreferences("fdb3-client", 0)
        val previous = prefs.all.toMap()
        val session = UUID.randomUUID().toString().replace("-", "")
        check(prefs.edit().clear().putString("session", session).putString("host", "http://127.0.0.1:8768").commit())
        try {
            ActivityScenario.launch(Fdb3Activity::class.java).use { scenario ->
                fun textMatches(predicate: (String) -> Boolean): Boolean {
                    var found = false
                    scenario.onActivity { activity -> found = views(activity.window.decorView).filterIsInstance<TextView>().any { predicate(it.text.toString()) } }
                    return found
                }
                fun waitFor(label: String, predicate: (String) -> Boolean) {
                    val until = android.os.SystemClock.elapsedRealtime() + 150000
                    while (!textMatches(predicate)) {
                        check(android.os.SystemClock.elapsedRealtime() < until) { "Timed out: $label" }
                        Thread.sleep(100)
                    }
                }
                fun click(label: String) = scenario.onActivity { activity ->
                    views(activity.window.decorView).filterIsInstance<TextView>().single { it.text.toString() == label }.performClick()
                }
                click("Connect without microphone")
                waitFor("host connection") { it == "Connected. Type a request." }
                scenario.onActivity { activity ->
                    views(activity.window.decorView).filterIsInstance<EditText>().single { it.hint?.toString() == "Ask for a checklist change" }
                        .setText("Add wash the radishes to my checklist.")
                }
                click("Send request")
                waitFor("actual saved checklist") { it.startsWith("○ ") && it.contains("wash the radishes", ignoreCase = true) }
                waitFor("native receipt") { it.startsWith("Added checklist step:") && it.contains("radishes", ignoreCase = true) }
                waitFor("native PCM playback") { it == "Speaking" }
                waitFor("native playback head reaching the end") { it == "Ready" }
                var spokenCaption = ""
                scenario.onActivity { activity ->
                    spokenCaption = views(activity.window.decorView).filterIsInstance<TextView>()
                        .single { it.text.toString().startsWith("THREAD:") }.text.toString()
                }
                assertTrue(spokenCaption.contains("radishes", ignoreCase = true))
                assertFalse("Internal receipt IDs must not be narrated", Regex("[a-f0-9]{32}").containsMatchIn(spokenCaption))
                instrumentation.uiAutomation.takeScreenshot().let { screenshot ->
                    context.getExternalFilesDir(null)!!.resolve("checkpoint-kitchen-live.png").outputStream().use {
                        screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it)
                    }
                    screenshot.recycle()
                }
                click("End conversation")
                scenario.recreate()
                assertTrue(textMatches { it.startsWith("○ ") && it.contains("radishes", ignoreCase = true) })
                assertTrue(textMatches { it.startsWith("Added checklist step:") })
                val record = org.json.JSONObject().put("session_id", session).put("passed", true)
                    .put("input", "typed, no microphone").put("scope", "actual local host to native persisted checklist and receipt; AudioTrack PCM playout; restart retained; no physical acoustic measurement")
                    .put("saved_items", org.json.JSONArray(context.getSharedPreferences("fdb3-$session", 0).getString("items", "[]")))
                    .put("spoken_caption", spokenCaption)
                    .put("tool_receipts", org.json.JSONArray(context.getSharedPreferences("fdb3-$session", 0).all.toSortedMap()
                        .filterKeys { it.startsWith("request-") }.values.map { org.json.JSONObject(it as String) }))
                context.getExternalFilesDir(null)!!.resolve("checkpoint-kitchen-live.json").writeText(record.toString(2))
            }
        } finally {
            context.getSharedPreferences("fdb3-$session", 0).edit().clear().commit()
            val restore = prefs.edit().clear()
            for ((key, value) in previous) when (value) {
                is String -> restore.putString(key, value)
                is Boolean -> restore.putBoolean(key, value)
                is Int -> restore.putInt(key, value)
                is Long -> restore.putLong(key, value)
            }
            check(restore.commit())
        }
    }
}
