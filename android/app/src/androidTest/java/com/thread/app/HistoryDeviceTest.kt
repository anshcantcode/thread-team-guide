package com.thread.app

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HistoryDeviceTest {
    @Test fun newConversationArchivesTheExistingTranscriptAndHistorySurvivesRecreation() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val workspace = context.filesDir.resolve("workspace.json")
        val previousWorkspace = workspace.takeIf { it.exists() }?.readBytes()
        val prefs = context.getSharedPreferences("thread_sessions", 0)
        val previousSessions = prefs.getString("sessions", null)
        val fixture = JSONObject().put("role", "user").put("text", "Archive this local history fixture")
        try {
            check(prefs.edit().remove("sessions").commit())
            workspace.writeText(JSONObject().put("transcript", JSONArray().put(fixture)).toString())
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    val model = activity.model
                    assertEquals(fixture.getString("text"), model.ui.transcript.single().getString("text"))
                    model.newConversation()
                    assertTrue(model.ui.transcript.isEmpty())
                    val saved = model.loadSessionHistory().single()
                    assertEquals(fixture.getString("text"), saved.getString("summary"))
                    assertEquals(fixture.getString("text"), saved.getJSONArray("transcript").getJSONObject(0).getString("text"))
                }
                scenario.recreate()
                scenario.onActivity { activity ->
                    assertEquals(fixture.getString("text"), activity.model.loadSessionHistory().single().getString("summary"))
                }
            }
        } finally {
            if (previousWorkspace == null) workspace.delete() else workspace.writeBytes(previousWorkspace)
            check(prefs.edit().apply { if (previousSessions == null) remove("sessions") else putString("sessions", previousSessions) }.commit())
        }
    }
}
