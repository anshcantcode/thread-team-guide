package com.thread.app

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.SystemClock
import android.view.View
import android.widget.RemoteViews
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

/** The same real RemoteViews render in preview and the launcher. No model-generated executable UI. */
object WidgetContent {
    private val imageClient = OkHttpClient.Builder().callTimeout(5, TimeUnit.SECONDS).followRedirects(false).build()
    private fun imageFile(context: Context, url: String) = context.cacheDir.resolve("widget-images").resolve(java.security.MessageDigest.getInstance("SHA-256").digest(url.toByteArray()).joinToString("") { "%02x".format(it) } + ".png")
    private fun allowedImage(url: String): Boolean = try { Uri.parse(url).let { it.scheme == "https" && it.host == "a.espncdn.com" && it.userInfo == null } } catch (_: Exception) { false }
    fun cacheImages(context: Context, config: JSONObject) {
        val urls = mutableSetOf<String>()
        fun walk(value: Any?) {
            when (value) {
                is JSONObject -> value.keys().forEach { k -> if (k in setOf("logo", "portrait", "home_logo", "away_logo")) value.optString(k).takeIf(::allowedImage)?.let(urls::add) else walk(value.opt(k)) }
                is org.json.JSONArray -> (0 until value.length()).forEach { walk(value.opt(it)) }
            }
        }
        walk(config.optJSONArray("results"))
        urls.take(14).forEach { url ->
            val file = imageFile(context, url)
            if (!file.exists()) try {
                imageClient.newCall(Request.Builder().url(url).build()).execute().use { response ->
                    if (!response.isSuccessful || (response.body?.contentLength() ?: 0) > 1_500_000) return@use
                    val input = response.body?.byteStream() ?: return@use
                    val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
                    while (output.size() <= 1_500_000) { val size=input.read(buffer); if(size<0) break; output.write(buffer,0,size) }
                    val bytes = output.toByteArray()
                    if (bytes.size > 1_500_000) return@use
                    val opts = BitmapFactory.Options().apply { inSampleSize = 2 }
                    val original = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts) ?: return@use
                    val scale = 128f / maxOf(original.width, original.height)
                    val bitmap = Bitmap.createScaledBitmap(original, maxOf(1, (original.width * scale).toInt()), maxOf(1, (original.height * scale).toInt()), true)
                    file.parentFile?.mkdirs(); file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                }
            } catch (_: Exception) { /* A missing badge never hides source records. */ }
        }
    }
    private fun badge(context: Context, view: RemoteViews, id: Int, url: String) {
        if (!allowedImage(url)) return
        val bitmap = BitmapFactory.decodeFile(imageFile(context, url).path) ?: return
        view.setViewVisibility(id, View.VISIBLE); view.setImageViewBitmap(id, bitmap)
    }
    fun checkKey(result: JSONObject, block: Int, item: Int, text: String) = "${result.optString("id")}:$block:$item:${text.hashCode()}"
    fun checkKeys(config: JSONObject): Set<String> = buildSet {
        ThreadModel.rows(config.optJSONArray("results")).forEach { result ->
            val doc = result.optJSONArray("items")?.optJSONObject(0)?.optJSONObject("document") ?: return@forEach
            if (doc.optString("kind") == "checklist") ThreadModel.rows(doc.optJSONArray("blocks")).forEachIndexed { bi, block ->
                val items = block.optJSONArray("items") ?: return@forEachIndexed
                for (i in 0 until items.length()) add(checkKey(result, bi, i, items.optString(i)))
            }
        }
    }
    private fun day(value: String): String = try { LocalDate.parse(value.take(10)).format(DateTimeFormatter.ofPattern("d MMM")) } catch (_: Exception) { value.take(18) }
    fun rows(context: Context, config: JSONObject): List<RemoteViews> = buildList {
        val results = ThreadModel.rows(config.optJSONArray("results"))
        fun row(index: Int, text: String, detail: String = "", value: String = "", image: String = "", key: String = "") {
            add(RemoteViews(context.packageName, R.layout.widget_row).apply {
                setTextViewText(R.id.row_title, text.take(1200)); setTextViewText(R.id.row_detail, detail.take(1800)); setTextViewText(R.id.row_value, value.take(80))
                setViewVisibility(R.id.row_detail, if (detail.isBlank()) View.GONE else View.VISIBLE)
                setViewVisibility(R.id.row_value, if (value.isBlank()) View.GONE else View.VISIBLE)
                badge(context, this, R.id.row_image, image)
                if (key.isNotEmpty()) {
                    val checked = config.optJSONObject("checked")?.optBoolean(key) == true
                    setViewVisibility(R.id.row_check, View.VISIBLE); setTextViewText(R.id.row_check, if (checked) "☑" else "□")
                    setInt(R.id.row_title, "setPaintFlags", if (checked) android.graphics.Paint.ANTI_ALIAS_FLAG or android.graphics.Paint.STRIKE_THRU_TEXT_FLAG else android.graphics.Paint.ANTI_ALIAS_FLAG)
                    setContentDescription(R.id.row_root, "${if (checked) "Completed" else "Not completed"}: $text. Tap to toggle.")
                }
                setOnClickFillInIntent(R.id.row_root, Intent().putExtra("result_index", index).putExtra("toggle_key", key))
            })
        }
        fun hero(index: Int, text: String, detail: String = "", value: String = "", image: String = "") {
            add(RemoteViews(context.packageName, R.layout.widget_hero).apply {
                setTextViewText(R.id.hero_title, text.take(200)); setTextViewText(R.id.hero_detail, detail.take(600))
                if (value.isNotBlank()) { setViewVisibility(R.id.hero_value, View.VISIBLE); setTextViewText(R.id.hero_value, value.take(100)) }
                badge(context, this, R.id.hero_image, image)
                setOnClickFillInIntent(R.id.hero_root, Intent().putExtra("result_index", index))
            })
        }
        results.forEachIndexed { index, result ->
            val items = ThreadModel.rows(result.optJSONArray("items"))
            val item = items.firstOrNull() ?: return@forEachIndexed
            when (result.optString("domain")) {
                "world_clocks" -> items.chunked(2).forEach { clocks ->
                    add(RemoteViews(context.packageName, R.layout.widget_clocks).apply {
                        clocks.forEachIndexed { n, c ->
                            val zone = try { ZoneId.of(c.getString("zone")).id } catch (_: Exception) { return@forEachIndexed }
                            setTextViewText(if (n == 0) R.id.clock_one_label else R.id.clock_two_label, c.optString("title"))
                            setString(if (n == 0) R.id.clock_one_time else R.id.clock_two_time, "setTimeZone", zone)
                            setString(if (n == 0) R.id.clock_one_date else R.id.clock_two_date, "setTimeZone", zone)
                        }
                        if (clocks.size < 2) { setViewVisibility(R.id.clock_two, View.GONE); setViewVisibility(R.id.clock_divider, View.GONE) }
                        setOnClickFillInIntent(R.id.clocks_root, Intent().putExtra("result_index", index))
                    })
                }
                "sports" -> items.forEach { source ->
                    val profile = sportProfile(source)
                    val records = ThreadModel.rows(profile.optJSONArray("records"))
                    val metrics = ThreadModel.rows(profile.optJSONArray("metrics")).joinToString("   ·   ") { "${it.opt("value")} ${it.optString("label")}" }
                    hero(index, source.optString("title"), listOf(metrics, "${records.size} recent ${if (profile.optString("sport") == "cricket") "innings" else "results"}").filter(String::isNotBlank).joinToString("\n"), image = source.optString("portrait").ifBlank { source.optString("logo") })
                    records.forEach { record -> row(index, record.optString("opponent").ifBlank { record.optString("title") }, listOf(day(record.optString("date")), record.optString("venue"), record.optString("subtitle")).filter(String::isNotBlank).joinToString(" · "), record.optString("score"), record.optString("opponent_logo")) }
                    if (records.isEmpty()) row(index, "Open source coverage", profile.optString("coverage", result.optString("note", "Structured records unavailable.")))
                    if (source.optJSONArray("warnings")?.length() ?: 0 > 0) row(index, "Coverage note", source.getJSONArray("warnings").join(" · "))
                }
                "weather" -> {
                    hero(index, item.optString("title"), item.optString("condition") + " · Wind ${item.opt("wind")} km/h", "${item.opt("temperature")}°")
                    ThreadModel.rows(item.optJSONArray("forecast")).forEach { forecast -> row(index, day(forecast.optString("date")), "${forecast.optString("condition")} · Rain ${forecast.opt("rain")}%", "${forecast.opt("high")}° / ${forecast.opt("low")}°") }
                }
                "document" -> {
                    val doc = item.optJSONObject("document") ?: return@forEachIndexed
                    hero(index, doc.optString("title"), "Saved AI draft" + doc.optString("summary").takeIf(String::isNotBlank)?.let { " · $it" }.orEmpty())
                    ThreadModel.rows(doc.optJSONArray("blocks")).forEachIndexed { bi, block ->
                        if (block.optString("heading").isNotBlank() || block.optString("text").isNotBlank()) row(index, block.optString("heading"), block.optString("text"))
                        val entries = block.optJSONArray("items")
                        if (entries != null) for (i in 0 until entries.length()) row(index, entries.optString(i), key = if (doc.optString("kind") == "checklist") checkKey(result, bi, i, entries.optString(i)) else "")
                    }
                    val columns = doc.optJSONArray("columns"); val table = doc.optJSONArray("rows")
                    if (columns != null && table != null) for (i in 0 until table.length()) {
                        val cells = table.optJSONArray(i) ?: continue
                        row(index, cells.optString(0), (1 until cells.length()).joinToString("\n") { "${columns.optString(it)} · ${cells.optString(it)}" })
                    }
                }
                "timer" -> add(RemoteViews(context.packageName, R.layout.widget_countdown).apply {
                    setTextViewText(R.id.countdown_title, item.optString("title"))
                    val remaining = try { maxOf(0L, Instant.parse(item.getString("end_at")).toEpochMilli() - System.currentTimeMillis()) } catch (_: Exception) { 0L }
                    setChronometer(R.id.countdown_time, SystemClock.elapsedRealtime() + remaining, null, remaining > 0)
                    setChronometerCountDown(R.id.countdown_time, true)
                    setOnClickFillInIntent(R.id.countdown_root, Intent().putExtra("result_index", index))
                })
                "calculate", "convert", "currency", "dates", "clock" -> hero(index, item.optString("title"), result.optString("summary"), (item.opt("value") ?: item.opt("to_time") ?: "").toString())
                else -> {
                    hero(index, if (items.size == 1) item.optString("title") else result.optJSONObject("arguments")?.optString("query") ?: result.optString("domain"), result.optString("source"))
                    items.forEach { source -> row(index, source.optString("title"), listOf(source.optString("body", source.optString("detail", source.optString("snippet", source.optString("summary")))), source.optString("provider"), source.optString("published")).filter(String::isNotBlank).joinToString("\n")) }
                }
            }
        }
        if (results.isEmpty()) hero(0, "Make it yours.", "Tap to create a world clock, match history, plan or something you need.")
    }.take(240)
}
