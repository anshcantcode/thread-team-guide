package com.thread.app

import android.app.PendingIntent
import android.app.job.*
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.PersistableBundle
import android.view.View
import android.widget.RemoteViews
import okhttp3.*
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

open class ThreadWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) { ids.forEach { seed(context, it); render(context, it); refresh(context, it) } }
    override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, options: android.os.Bundle) { render(context, id) }
    override fun onDeleted(context: Context, ids: IntArray) { val edit = context.getSharedPreferences("widgets", 0).edit(); ids.forEach { edit.remove("widget-$it"); context.getSystemService(JobScheduler::class.java).cancel(8000 + it) }; edit.apply() }
    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        val id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, -1)
        if (intent.action == "com.thread.app.WIDGET_PINNED" && id >= 0) {
            val prefs = context.getSharedPreferences("widgets", 0)
            val draft = prefs.getString("draft-${intent.getStringExtra("draft")}", null) ?: return
            prefs.edit().remove("draft-${intent.getStringExtra("draft")}").apply()
            save(context, id, JSONObject(draft))
        }
        if (intent.action == "com.thread.app.WIDGET_ITEM" && id >= 0) {
            val prefs = context.getSharedPreferences("widgets", 0)
            val config = prefs.getString("widget-$id", null)?.let(::JSONObject) ?: return
            val key = intent.getStringExtra("toggle_key").orEmpty()
            if (key.isNotEmpty()) {
                if (key !in WidgetContent.checkKeys(config)) return
                val checked = config.optJSONObject("checked") ?: JSONObject()
                checked.put(key, !checked.optBoolean(key)); config.put("checked", checked)
                prefs.edit().putString("widget-$id", config.toString()).apply(); render(context, id)
                if (context.getSharedPreferences("thread", 0).getBoolean("haptics", true)) context.getSystemService(android.os.VibratorManager::class.java).defaultVibrator.vibrate(android.os.VibrationEffect.createPredefined(android.os.VibrationEffect.EFFECT_TICK))
            } else context.startActivity(Intent(context, MainActivity::class.java).putExtra("widget_id", id).putExtra("result_index", intent.getIntExtra("result_index", 0)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        if (intent.action == "com.thread.app.WIDGET_REFRESH" && id >= 0) refresh(context, id)
    }

    companion object {
        fun provider(config: JSONObject): Class<out ThreadWidget> {
            val results=ThreadModel.rows(config.optJSONArray("results"))
            return if(results.size==1 && results[0].optString("domain")=="world_clocks" && (results[0].optJSONArray("items")?.length() ?: 0)<=2) ClockWidget::class.java else ThreadWidget::class.java
        }
        fun owns(context: Context, id: Int) = AppWidgetManager.getInstance(context).getAppWidgetInfo(id)?.provider?.className in setOf(ThreadWidget::class.java.name, ClockWidget::class.java.name)
        fun preview(context: Context, config: JSONObject): android.appwidget.AppWidgetHostView {
            val info = AppWidgetManager.getInstance(context).installedProviders.first { it.provider.className == provider(config).name }
            return android.appwidget.AppWidgetHostView(context).apply {
                setAppWidget(-1, info); setPadding(0, 0, 0, 0); updateAppWidget(views(context, -1, config))
            }
        }
        fun seed(context: Context, id: Int) {
            val prefs = context.getSharedPreferences("widgets", 0)
            if (prefs.contains("widget-$id")) return
            val saved = try { JSONObject(context.filesDir.resolve("workspace.json").readText()) } catch (_: Exception) { JSONObject() }
            val latest = ThreadModel.rows(saved.optJSONArray("workspace")).lastOrNull(::canMakeWidget)
            if (latest != null) prefs.edit().putString("widget-$id", JSONObject().put("title", "Your day").put("results", JSONArray().put(latest)).toString()).apply()
        }
        fun save(context: Context, id: Int, config: JSONObject) {
            require(owns(context, id))
            require(ThreadModel.rows(config.optJSONArray("results")).let { it.size in 1..2 && it.all(::canMakeWidget) })
            val prefs=context.getSharedPreferences("widgets",0)
            val previous=prefs.getString("widget-$id",null)?.let(::JSONObject)?.optJSONObject("checked")
            val checked=config.optJSONObject("checked") ?: previous ?: JSONObject()
            val keep=JSONObject();WidgetContent.checkKeys(config).forEach { if(checked.optBoolean(it)) keep.put(it,true) };config.put("checked",keep)
            prefs.edit().putString("widget-$id", config.toString()).apply()
            context.getSystemService(JobScheduler::class.java).cancel(8000 + id)
            render(context, id); refresh(context, id)
            java.util.concurrent.CompletableFuture.runAsync { WidgetContent.cacheImages(context.applicationContext, config); if (context.getSharedPreferences("widgets", 0).contains("widget-$id")) render(context, id) }
        }
        fun pin(context: Context, config: JSONObject): Boolean {
            val manager = AppWidgetManager.getInstance(context)
            if (!manager.isRequestPinAppWidgetSupported) return false
            val draft = UUID.randomUUID().toString()
            context.getSharedPreferences("widgets", 0).edit().putString("draft-$draft", config.toString()).apply()
            val callback = PendingIntent.getBroadcast(context, draft.hashCode(), Intent(context, ThreadWidget::class.java)
                .setAction("com.thread.app.WIDGET_PINNED").putExtra("draft", draft), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
            val preview = android.os.Bundle().apply { putParcelable(AppWidgetManager.EXTRA_APPWIDGET_PREVIEW, views(context, -1, config)) }
            return manager.requestPinAppWidget(ComponentName(context, provider(config)), preview, callback)
        }
        fun render(context: Context, id: Int) {
            val config = context.getSharedPreferences("widgets", 0).getString("widget-$id", null)?.let { JSONObject(it) } ?: JSONObject()
            AppWidgetManager.getInstance(context).updateAppWidget(id, views(context, id, config))
        }
        fun views(context: Context, id: Int, config: JSONObject): RemoteViews {
            val view = RemoteViews(context.packageName, R.layout.widget_thread)
            view.setTextViewText(R.id.widget_title, config.optString("title", "Your day").take(60))
            val results = ThreadModel.rows(config.optJSONArray("results"))
            val rows = WidgetContent.rows(context, config)
            val collection = RemoteViews.RemoteCollectionItems.Builder().setHasStableIds(true).setViewTypeCount(5)
            rows.forEachIndexed { index, row -> collection.addItem(index.toLong(), row) }
            view.setRemoteAdapter(R.id.widget_list, collection.build())
            val retrieved = results.map { it.optString("retrieved_at") }.filter(String::isNotBlank).minOrNull()
            val date = try { DateTimeFormatter.ofPattern("d MMM · HH:mm").withZone(ZoneId.systemDefault()).format(Instant.parse(retrieved)) } catch (_: Exception) { "Saved snapshot" }
            val source = results.map { if (it.optString("provenance") == "draft") "Saved AI draft" else it.optString("source").substringBefore(" · ") }.distinct().joinToString(" · ")
            val localClocks = results.isNotEmpty() && results.all { it.optString("domain") == "world_clocks" }
            val stamp = when {
                localClocks -> "Live on your phone · works offline"
                results.isEmpty() -> "Tap to create your widget"
                config.optBoolean("refreshing") -> "Refreshing…"
                config.has("refresh_error") -> "Offline · $date"
                results.all { it.optString("provenance") in listOf("draft", "saved", "computed") } -> "Saved on your phone"
                else -> "Updated $date"
            }
            view.setTextViewText(R.id.widget_updated, listOf(source, stamp).filter(String::isNotBlank).joinToString("\n"))
            val open = PendingIntent.getActivity(context, id, Intent(context, MainActivity::class.java).putExtra("widget_id", id).setAction("widget-$id"), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            view.setOnClickPendingIntent(R.id.widget_root, open)
            val items = PendingIntent.getBroadcast(context, id, Intent(context, ThreadWidget::class.java).setAction("com.thread.app.WIDGET_ITEM").putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id), PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            view.setPendingIntentTemplate(R.id.widget_list, items)
            val edit = PendingIntent.getActivity(context, id, Intent(context, WidgetConfigurationActivity::class.java).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id).setAction("configure-$id"), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            view.setOnClickPendingIntent(R.id.widget_edit, edit)
            val refresh = PendingIntent.getBroadcast(context, id, Intent(context, ThreadWidget::class.java).setAction("com.thread.app.WIDGET_REFRESH").putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            view.setOnClickPendingIntent(R.id.widget_refresh, refresh)
            view.setViewVisibility(R.id.widget_refresh, if (localClocks || results.all { it.optString("provenance") in listOf("draft", "saved", "computed") }) View.GONE else View.VISIBLE)
            return view
        }
        fun refresh(context: Context, id: Int) {
            if (id < 0) return
            val extras = PersistableBundle().apply { putInt("widget", id) }
            context.getSystemService(JobScheduler::class.java).schedule(JobInfo.Builder(8000 + id, ComponentName(context, WidgetRefreshService::class.java))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setExtras(extras).build())
        }
    }
}

class ClockWidget : ThreadWidget()

class TalkWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        val open = PendingIntent.getActivity(context, 7000, Intent(context, MainActivity::class.java).putExtra("talk", true).setAction("talk"), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        ids.forEach { id -> manager.updateAppWidget(id, RemoteViews(context.packageName, R.layout.widget_talk).apply { setOnClickPendingIntent(R.id.talk_root, open) }) }
    }
}

class WidgetRefreshService : JobService() {
    private val calls = java.util.concurrent.ConcurrentHashMap<Int, Call>()
    override fun onStartJob(params: JobParameters): Boolean {
        val id = params.extras.getInt("widget", -1)
        val prefs = getSharedPreferences("widgets", 0)
        val config = prefs.getString("widget-$id", null)?.let { JSONObject(it) } ?: return false
        val original = ThreadModel.rows(config.optJSONArray("results"))
        val refreshable = original.filter { it.optString("domain") in setOf("weather", "sports", "web", "currency", "calculate", "convert", "dates", "clock", "research") }
        if (refreshable.isEmpty()) return false
        config.put("refreshing", true); prefs.edit().putString("widget-$id", config.toString()).apply(); ThreadWidget.render(this, id)
        val modules = JSONArray(refreshable.map { JSONObject().put("id", it.optString("id")).put("domain", it.optString("domain")).put("arguments", it.optJSONObject("arguments") ?: JSONObject()) })
        val endpoint = ThreadBackend.endpoint(this)
        val request = Request.Builder().url("$endpoint/api/widgets/refresh").post(JSONObject().put("modules", modules).toString().toRequestBody(ThreadModel.JSON)).build()
        val call = ThreadBackend.client(this, CLIENT.newBuilder()).newCall(request); calls[params.jobId] = call
        call.enqueue(object : Callback {
            private fun finish(error: Boolean, fresh: List<JSONObject> = emptyList()) {
                if (calls[params.jobId] !== call || !prefs.contains("widget-$id")) return
                val latest = prefs.getString("widget-$id", null)?.let(::JSONObject)
                if (latest?.optJSONArray("results")?.toString() != config.optJSONArray("results")?.toString()) { calls.remove(params.jobId); jobFinished(params, false); return }
                latest?.optJSONObject("checked")?.let { config.put("checked", it) }; config.remove("refreshing")
                if (error) config.put("refresh_error", true) else {
                    config.remove("refresh_error")
                    val byId = fresh.associateBy { it.optString("id") }
                    config.put("results", JSONArray(original.map { byId[it.optString("id")] ?: it }))
                }
                prefs.edit().putString("widget-$id", config.toString()).apply(); ThreadWidget.render(this@WidgetRefreshService, id)
                calls.remove(params.jobId); jobFinished(params, false)
            }
            override fun onFailure(call: Call, e: IOException) = finish(true)
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    try { check(it.isSuccessful); val fresh = ThreadModel.rows(JSONObject(it.body!!.string()).optJSONArray("results")); check(fresh.size == refreshable.size && fresh.all { r -> r.optString("status") == "completed" && (r.optJSONArray("items")?.length() ?: 0) > 0 }); WidgetContent.cacheImages(this@WidgetRefreshService, JSONObject().put("results", JSONArray(fresh))); finish(false, fresh) }
                    catch (_: Exception) { finish(true) }
                }
            }
        })
        return true
    }
    override fun onStopJob(params: JobParameters): Boolean {
        calls.remove(params.jobId)?.cancel()
        val id = params.extras.getInt("widget", -1); val prefs = getSharedPreferences("widgets", 0)
        prefs.getString("widget-$id", null)?.let { raw -> val config = JSONObject(raw); config.remove("refreshing"); prefs.edit().putString("widget-$id", config.toString()).apply(); ThreadWidget.render(this, id) }
        return false
    }
    companion object { private val CLIENT = OkHttpClient.Builder().callTimeout(40, java.util.concurrent.TimeUnit.SECONDS).build() }
}
