package com.thread.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.RemoteViews
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

enum class StoredWidgetKind(val heading: String) { NOW("Now doing"), WATCHES("Watches"), KITCHEN("Kitchen checklist") }

open class StoredStateWidget(private val kind: StoredWidgetKind) : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        val pending = goAsync()
        StoredStateWidgets.run { try { ids.forEach { StoredStateWidgets.render(context, it, kind) } } finally { pending.finish() } }
    }
    override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, options: android.os.Bundle) = onUpdate(context, manager, intArrayOf(id))
}
class NowDoingWidget : StoredStateWidget(StoredWidgetKind.NOW)
class WatchesWidget : StoredStateWidget(StoredWidgetKind.WATCHES)
class KitchenProgressWidget : StoredStateWidget(StoredWidgetKind.KITCHEN)

/** The existing RemoteViews stack, with no network refresh or generated widget UI. */
object StoredStateWidgets {
    private val worker = Executors.newSingleThreadExecutor { runnable -> Thread(runnable, "THREAD stored widgets").apply { priority = Thread.MIN_PRIORITY } }
    private val main = Handler(Looper.getMainLooper())
    private var pending: Runnable? = null
    private val providers = mapOf(NowDoingWidget::class.java to StoredWidgetKind.NOW,
        WatchesWidget::class.java to StoredWidgetKind.WATCHES, KitchenProgressWidget::class.java to StoredWidgetKind.KITCHEN)
    fun run(block: () -> Unit) { worker.execute(block) }

    fun changed(context: Context) {
        val app = context.applicationContext
        main.post {
            pending?.let(main::removeCallbacks)
            pending = Runnable {
                pending = null
                run {
                    val manager = AppWidgetManager.getInstance(app)
                    providers.forEach { (provider, kind) ->
                        manager.getAppWidgetIds(ComponentName(app, provider)).forEach { render(app, it, kind) }
                    }
                }
            }.also { main.postDelayed(it, 400) }
        }
    }

    private fun open(context: Context, kind: StoredWidgetKind): Intent = when (kind) {
        StoredWidgetKind.NOW -> Intent(context, MainActivity::class.java).putExtra("show_task", true)
        StoredWidgetKind.WATCHES -> Intent(context, MainActivity::class.java).putExtra("watch_id", "")
        StoredWidgetKind.KITCHEN -> Intent(context, Fdb3Activity::class.java)
    }.setAction("com.thread.app.STORED_${kind.name}")

    fun render(context: Context, id: Int, kind: StoredWidgetKind) {
        val rows = when (kind) {
            StoredWidgetKind.NOW -> {
                val snapshot = runCatching { context.filesDir.resolve("workspace.json").let { if (it.exists()) JSONObject(it.readText()) else JSONObject() } }.getOrNull()
                val live = (context.applicationContext as? ThreadApplication)?.currentModel?.ui?.connected == true
                StoredWidgetText.now(snapshot, live)
            }
            StoredWidgetKind.WATCHES -> StoredWidgetText.watches(runCatching { WatchRuntime.store(context).list() }.getOrNull())
            StoredWidgetKind.KITCHEN -> {
                val items = runCatching {
                    val session = context.getSharedPreferences("fdb3-client", 0).getString("session", null)
                    if (session == null) JSONArray() else {
                        require(Regex("[a-f0-9]{32}").matches(session))
                        JSONArray(context.getSharedPreferences("fdb3-$session", 0).getString("items", "[]"))
                    }
                }.getOrNull()
                listOf(StoredWidgetText.kitchen(items))
            }
        }
        val views = RemoteViews(context.packageName, R.layout.widget_thread)
        views.setTextViewText(R.id.widget_title, kind.heading)
        views.setTextViewText(R.id.widget_updated, "Saved on this phone · tap to open")
        views.setViewVisibility(R.id.widget_edit, View.GONE)
        views.setViewVisibility(R.id.widget_refresh, View.GONE)
        val intent = open(context, kind).setData(Uri.parse("thread://stored-widget/${kind.name}/$id"))
        val open = PendingIntent.getActivity(context, id, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        views.setOnClickPendingIntent(R.id.widget_root, open)
        val template = PendingIntent.getActivity(context, id, Intent(intent).apply { removeExtra("watch_id") }.setAction("com.thread.app.STORED_ROW_${kind.name}"),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
        views.setPendingIntentTemplate(R.id.widget_list, template)
        val collection = RemoteViews.RemoteCollectionItems.Builder().setHasStableIds(false).setViewTypeCount(1)
        rows.forEachIndexed { index, row ->
            val content = RemoteViews(context.packageName, R.layout.widget_row)
            content.setTextViewText(R.id.row_title, row.title.take(200))
            content.setTextViewText(R.id.row_detail, row.detail.take(1400))
            content.setViewVisibility(R.id.row_detail, View.VISIBLE)
            content.setOnClickFillInIntent(R.id.row_root, Intent().apply { if (kind == StoredWidgetKind.WATCHES) putExtra("watch_id", row.target) })
            collection.addItem(index.toLong(), content)
        }
        views.setRemoteAdapter(R.id.widget_list, collection.build())
        // Launcher removal during an asynchronous refresh is harmless.
        runCatching { AppWidgetManager.getInstance(context).updateAppWidget(id, views) }
    }
}
