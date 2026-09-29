package com.thread.app

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Deterministic native checks. No account access, playback or created alarms. */
@RunWith(AndroidJUnit4::class)
class SmartActionDeviceTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    @Before fun awake() { compose.runOnUiThread { compose.activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) } }

    @Test fun searchQueryCannotInjectASecondFilterOrAnotherDestination() {
        val query = "cats & tbm=nws / café?"
        val uri = PhoneActions.searchUri("google", query, "videos")
        assertEquals("www.google.com", uri.host)
        assertEquals(query, uri.getQueryParameter("q"))
        assertEquals(listOf("vid"), uri.getQueryParameters("tbm"))
        assertEquals("cat / music", PhoneActions.searchUri("spotify", "cat / music").lastPathSegment)
        try { PhoneActions.searchUri("arbitrary", "cats"); fail("Accepted an unsupported destination") } catch (_: IllegalArgumentException) { }
        try { PhoneActions.searchUri("google", "cats", "execute"); fail("Accepted an unsupported tab") } catch (_: IllegalArgumentException) { }
    }

    @Test fun correctionCardShowsChangedDestinationAndRetainedDetails() {
        fun state(revision: Int, destination: String) = JSONObject().put("domain", "travel").put("revision", revision)
            .put("capability", JSONObject().put("title", "Demo flights"))
            .put("slots", JSONObject().put("origin", "Chennai").put("destination", destination).put("date", "2026-09-15").put("after", "21:00"))
            .put("workspace", JSONArray()).put("transcript", JSONArray()).put("operations", JSONArray())
        compose.runOnUiThread {
            compose.activity.model.newConversation()
            compose.activity.model.acceptSnapshot(state(1, "Delhi"), false)
            compose.activity.model.acceptSnapshot(state(2, "Mumbai"), false)
            assertEquals(setOf("destination"), compose.activity.model.ui.changedSlots)
            compose.activity.model.route = "home"
        }
        compose.onNodeWithTag("active-task").performClick()
        compose.onAllNodesWithText("Chennai → Mumbai").onLast().assertIsDisplayed()
        compose.onNodeWithText("Changed").assertIsDisplayed()
        compose.onNodeWithText("2026-09-15").assertIsDisplayed()
        compose.onAllNodesWithText("Kept").assertCountEquals(3)
        screenshot("smart-correction")
    }

    @Test fun unconnectedSpotifyReceiptDoesNotLookLikePlayback() {
        compose.runOnUiThread {
            compose.activity.model.newConversation()
            val receipt = JSONObject().put("id", "phone-fixture-spotify").put("domain", "phone").put("status", "needs_connection").put("source", "Test fixture")
                .put("items", JSONArray().put(JSONObject().put("id", "phone-fixture-spotify").put("title", "Your most played").put("status", "needs_connection")
                    .put("detail", "Connect Spotify to use your listening history. Playback has not started.")))
            compose.activity.model.acceptSnapshot(JSONObject().put("workspace", JSONArray().put(receipt)), false)
            compose.activity.model.taskExpanded = true
        }
        compose.onNodeWithText("Connect your account").assertIsDisplayed()
        compose.onNodeWithText("Connect Spotify").assertIsDisplayed()
        compose.onNodeWithText("Stop remaining steps").assertDoesNotExist()
        screenshot("smart-spotify-connection")
    }

    @Test fun sportsWorkspaceRefreshCannotEraseTheCurrentTask() {
        compose.runOnUiThread {
            val model = compose.activity.model
            model.newConversation()
            model.acceptSnapshot(JSONObject().put("domain", "travel").put("revision", 3)
                .put("slots", JSONObject().put("destination", "Mumbai"))
                .put("operations", JSONArray().put(JSONObject().put("id", "test-op").put("purpose", "lookup").put("status", "running"))), false)
            val task = model.ui.task.toString()
            model.acceptSnapshot(JSONObject().put("workspace", JSONArray()).put("transcript", JSONArray(model.ui.transcript)), false)
            assertEquals(task, model.ui.task.toString())
            assertTrue(hasTask(model.ui))
        }
    }

    private fun screenshot(name: String) {
        compose.waitForIdle()
        android.os.SystemClock.sleep(450) // Let the native sheet/window animation settle too.
        InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot().let { bitmap ->
            compose.activity.filesDir.resolve("qa-$name.png").outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
        }
    }
}
