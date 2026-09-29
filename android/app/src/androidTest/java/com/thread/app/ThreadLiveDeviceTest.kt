package com.thread.app

import android.app.Instrumentation
import android.content.Intent
import android.provider.AlarmClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import okhttp3.Request
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in network/device smoke check. Run separately from the deterministic UI suite. */
@RunWith(AndroidJUnit4::class)
class ThreadLiveDeviceTest {
    @Test fun realSportsRequestOpensProfileKeepsVoiceAndPreviewsWidget() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val model=activity.model
        fun find(label:String):android.view.accessibility.AccessibilityNodeInfo? {
            fun walk(node:android.view.accessibility.AccessibilityNodeInfo?):android.view.accessibility.AccessibilityNodeInfo? {
                if(node==null)return null
                if(node.text?.toString()==label || node.contentDescription?.toString()==label)return node
                for(i in 0 until node.childCount)walk(node.getChild(i))?.let{return it}
                return null
            }
            return walk(instrumentation.uiAutomation.rootInActiveWindow)
        }
        fun click(label:String) {
            await(10000){find(label)!=null};var node=find(label)!!
            while(!node.isClickable && node.parent!=null)node=node.parent
            assertTrue(node.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK))
        }
        val report=JSONObject().put("passed",false).put("device",android.os.Build.MODEL)
        try {
            instrumentation.runOnMainSync { activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);model.newConversation();model.connect(false,"Show Lando Norris's last five Formula 1 races with his stats.") }
            await(100000) { (find("Lando Norris")!=null && find("Finish")!=null) || model.ui.error!=null }
            assertNull(model.ui.error);assertTrue(model.ui.connected)
            assertNotNull(find("End conversation"));assertNotNull(find("Unmute"))
            android.os.SystemClock.sleep(1800)
            instrumentation.uiAutomation.takeScreenshot().let { image->activity.filesDir.resolve("qa-sports-live-profile.png").outputStream().use { image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) } }
            click("Back");await(10000){find("View result")!=null}
            assertTrue(model.ui.connected)
            click("View result");await(10000){find("Finish")!=null}
            click("Make a widget");await(10000){model.widget!=null && find("Add to home screen")!=null}
            val result=model.widget!!.getJSONArray("results").getJSONObject(0)
            assertEquals(5,result.getJSONArray("items").getJSONObject(0).getJSONArray("records").length())
            report.put("passed",true).put("session_id",model.sessionId).put("result",result)
                .put("scope","Actual typed request through Android/Gemini, automatic sports profile navigation, active voice dock, back/reopen result, and native widget preview containing five source records. Microphone stays off. No additional home-screen widget is pinned.")
        } catch(error:Throwable) { report.put("error",error.stackTraceToString());throw error }
        finally {
            activity.filesDir.resolve("qa-sports-live-device.json").writeText(report.toString(2))
            instrumentation.runOnMainSync{model.widget=null;model.disconnect(false);activity.finishAndRemoveTask()}
            await(10000){activity.isDestroyed}
        }
    }
    @Test fun realNativeAudioToolsAndClockHandoff() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val activity = instrumentation.startActivitySync(Intent(instrumentation.targetContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val model = activity.model
        val priorIds = model.ui.results.map { it.optString("id") }.toSet()
        instrumentation.runOnMainSync {
            activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            model.newConversation()
            model.connect(false, "Calculate 12 times 13. Show the result and say it briefly.")
        }
        try {
            await(60000) { model.ui.results.any { it.optString("id") !in priorIds && it.optString("domain") == "calculate" && it.optJSONArray("items")?.optJSONObject(0)?.optInt("value") == 156 } }
            assertTrue(model.ui.connected)
            // Actual Android AudioTrack output is recorded by the server's playback events.
            val sid = model.sessionId!!
            var export = JSONObject()
            await(30000) {
                export = model.http.newCall(Request.Builder().url("${model.endpoint}/api/sessions/$sid/export").build()).execute().use { JSONObject(it.body!!.string()) }
                export.toString().contains("live_playback") && export.toString().contains("played")
            }
            instrumentation.runOnMainSync { model.sendText("Open my phone’s alarm list.") }
            await(45000) { model.ui.results.any { it.optString("id") !in priorIds && it.optString("domain") == "phone" && it.optString("status") == "handed_off" } }
            val clockPackage = Intent(AlarmClock.ACTION_SHOW_ALARMS).resolveActivity(activity.packageManager)!!.packageName
            await(10000) { instrumentation.uiAutomation.rootInActiveWindow?.packageName?.toString() == clockPackage }
            // Opening Clock is real, read-only navigation. We do not create a test alarm on the user's phone.
            instrumentation.runOnMainSync { activity.startActivity(Intent(activity, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            await(10000) { activity.lifecycle.currentState == androidx.lifecycle.Lifecycle.State.RESUMED }
            val report = JSONObject().put("passed", true).put("session_id", sid).put("device", android.os.Build.MODEL)
                .put("clock_package_observed", clockPackage)
                .put("scope", "New typed input through native Android client, actual Gemini audio played by AudioTrack, local calculator, and Clock alarm-list handoff verified by the foreground window package. No microphone recording or alarm creation.")
                .put("state", JSONObject(model.http.newCall(Request.Builder().url("${model.endpoint}/api/sessions/$sid").build()).execute().use { it.body!!.string() }))
            activity.filesDir.resolve("qa-live-device.json").writeText(report.toString(2))
        } catch (error: Throwable) {
            activity.filesDir.resolve("qa-live-device-failure.txt").writeText(error.stackTraceToString() + "\n" + model.ui.toString())
            throw error
        } finally {
            instrumentation.runOnMainSync { model.disconnect(false); activity.finishAndRemoveTask() }
            await(10000) { activity.isDestroyed }
        }
    }
    private fun await(timeout: Long, ready: () -> Boolean) {
        val until = android.os.SystemClock.elapsedRealtime() + timeout
        while (!ready()) {
            if (android.os.SystemClock.elapsedRealtime() >= until) fail("Live device step exceeded ${timeout}ms; inspect the session and device state.")
            android.os.SystemClock.sleep(100)
        }
    }
}
