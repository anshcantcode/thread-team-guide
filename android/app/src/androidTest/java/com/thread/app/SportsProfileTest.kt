package com.thread.app

import android.os.SystemClock
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Recorded public-source responses exercise real native layouts; no fabricated live conversation. */
@RunWith(AndroidJUnit4::class)
class SportsProfileTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    @Before fun keepScreenAwake() { compose.runOnUiThread { compose.activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) } }

    private fun fixture(name: String) = JSONObject(instrumentation.context.assets.open("profile-$name.json").bufferedReader().use { it.readText() })
    private fun open(name: String): JSONObject {
        val result=fixture(name)
        compose.runOnUiThread { compose.activity.model.openResult=result }
        compose.onNodeWithText(result.getJSONArray("items").getJSONObject(0).getString("title")).assertIsDisplayed()
        compose.waitUntil(20000) { compose.onAllNodesWithTag("sports-portrait").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithContentDescription("Make a widget").assertIsDisplayed()
        return result
    }
    private fun screenshot(name: String) {
        compose.waitForIdle();SystemClock.sleep(350)
        val bitmap=instrumentation.uiAutomation.takeScreenshot()
        compose.activity.filesDir.resolve("qa-profile-$name.png").outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) }
    }
    private fun lastRecordAndSource(result: JSONObject, name: String) {
        val profile=result.getJSONArray("items").getJSONObject(0)
        val records=profile.getJSONArray("records")
        val last=records.getJSONObject(records.length()-1)
        compose.onNodeWithText("Open source profile").performScrollTo()
        compose.onAllNodesWithText(last.optString("opponent").ifBlank { last.getString("title") }).onLast().assertIsDisplayed()
        compose.onNodeWithText("Open source profile").assertIsDisplayed()
        screenshot("$name-records")
    }
    @Test fun basketballShowsPlayerIdentityAndOwnGameStatistics() {
        val result=open("aja-wilson")
        compose.onNodeWithText("Las Vegas Aces").assertIsDisplayed()
        compose.onNodeWithText("Center · #22").assertIsDisplayed()
        listOf("PTS","REB","AST").forEach { compose.onNodeWithText(it).assertIsDisplayed() }
        screenshot("aja-wilson");lastRecordAndSource(result,"aja-wilson")
    }
    @Test fun cricketShowsFormatControlsAndHonestPartialCoverage() {
        val result=open("virat-kohli")
        compose.onNodeWithText("ODI").assertIsSelected()
        listOf("T20","Test","All","Runs","Balls","SR").forEach { compose.onAllNodesWithText(it).onFirst().assertIsDisplayed() }
        screenshot("virat-kohli")
        compose.onNodeWithText("Open source profile").performScrollTo()
        val profile=result.getJSONArray("items").getJSONObject(0)
        compose.onNodeWithText("${profile.getJSONArray("records").length()} of ${profile.getInt("requested_count")} requested records available").assertIsDisplayed()
        screenshot("virat-kohli-records")
    }
    @Test fun cricketFormatChangeRefreshesDataAndPreservesItOnFailure() {
        open("virat-kohli")
        val model=compose.activity.model
        val endpoint=model.prefs.getString("endpoint",null)
        val backendMode=model.prefs.getString("backend-mode",null)
        val workspace=compose.activity.filesDir.resolve("workspace.json")
        val previous=workspace.takeIf { it.exists() }?.readBytes()
        val socket=java.net.ServerSocket(0)
        val fail=java.util.concurrent.atomic.AtomicBoolean(false)
        val requested=java.util.concurrent.atomic.AtomicReference<String>("")
        val response=fixture("virat-kohli-t20")
        val server=Thread {
            try { while(!socket.isClosed) socket.accept().use { client ->
                client.soTimeout=5000
                val reader=client.getInputStream().bufferedReader()
                var length=0
                while(true) { val line=reader.readLine() ?: break;if(line.isEmpty())break;if(line.startsWith("Content-Length:",true))length=line.substringAfter(':').trim().toInt() }
                val body=CharArray(length);var offset=0
                while(offset<length) { val read=reader.read(body,offset,length-offset);if(read<0)break;offset+=read }
                val module=JSONObject(String(body)).getJSONArray("modules").getJSONObject(0)
                requested.set(module.getJSONObject("arguments").optString("cricket_format"))
                val payload=JSONObject().put("results",org.json.JSONArray().put(JSONObject(response.toString()).put("id",module.getString("id")))).toString().toByteArray()
                val header=if(fail.get()) "HTTP/1.1 503 Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n" else "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${payload.size}\r\nConnection: close\r\n\r\n"
                client.getOutputStream().apply { write(header.toByteArray());if(!fail.get())write(payload);flush() }
            } } catch(_:Exception) { }
        }
        try {
            model.prefs.edit().putString("backend-mode","laptop").putString("endpoint","http://127.0.0.1:${socket.localPort}").apply();server.start()
            compose.onNodeWithText("T20").performClick()
            compose.waitUntil(10000) { !model.sportsLoading && model.ui.results.any { it.optJSONObject("arguments")?.optString("cricket_format")=="T20" } }
            compose.onNodeWithText("T20").assertIsSelected()
            assertEquals("T20",requested.get())
            compose.onNodeWithText("5 innings selected").assertIsDisplayed()
            screenshot("virat-kohli-t20")
            fail.set(true);compose.onNodeWithText("Test").performClick()
            compose.waitUntil(10000) { model.sportsError!=null }
            assertEquals("Test",requested.get())
            compose.onNodeWithText("T20").assertIsSelected()
            compose.onNodeWithText("5 innings selected").assertIsDisplayed()
            assertNull(model.ui.error)
            assertFalse(model.ui.connected);assertFalse(model.ui.connecting)
        } finally {
            model.prefs.edit().putString("backend-mode",backendMode).putString("endpoint",endpoint).apply();socket.close();server.join(1000)
            SystemClock.sleep(1000) // Let the normal debounced Library write finish before restoring user data.
            if(previous==null)workspace.delete() else workspace.writeBytes(previous)
        }
    }
    @Test fun tennisPreservesSetsAndSelectedMatchSummary() {
        val result=open("carlos-alcaraz")
        listOf("Wins","Losses","Matches","Sets").forEach { compose.onNodeWithText(it).assertIsDisplayed() }
        val first=result.getJSONArray("items").getJSONObject(0).getJSONArray("records").getJSONObject(0)
        compose.onAllNodesWithText(first.getString("score")).onFirst().assertIsDisplayed()
        screenshot("carlos-alcaraz");lastRecordAndSource(result,"carlos-alcaraz")
    }
    @Test fun formulaOneUsesRaceStatisticsAndOpensFullRows() {
        val result=open("lando-norris")
        listOf("Finish","Grid","Podiums").forEach { compose.onNodeWithText(it).assertIsDisplayed() }
        screenshot("lando-norris")
        val first=result.getJSONArray("items").getJSONObject(0).getJSONArray("records").getJSONObject(0)
        compose.onNodeWithText(first.getString("title")).performClick()
        compose.onNodeWithText("Laps").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(first.getString("title")).performClick()
        lastRecordAndSource(result,"lando-norris")
    }
}
