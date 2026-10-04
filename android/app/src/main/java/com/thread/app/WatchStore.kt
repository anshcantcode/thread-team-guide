package com.thread.app

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FileOutputStream
import java.net.URI
import java.net.URLEncoder
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID
import javax.xml.parsers.DocumentBuilderFactory

/** Pure JVM parser/store, also exercised by local tests. No Android or model dependency. */
object NewsRss {
    const val MAX_BYTES = 512_000
    fun url(topic: String): String {
        require(topic.trim().length in 1..200 && '\u0000' !in topic)
        return "https://news.google.com/rss/search?q=${URLEncoder.encode(topic.trim(), "UTF-8")}&hl=en-IN&gl=IN&ceid=IN:en"
    }
    private fun hash(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    fun parse(bytes: ByteArray): List<JSONObject> {
        require(bytes.size <= MAX_BYTES && 0.toByte() !in bytes && !Regex("<!\\s*(DOCTYPE|ENTITY)", RegexOption.IGNORE_CASE).containsMatchIn(bytes.toString(Charsets.UTF_8)))
        val factory = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true; isExpandEntityReferences = false }
        val document = factory.newDocumentBuilder().parse(ByteArrayInputStream(bytes))
        require(document.documentElement.tagName == "rss" && document.getElementsByTagName("channel").length == 1)
        val nodes = document.getElementsByTagName("item")
        val seen = mutableSetOf<String>()
        return (0 until minOf(nodes.length, 100)).mapNotNull { index ->
            val node = nodes.item(index) as org.w3c.dom.Element
            fun text(name: String) = node.getElementsByTagName(name).item(0)?.textContent?.trim().orEmpty()
            val title = text("title").replace(Regex("\\s+"), " ").take(1000)
            val source = text("source").replace(Regex("\\s+"), " ").take(200)
            val link = text("link")
            val uri = runCatching { URI(link) }.getOrNull()
            if (title.isBlank() || link.length > 4000 || uri?.scheme !in listOf("http", "https") || uri?.host.isNullOrBlank() || uri?.userInfo != null) return@mapNotNull null
            val id = hash(link); val story = hash(title.lowercase(Locale.ROOT) + "\n" + source.lowercase(Locale.ROOT))
            if (id in seen || story in seen) return@mapNotNull null
            seen.add(id); seen.add(story)
            val published = runCatching { ZonedDateTime.parse(text("pubDate"), DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() }.getOrNull()
            JSONObject().put("id", id).put("story_key", story).put("title", title).put("source", source.ifBlank { "Source not supplied" })
                .put("link", link).put("published_at", published ?: JSONObject.NULL)
        }.sortedByDescending { it.optLong("published_at", 0) }
    }
}

class WatchStore(private val file: File, private val clock: () -> Long = System::currentTimeMillis) {
    var onChanged: () -> Unit = {}
    companion object {
        // One app process; the same lock covers workers, screen controls and the voice bridge.
        val lock = Any()
        fun rows(array: JSONArray): List<JSONObject> = (0 until array.length()).map { array.getJSONObject(it) }
        fun summary(row: JSONObject) = JSONObject(row.toString()).apply { listOf("seen", "items", "history", "generation").forEach { remove(it) } }
        fun minutes(args: JSONObject): Int {
            require(args.has("every_minutes") != args.has("every_hours")) { "Supply exactly one cadence." }
            val value = args.get(if (args.has("every_minutes")) "every_minutes" else "every_hours")
            require(value is Number)
            val number = value.toDouble() * if (args.has("every_hours")) 60 else 1
            require(number.isFinite() && number in 15.0..10080.0 && number == number.toInt().toDouble()) { "Use a cadence of 15 minutes to 7 days." }
            if (args.has("stop_after")) {
                val stop = args.get("stop_after")
                require((stop is Int || stop is Long) && (stop as Number).toLong() in 1..525600) { "stop_after is a duration in minutes." }
            }
            return number.toInt()
        }
    }

    private fun read() = if (file.exists()) JSONArray(file.readText(Charsets.UTF_8)) else JSONArray()
    private fun save(rows: List<JSONObject>) {
        file.parentFile?.mkdirs()
        val temp = File(file.parentFile, file.name + ".tmp")
        FileOutputStream(temp).use { it.write(JSONArray(rows).toString().toByteArray(Charsets.UTF_8)); it.fd.sync() }
        try { Files.move(temp.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING) }
        catch (_: AtomicMoveNotSupportedException) { Files.move(temp.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING) }
        runCatching { onChanged() } // Widget failure must never change a durable Watch outcome.
    }
    private fun load(): List<JSONObject> {
        val rows = rows(read())
        var changed = false
        rows.filter { it.optBoolean("active") && it.optLong("stop_at") in 1..clock() }.forEach {
            it.put("active", false).put("next_check", JSONObject.NULL); changed = true
        }
        if (changed) save(rows)
        return rows
    }
    private fun resolve(rows: List<JSONObject>, args: JSONObject): JSONObject {
        require(!(args.has("id") && args.has("topic"))) { "Use either a Watch id or topic." }
        val target = args.optString("id").ifBlank { args.optString("topic") }.trim()
        val matches = rows.filter { if (target.isBlank()) it.optBoolean("active") else it.getString("id") == target || it.getString("topic").equals(target, true) }
        require(matches.size == 1) { "Name the exact Watch topic or id; there is not a single matching Watch." }
        return matches.single()
    }
    fun list(): List<JSONObject> = synchronized(lock) { load().map { JSONObject(it.toString()).apply { remove("seen") } } }
    fun get(args: JSONObject): JSONObject = synchronized(lock) { JSONObject(resolve(load(), args).toString()) }
    fun create(args: JSONObject): JSONObject = synchronized(lock) {
        val minutes = minutes(args)
        val topic = args.getString("topic").trim(); NewsRss.url(topic)
        val rows = load().toMutableList()
        val existing = rows.firstOrNull { it.getString("topic").equals(topic, true) }
        if (existing?.optBoolean("active") == true) {
            require(existing.getInt("every_minutes") == minutes && existing.optLong("stop_after") == args.optLong("stop_after")) { "Stop this Watch before changing its schedule." }
            return@synchronized JSONObject(existing.toString()).apply { remove("seen") }
        }
        require(existing != null || rows.size < 20) { "This phone supports at most 20 saved Watches." }
        val now = clock()
        val row = existing ?: JSONObject().put("id", UUID.randomUUID().toString()).put("topic", topic).put("seen", JSONArray())
            .put("items", JSONArray()).put("history", JSONArray()).put("last_checked", JSONObject.NULL).put("baseline", false)
        row.put("active", true).put("generation", UUID.randomUUID().toString()).put("every_minutes", minutes).put("created_at", now).put("next_check", now)
            .put("stop_after", args.opt("stop_after") ?: JSONObject.NULL)
            .put("stop_at", if (args.has("stop_after")) now + args.getLong("stop_after") * 60000 else JSONObject.NULL)
        if (existing == null) rows.add(row)
        save(rows)
        JSONObject(row.toString()).apply { remove("seen") }
    }
    fun stop(args: JSONObject): JSONObject = synchronized(lock) {
        val rows = load(); val row = resolve(rows, args)
        row.put("active", false).put("next_check", JSONObject.NULL)
        save(rows)
        JSONObject(row.toString()).apply { remove("seen") }
    }
    fun record(id: String, generation: String, items: List<JSONObject>, error: String = ""): JSONObject = synchronized(lock) {
        val rows = load(); val row = resolve(rows, JSONObject().put("id", id))
        if (!row.getBoolean("active") || row.getString("generation") != generation)
            return@synchronized JSONObject().put("status", "cancelled").put("detail", "Watch stopped or replaced during the check.").put("new_items", JSONArray())
        val seenArray = row.getJSONArray("seen")
        val seen = (0 until seenArray.length()).map { seenArray.getString(it) }.toMutableSet()
        val baseline = row.getBoolean("baseline")
        var fresh = if (baseline) items.filter { it.getString("id") !in seen && it.getString("story_key") !in seen } else emptyList()
        val identities = seen + items.flatMap { listOf(it.getString("id"), it.getString("story_key")) }
        var status = "completed"
        val detail = if (error.isNotBlank()) { status = "failed"; fresh = emptyList(); error }
        else if (identities.size > 20000) {
            row.put("active", false); status = "failed"; fresh = emptyList()
            "Watch stopped at its 20,000-identity storage limit. History was preserved."
        } else {
            row.put("seen", JSONArray(identities.sorted())).put("baseline", true)
                .put("items", JSONArray((if (baseline) fresh + rows(row.getJSONArray("items")) else items).take(100)))
            if (!baseline) "Baseline saved. Only future newly discovered reports will notify." else if (fresh.isEmpty()) "No new updates." else "${fresh.size} new updates."
        }
        val now = clock()
        row.put("last_checked", now).put("next_check", if (row.getBoolean("active")) now + row.getInt("every_minutes") * 60000L else JSONObject.NULL)
        val history = JSONObject().put("checked_at", now).put("status", status).put("detail", detail).put("new_count", fresh.size).put("new_ids", JSONArray(fresh.map { it.getString("id") }))
        row.put("history", JSONArray((listOf(history) + rows(row.getJSONArray("history"))).take(100)))
        save(rows)
        JSONObject().put("status", status).put("detail", detail).put("new_items", JSONArray(fresh)).put("watch_id", id)
    }
}
