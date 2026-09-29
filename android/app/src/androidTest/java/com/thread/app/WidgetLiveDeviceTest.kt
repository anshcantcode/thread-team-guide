package com.thread.app

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in acceptance run: creates the user's two requested widgets on the actual Samsung home screen. */
@RunWith(AndroidJUnit4::class)
class WidgetLiveDeviceTest {
    private val instrumentation=InstrumentationRegistry.getInstrumentation()
    private fun await(timeout: Long=15000, ready: ()->Boolean) {
        val until=android.os.SystemClock.elapsedRealtime()+timeout
        while(!ready()) { if(android.os.SystemClock.elapsedRealtime()>=until) fail("Native widget acceptance step timed out");android.os.SystemClock.sleep(100) }
    }
    private fun find(text: String): AccessibilityNodeInfo? {
        fun walk(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
            if(node==null)return null
            if(node.text?.toString()?.equals(text,true)==true || node.contentDescription?.toString()?.equals(text,true)==true) return node
            for(i in 0 until node.childCount) walk(node.getChild(i))?.let { return it }
            return null
        }
        return walk(instrumentation.uiAutomation.rootInActiveWindow)
    }
    private fun click(label:String) {
        await { find(label)!=null }
        var node=find(label)!!
        while(!node.isClickable && node.parent!=null) node=node.parent
        assertTrue("$label must accept a click",node.performAction(AccessibilityNodeInfo.ACTION_CLICK))
    }
    @Test fun actualGeminiRequestsPreviewAndPinClocksAndFiveMatches() {
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val model=activity.model
        val manager=AppWidgetManager.getInstance(activity)
        fun ids() = listOf(ThreadWidget::class.java,ClockWidget::class.java).flatMap { manager.getAppWidgetIds(ComponentName(activity,it)).toList() }
        val report=JSONObject().put("passed",false).put("device",android.os.Build.MODEL).put("input","Typed exact requests through native Android client and actual Gemini Live; native previews and Samsung launcher pin actions")
        val cases=JSONArray();report.put("cases",cases)
        try {
            instrumentation.runOnMainSync { activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);model.newConversation() }
            for((name,prompt,domain) in listOf(
                Triple("world-clocks","Make a widget that shows the time in Manchester and Barca.","world_clocks"),
                Triple("barcelona-matches","Make a widget that shows Barca's last 5 games.","sports")
            )) {
                instrumentation.runOnMainSync { model.widget=null;model.sendText(prompt) }
                await(100000) { model.widget!=null || model.ui.error!=null }
                assertNull(model.ui.error)
                val config=model.widget!!
                val result=config.getJSONArray("results").getJSONObject(0)
                assertEquals(domain,result.getString("domain"))
                if(domain=="world_clocks")assertEquals(2,result.getJSONArray("items").length())
                else assertEquals(5,result.getJSONArray("items").getJSONObject(0).getJSONArray("matches").length())
                // Let the real native preview and cached club badges finish rendering.
                await { find("Add to home screen")!=null }
                android.os.SystemClock.sleep(1800)
                instrumentation.uiAutomation.takeScreenshot().let { image -> activity.filesDir.resolve("qa-widget-$name-preview.png").outputStream().use { image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) } }
                val before=ids().toSet()
                click("Add to home screen")
                // This is Samsung's own launcher confirmation, not a simulated widget acknowledgement.
                await { find("Add")!=null || ids().any { it !in before } }
                find("Add")?.let { click("Add") }
                var id=-1
                await { id=ids().firstOrNull { it !in before } ?: -1; id>=0 && activity.getSharedPreferences("widgets",0).contains("widget-$id") }
                val saved=JSONObject(activity.getSharedPreferences("widgets",0).getString("widget-$id","{}")!!)
                assertEquals(domain,saved.getJSONArray("results").getJSONObject(0).getString("domain"))
                cases.put(JSONObject().put("request",prompt).put("widget_id",id).put("saved",saved).put("passed",true))
                activity.filesDir.resolve("qa-widget-live-device.json").writeText(report.toString(2))
                instrumentation.runOnMainSync { model.widget=null;activity.startActivity(Intent(activity,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                await { activity.lifecycle.currentState==androidx.lifecycle.Lifecycle.State.RESUMED }
            }
            report.put("passed",true).put("session_id",model.sessionId)
        } catch(error:Throwable) { report.put("error",error.stackTraceToString());throw error }
        finally {
            activity.filesDir.resolve("qa-widget-live-device.json").writeText(report.toString(2))
            instrumentation.runOnMainSync { model.disconnect(false); model.widget=null;activity.finishAndRemoveTask() }
            await { activity.isDestroyed }
        }
    }
}
