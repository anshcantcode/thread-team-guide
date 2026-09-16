package com.thread.app

import android.appwidget.AppWidgetManager
import android.content.Intent
import android.provider.AlarmClock
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.Before
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ThreadDeviceTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    @Before fun stayAwakeDuringChecks() { compose.runOnUiThread { compose.activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) } }

    @Test fun startAndNativeNavigation() {
        compose.onNodeWithText("Go on.").assertIsDisplayed()
        screenshot("start")
        compose.onNodeWithText("Start talking").assertIsDisplayed()
        compose.onNodeWithContentDescription("Settings").performClick()
        compose.onNodeWithText("Make yourself\nat home.").assertIsDisplayed()
        compose.onNodeWithText("Kore").assertIsDisplayed()
        screenshot("settings")
        compose.onNodeWithContentDescription("Back").performClick()
        compose.onNodeWithText("Go on.").assertIsDisplayed()
    }

    @Test fun typingSheetIsReachableWithoutMicrophone() {
        compose.onNodeWithText("Type instead").performClick()
        compose.onNodeWithText("Say it your way.").assertIsDisplayed()
        compose.onNodeWithText("Ask, plan, or change your mind…").performTextInput("Set an alarm for 5 PM")
        compose.onNodeWithText("Send").assertIsEnabled()
    }

    @Test fun phoneValidationPreventsMalformedSideEffects() {
        compose.runOnUiThread {
            val actions = PhoneActions(compose.activity) { }
            val invalid = listOf(
                JSONObject().put("hour", 24).put("minute", 0).put("label", "Invalid"),
                JSONObject().put("hour", 5).put("minute", -1).put("label", "Invalid"),
                JSONObject().put("hour", 5).put("minute", 0).put("label", ""),
                JSONObject().put("hour", 4294967313L).put("minute", 0).put("label", "Invalid"))
            invalid.forEachIndexed { i, args -> assertEquals("failed", actions.execute(JSONObject().put("request_id", "phone-invalid-$i").put("action", "set_alarm").put("arguments", args)).getString("status")) }
            assertEquals("failed", actions.execute(JSONObject().put("request_id", "phone-unknown").put("action", "execute_shell")).getString("status"))
        }
    }

    @Test fun exactClockIntentHasAReceiverOnThisDevice() {
        val context = compose.activity
        assertNotNull(Intent(AlarmClock.ACTION_SET_ALARM).resolveActivity(context.packageManager))
        assertNotNull(Intent(AlarmClock.ACTION_SET_TIMER).resolveActivity(context.packageManager))
    }

    @Test fun widgetPreviewUsesActualSuppliedValuesAndDoesNotClaimPinning() {
        compose.runOnUiThread {
            val config = JSONObject().put("title", "Layout verification").put("results", JSONArray().put(JSONObject().put("id", "test-weather").put("domain", "weather").put("source", "Test fixture")
                .put("items", JSONArray().put(JSONObject().put("title", "Test city").put("temperature", 29).put("condition", "Clear").put("wind", 12)))))
            val view = ThreadWidget.preview(compose.activity, config)
            val list = view.findViewById<android.widget.ListView>(R.id.widget_list)
            assertTrue(list.adapter.count > 0)
            val hero = list.adapter.getView(0, null, list)
            assertEquals("29°", hero.findViewById<android.widget.TextView>(R.id.hero_value).text.toString())
            assertTrue(hero.findViewById<android.widget.TextView>(R.id.hero_detail).text.contains("12"))
            compose.activity.model.widget = config
        }
        compose.onNodeWithText("Your widget").assertIsDisplayed()
        compose.onNodeWithText("Add to home screen").assertIsDisplayed()
        screenshot("widget")
    }

    @Test fun interruptedNoiseMarkersAreDifferentFromRealWords() {
        assertFalse(LiveAudio.hasWords("[noise]")); assertFalse(LiveAudio.hasWords("[silence] …"))
        assertTrue(LiveAudio.hasWords("Actually, tomorrow")); assertTrue(LiveAudio.hasWords("नहीं शाम को"))
    }
    @Test fun widgetRefreshCanScheduleOnTheActualAndroidPlatform() {
        val context = compose.activity
        val fixtureWidgetId = 900001
        try {
            ThreadWidget.refresh(context, fixtureWidgetId)
            assertNotNull(context.getSystemService(android.app.job.JobScheduler::class.java).getPendingJob(8000 + fixtureWidgetId))
        } finally { context.getSystemService(android.app.job.JobScheduler::class.java).cancel(8000 + fixtureWidgetId) }
    }
    private fun screenshot(name: String) {
        compose.waitForIdle()
        android.os.SystemClock.sleep(450) // Let the Android dialog window animation finish outside Compose's test clock.
        val bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
        val file = compose.activity.filesDir.resolve("qa-$name.png")
        file.outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
    }
}
