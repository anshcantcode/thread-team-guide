package com.thread.app

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.work.*
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object WatchRuntime {
    val actions = setOf("create_watch", "list_watches", "stop_watch", "check_watch_now")
    const val CHANNEL = "watch-updates"
    private val checking = mutableSetOf<String>()
    private val http = OkHttpClient.Builder().connectTimeout(8, TimeUnit.SECONDS).readTimeout(12, TimeUnit.SECONDS)
        .callTimeout(15, TimeUnit.SECONDS).followRedirects(false).retryOnConnectionFailure(false).build()
    fun store(context: Context) = WatchStore(context.filesDir.resolve("watches.json")).apply { onChanged = { StoredStateWidgets.changed(context) } }
    fun notifications(context: Context): Boolean {
        val manager = context.getSystemService(NotificationManager::class.java)
        return manager.areNotificationsEnabled() && manager.getNotificationChannel(CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE &&
            (android.os.Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
    }
    private fun tag(id: String) = "thread-watch-$id"
    fun restore(context: Context) = synchronized(WatchStore.lock) {
        // Repair a process death between saving a Watch and registering its work.
        store(context).list().forEach { row ->
            if (row.getBoolean("active")) schedule(context, row)
            else WorkManager.getInstance(context).cancelAllWorkByTag(tag(row.getString("id")))
        }
    }
    fun schedule(context: Context, row: JSONObject) {
        val work = PeriodicWorkRequestBuilder<WatchWorker>(row.getLong("every_minutes"), TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInputData(workDataOf("watch_id" to row.getString("id")))
            .addTag(tag(row.getString("id"))).build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(tag(row.getString("id")), ExistingPeriodicWorkPolicy.UPDATE, work)
            .result.get(5, TimeUnit.SECONDS)
    }
    fun checkNow(context: Context, id: String) {
        val row = store(context).get(JSONObject().put("id", id))
        require(row.getBoolean("active")) { "That Watch is stopped. Create it again to resume." }
        val work = OneTimeWorkRequestBuilder<WatchWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInputData(workDataOf("watch_id" to id)).addTag(tag(id)).build()
        WorkManager.getInstance(context).enqueueUniqueWork("${tag(id)}-now", ExistingWorkPolicy.KEEP, work).result.get(5, TimeUnit.SECONDS)
    }
    /** Called on an IO worker through the existing device_action/device_result socket path. */
    fun execute(context: Context, request: JSONObject): JSONObject {
        val action = request.getString("action"); val args = request.getJSONObject("arguments")
        val prefs = context.getSharedPreferences("phone-actions", 0)
        val id = request.getString("request_id")
        require(id.startsWith("phone-") && id.length <= 180)
        prefs.getString(id, null)?.let { return JSONObject(it) }
        val result = try {
            val store = store(context)
            when (action) {
                "create_watch" -> {
                    val row = store.create(args)
                    try { schedule(context, row) }
                    catch (_: Exception) {
                        store.stop(JSONObject().put("id", row.getString("id")))
                        return PhoneActions.outcome("failed", "Watch saved but scheduling failed; it is stopped. Try creating it again.")
                    }
                    val enabled = notifications(context)
                    val minutes = row.getInt("every_minutes")
                    val cadence = if (minutes % 60 == 0) "${minutes / 60} hours" else "$minutes minutes"
                    PhoneActions.outcome("completed", "I'll check ${row.getString("topic")} every $cadence and notify you only about new reports after a silent baseline. Say 'stop watching' to end it." +
                        if (enabled) "" else " Alerts are off; allow notifications to receive them. Updates still appear in Watches.")
                        .put("watch", WatchStore.summary(row)).put("notifications_enabled", enabled)
                }
                "list_watches" -> PhoneActions.outcome("completed", "Saved Watches on this phone.").put("watches", JSONArray(store.list().map(WatchStore::summary)))
                "stop_watch" -> {
                    val row = store.stop(args)
                    WorkManager.getInstance(context).cancelAllWorkByTag(tag(row.getString("id"))).result.get(5, TimeUnit.SECONDS)
                    context.getSystemService(NotificationManager::class.java).cancel(tag(row.getString("id")), 1)
                    PhoneActions.outcome("completed", "Stopped watching ${row.getString("topic")}. History is kept.").put("watch", WatchStore.summary(row))
                }
                "check_watch_now" -> {
                    val row = store.get(args); checkNow(context, row.getString("id"))
                    PhoneActions.outcome("prepared", "Check queued for ${row.getString("topic")}. It will run when Android permits and the network is available; see Watches for the result.").put("watch_id", row.getString("id"))
                }
                else -> PhoneActions.outcome("failed", "Unknown Watch action.")
            }
        } catch (error: IllegalArgumentException) { PhoneActions.outcome("failed", error.message ?: "Invalid Watch request.") }
        catch (_: Exception) { PhoneActions.outcome("failed", "Watch storage or scheduling is unavailable. Existing data was not cleared.") }
        // List/check are observations, not cached forever. Mutating commands are idempotent by request id.
        if (action in setOf("create_watch", "stop_watch")) prefs.edit().putString(id, result.toString()).commit()
        return result
    }
    fun fetch(topic: String): List<JSONObject> {
        http.newCall(Request.Builder().url(NewsRss.url(topic)).header("User-Agent", "THREAD-Watches/1.0").build()).execute().use { response ->
            check(response.isSuccessful)
            val stream = response.body?.byteStream() ?: error("Empty news response")
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                require(output.size() + count <= NewsRss.MAX_BYTES)
                output.write(buffer, 0, count)
            }
            return NewsRss.parse(output.toByteArray())
        }
    }
    fun check(context: Context, id: String) {
        synchronized(checking) { if (!checking.add(id)) return }
        try {
            val store = store(context); val args = JSONObject().put("id", id); val row = store.get(args)
            if (!row.getBoolean("active")) {
                WorkManager.getInstance(context).cancelAllWorkByTag(tag(id)); return
            }
            var error = ""
            val items = try { fetch(row.getString("topic")) } catch (_: Exception) {
                error = "News could not be fetched. Previous headlines are kept; the next scheduled check will try again."
                emptyList()
            }
            val receipt = store.record(id, row.getString("generation"), items, error)
            val fresh = WatchStore.rows(receipt.getJSONArray("new_items"))
            synchronized(WatchStore.lock) {
                val current = store.get(args)
                if (!current.getBoolean("active")) WorkManager.getInstance(context).cancelAllWorkByTag(tag(id))
                if (fresh.isNotEmpty() && current.getBoolean("active") && current.getString("generation") == row.getString("generation")) notify(context, row, fresh)
            }
        } finally { synchronized(checking) { checking.remove(id) } }
    }
    private fun notify(context: Context, row: JSONObject, items: List<JSONObject>) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Watch updates", NotificationManager.IMPORTANCE_DEFAULT))
        if (!notifications(context)) return
        val id = row.getString("id")
        val open = PendingIntent.getActivity(context, id.hashCode(), Intent(context, MainActivity::class.java).putExtra("watch_id", id),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val style = Notification.InboxStyle()
        items.take(5).forEach { style.addLine("${it.getString("title")} · ${it.getString("source")}") }
        val notification = Notification.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_thread)
            .setContentTitle("${items.size} new updates · ${row.getString("topic")}")
            .setContentText(items.first().getString("title")).setStyle(style).setContentIntent(open).setAutoCancel(true).build()
        try { manager.notify(tag(id), 1, notification) } catch (_: SecurityException) { /* Saved history remains useful without permission. */ }
    }
}

class WatchWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
    override fun doWork(): Result {
        return try {
            val id = inputData.getString("watch_id") ?: return Result.failure()
            WatchRuntime.check(applicationContext, id)
            Result.success() // Failed fetches are recorded; retry at the cadence, never a tight loop.
        } catch (_: Exception) { Result.failure() }
    }
}
