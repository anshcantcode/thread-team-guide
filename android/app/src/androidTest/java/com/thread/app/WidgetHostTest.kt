package com.thread.app

import android.appwidget.AppWidgetHost
import android.appwidget.AppWidgetHostView
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.widget.FrameLayout
import android.widget.ListView
import android.widget.TextClock
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/** Real Android widget binding, collection rendering and PendingIntents on the attached phone.
 * Fixtures are recorded Gemini tool results, never submitted as fresh live lookups by this suite.
 */
@RunWith(AndroidJUnit4::class)
class WidgetHostTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private fun fixture(name: String) = JSONObject(instrumentation.context.assets.open("widget-$name.json").bufferedReader().readText())
    private fun await(timeout: Long = 10000, ready: () -> Boolean) {
        val until = android.os.SystemClock.elapsedRealtime() + timeout
        while (!ready()) { if (android.os.SystemClock.elapsedRealtime() > until) fail("Widget host step timed out"); android.os.SystemClock.sleep(80) }
    }
    private fun withHost(config: JSONObject, work: (MainActivity, Int, AppWidgetHostView) -> Unit) {
        val activity = instrumentation.startActivitySync(Intent(instrumentation.targetContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val host = AppWidgetHost(activity, 61740)
        var id = -1
        try {
            instrumentation.uiAutomation.adoptShellPermissionIdentity("android.permission.BIND_APPWIDGET")
            val manager = AppWidgetManager.getInstance(activity)
            id = host.allocateAppWidgetId()
            val options = Bundle().apply { putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 360); putInt(AppWidgetManager.OPTION_APPWIDGET_MAX_WIDTH, 360); putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 360); putInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 360) }
            assertTrue("Own widget should bind in scoped test host", manager.bindAppWidgetIdIfAllowed(id, ComponentName(activity, ThreadWidget::class.java), options))
            instrumentation.uiAutomation.dropShellPermissionIdentity()
            var view: AppWidgetHostView? = null
            instrumentation.runOnMainSync {
                activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                host.startListening()
                view = host.createView(activity, id, manager.getAppWidgetInfo(id))
                val root = FrameLayout(activity).apply { setBackgroundColor(0xff080d14.toInt()); val inset=(18*resources.displayMetrics.density).toInt(); setPadding(inset, inset*3, inset, inset) }
                root.addView(view, FrameLayout.LayoutParams(-1, (390*activity.resources.displayMetrics.density).toInt()))
                activity.setContentView(root)
                // Prevent this deterministic rendering test from scheduling any live network refresh.
                activity.getSharedPreferences("widgets", 0).edit().putString("widget-$id", config.toString()).apply()
                ThreadWidget.render(activity, id)
            }
            await { view?.findViewById<ListView>(R.id.widget_list)?.let { it.adapter?.count == WidgetContent.rows(activity, config).size && it.childCount > 0 } == true }
            work(activity, id, view!!)
        } finally {
            instrumentation.uiAutomation.dropShellPermissionIdentity()
            if (id >= 0) { activity.getSystemService(android.app.job.JobScheduler::class.java).cancel(8000+id); activity.getSharedPreferences("widgets", 0).edit().remove("widget-$id").apply(); host.deleteAppWidgetId(id) }
            host.stopListening()
            instrumentation.runOnMainSync { activity.model.disconnect(false); activity.finishAndRemoveTask() }
            await { activity.isDestroyed }
        }
    }
    @Test fun nativeWorldClocksUseBothZonesAndCurrentDeviceTime() = withHost(fixture("world-clocks")) { activity, _, host ->
        instrumentation.runOnMainSync {
            val list = host.findViewById<ListView>(R.id.widget_list)
            assertEquals(1, list.adapter.count)
            val row = list.adapter.getView(0, null, list)
            assertEquals("Manchester", row.findViewById<TextView>(R.id.clock_one_label).text.toString())
            val first = row.findViewById<TextClock>(R.id.clock_one_time); val second = row.findViewById<TextClock>(R.id.clock_two_time)
            assertEquals("Europe/London", first.timeZone); assertEquals("Europe/Madrid", second.timeZone)
            assertEquals(ZonedDateTime.now(ZoneId.of("Europe/London")).format(DateTimeFormatter.ofPattern("HH:mm")), first.text.toString())
            assertEquals(ZonedDateTime.now(ZoneId.of("Europe/Madrid")).format(DateTimeFormatter.ofPattern("HH:mm")), second.text.toString())
            assertTrue(host.findViewById<TextView>(R.id.widget_updated).text.contains("works offline"))
        }
        screenshot(activity, "clocks-host")
    }
    @Test fun sportsContainsAllFiveMatchesAndScrollsToLastOne() {
        val config = fixture("barcelona-matches")
        withHost(config) { activity, _, host ->
            val matches = config.getJSONArray("results").getJSONObject(0).getJSONArray("items").getJSONObject(0).getJSONArray("matches")
            instrumentation.runOnMainSync {
                val list=host.findViewById<ListView>(R.id.widget_list)
                assertEquals(6, list.adapter.count) // One profile heading, five complete matches.
                for (i in 0 until 5) {
                    val row=list.adapter.getView(i+1,null,list)
                    val match=matches.getJSONObject(i)
                    assertEquals("${match.getInt("home_score")} – ${match.getInt("away_score")}",row.findViewById<TextView>(R.id.row_value).text.toString())
                    assertTrue(row.findViewById<TextView>(R.id.row_detail).text.isNotBlank())
                }
            }
            // Swipe the currently attached collection, even if a background refresh re-inflates it.
            repeat(3) {
                val bounds=android.graphics.Rect()
                instrumentation.runOnMainSync { host.findViewById<ListView>(R.id.widget_list).getGlobalVisibleRect(bounds) }
                val down=android.os.SystemClock.uptimeMillis();val x=bounds.exactCenterX()
                for(step in 0..12) {
                    val action=if(step==0) android.view.MotionEvent.ACTION_DOWN else if(step==12) android.view.MotionEvent.ACTION_UP else android.view.MotionEvent.ACTION_MOVE
                    val event=android.view.MotionEvent.obtain(down,down+step*25L,action,x,bounds.bottom-35f-(bounds.height()-70)*step/12f,0)
                    instrumentation.sendPointerSync(event);event.recycle();android.os.SystemClock.sleep(25)
                }
                instrumentation.waitForIdleSync()
            }
            await { host.findViewById<ListView>(R.id.widget_list).lastVisiblePosition >= 5 }
            screenshot(activity, "matches-host")
        }
    }
    @Test fun checklistTapPersistsAndRejectsAnUnknownItem() {
        val config=fixture("packing-checklist")
        withHost(config) { activity,id,host ->
            val key=WidgetContent.checkKeys(config).first()
            val prefs=activity.getSharedPreferences("widgets",0)
            val rows=WidgetContent.rows(activity, config)
            val list=host.findViewById<ListView>(R.id.widget_list)
            var position=-1
            instrumentation.runOnMainSync {
                for (i in rows.indices) {
                    val row=list.adapter.getView(i,null,list)
                    if (row.findViewById<TextView?>(R.id.row_check)?.visibility == android.view.View.VISIBLE) { position=i; break }
                }
                assertTrue(position >= 0)
                list.setSelection(position)
            }
            await { position in list.firstVisiblePosition..list.lastVisiblePosition }
            instrumentation.runOnMainSync {
                val row=list.getChildAt(position-list.firstVisiblePosition)
                assertTrue("Collection should deliver checklist tap", list.performItemClick(row,position,list.adapter.getItemId(position)))
            }
            // Collection click invokes the provider through Android's actual PendingIntent template.
            await { JSONObject(prefs.getString("widget-$id","{}")!!).optJSONObject("checked")?.optBoolean(key) == true }
            instrumentation.runOnMainSync {
                ThreadWidget().onReceive(activity,Intent(activity,ThreadWidget::class.java).setAction("com.thread.app.WIDGET_ITEM").putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,id).putExtra("toggle_key","unknown"))
                ThreadWidget.render(activity,id)
            }
            val saved=JSONObject(prefs.getString("widget-$id","{}")!!)
            assertTrue(saved.getJSONObject("checked").getBoolean(key));assertFalse(saved.getJSONObject("checked").has("unknown"))
            screenshot(activity, "checklist-host")
        }
    }
    @Test fun nativeCollectionTapOpensFullSportsDetail() = withHost(fixture("barcelona-matches")) { activity, _, host ->
        instrumentation.runOnMainSync {
            val list=host.findViewById<ListView>(R.id.widget_list)
            assertTrue("Collection should deliver match tap", list.performItemClick(list.getChildAt(1-list.firstVisiblePosition),1,list.adapter.getItemId(1)))
        }
        await { activity.model.openResult?.optString("domain") == "sports" || activity.model.route == "detail" }
    }
    @Test fun reconfigureReplacesContentsOnTheSameWidgetId() = withHost(fixture("world-clocks")) { activity,id,host ->
        instrumentation.runOnMainSync { ThreadWidget.save(activity,id,fixture("packing-checklist")) }
        await { host.findViewById<ListView>(R.id.widget_list).adapter.count > 1 }
        val saved=JSONObject(activity.getSharedPreferences("widgets",0).getString("widget-$id","{}")!!)
        assertEquals("document",saved.getJSONArray("results").getJSONObject(0).getString("domain"))
        assertNotNull(AppWidgetManager.getInstance(activity).getAppWidgetInfo(id))
    }
    @Test fun failedRefreshKeepsEveryPreviouslySavedMatch() = withHost(fixture("barcelona-matches")) { activity,id,_ ->
        val prefs=activity.getSharedPreferences("widgets",0)
        val original=JSONObject(prefs.getString("widget-$id","{}")!!).getJSONArray("results").toString()
        val settings=activity.getSharedPreferences("thread",0);val endpoint=settings.getString("endpoint",null)
        val backendMode=settings.getString("backend-mode",null)
        val socket=java.net.ServerSocket(0)
        val seen=java.util.concurrent.atomic.AtomicBoolean(false)
        val reply=Thread {
            try { while(!socket.isClosed) socket.accept().use { client ->
                client.soTimeout=4000
                val reader=client.getInputStream().bufferedReader()
                while (true) { val line=reader.readLine() ?: break; if (line.isEmpty()) break }
                client.getOutputStream().write("HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray());client.getOutputStream().flush();seen.set(true)
            } } catch (_: Exception) { }
        }
        try {
            settings.edit().putString("backend-mode","laptop").putString("endpoint","http://127.0.0.1:${socket.localPort}").apply();reply.start()
            instrumentation.runOnMainSync { ThreadWidget.refresh(activity,id) }
            await(20000) { val state=JSONObject(prefs.getString("widget-$id","{}")!!);seen.get() && state.has("refresh_error") && !state.optBoolean("refreshing") }
            val saved=JSONObject(prefs.getString("widget-$id","{}")!!)
            assertEquals(original,saved.getJSONArray("results").toString());assertFalse(saved.optBoolean("refreshing"))
        } finally { settings.edit().putString("backend-mode",backendMode).putString("endpoint",endpoint).apply();socket.close();reply.join(1000) }
    }
    @Test fun launcherConfigurationActivityLoadsTheBoundWidget() = withHost(fixture("world-clocks")) { activity,id,_ ->
        val intent=Intent(activity,WidgetConfigurationActivity::class.java).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,id).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val configuration=instrumentation.startActivitySync(intent) as WidgetConfigurationActivity
        try {
            await { configuration.lifecycle.currentState == androidx.lifecycle.Lifecycle.State.RESUMED }
            assertEquals(id,configuration.intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,-1))
        } finally { instrumentation.runOnMainSync { configuration.finish() };await { configuration.isDestroyed } }
    }
    private fun screenshot(activity: MainActivity, name: String) {
        instrumentation.waitForIdleSync(); android.os.SystemClock.sleep(200)
        instrumentation.uiAutomation.takeScreenshot().let { image -> activity.filesDir.resolve("qa-widget-$name.png").outputStream().use { image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) } }
    }
}
