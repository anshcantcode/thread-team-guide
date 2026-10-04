package com.thread.app

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class WatchStoreTest {
    private fun feed(name: String) = NewsRss.parse(javaClass.classLoader!!.getResourceAsStream(name)!!.use { it.readBytes() })
    private fun rejects(block: () -> Unit) { try { block(); fail("Expected rejection") } catch (_: IllegalArgumentException) { } }

    @Test fun savedRssParsesEntitiesSourcesTimesAndDuplicateStories() {
        val items = feed("news.xml")
        assertEquals(2, items.size)
        assertEquals("Example Journal", items[0].getString("source"))
        assertEquals(1791030600000L, items[0].getLong("published_at"))
        assertEquals("Committee releases a timetable & review notes", items[1].getString("title"))
        assertEquals(64, items[0].getString("id").length)
        assertTrue(NewsRss.url("City & council?").contains("q=City+%26+council%3F"))
    }
    @Test fun rejectsEntitiesOversizeAndNonRss() {
        rejects { NewsRss.parse("<!DOCTYPE rss [<!ENTITY leak SYSTEM 'file:///secret'>]><rss><channel/></rss>".toByteArray()) }
        rejects { NewsRss.parse(ByteArray(512001)) }
        rejects { NewsRss.parse("<!DOCTYPE rss><rss><channel/></rss>".toByteArray(Charsets.UTF_16)) }
        rejects { NewsRss.parse("<html/>".toByteArray()) }
    }
    @Test fun missingMetadataIsNotInvented() {
        val item = NewsRss.parse("<rss><channel><item><title>A report</title><link>https://example.com/a</link><pubDate>invalid</pubDate></item></channel></rss>".toByteArray()).single()
        assertTrue(item.isNull("published_at")); assertEquals("Source not supplied", item.getString("source"))
    }
    @Test fun baselineDedupHistoryAndRestartAreDurable() {
        val directory = Files.createTempDirectory("thread-watch-test").toFile()
        try {
            var now = 1000000L
            val file = directory.resolve("watches.json")
            val store = WatchStore(file) { now }
            val created = store.create(JSONObject().put("topic", "Council").put("every_hours", 2))
            val id = created.getString("id"); val generation = created.getString("generation")
            val baseline = store.record(id, generation, feed("news.xml"))
            assertEquals(0, baseline.getJSONArray("new_items").length())
            assertTrue(baseline.getString("detail").startsWith("Baseline"))
            now += 7200000
            assertEquals(1, store.record(id, generation, feed("news-next.xml")).getJSONArray("new_items").length())
            val restarted = WatchStore(file) { now }
            assertEquals("No new updates.", restarted.record(id, generation, feed("news-next.xml")).getString("detail"))
            val row = restarted.list().single()
            assertEquals(3, row.getJSONArray("items").length()); assertEquals(3, row.getJSONArray("history").length())
            assertEquals(now + 7200000, row.getLong("next_check")); assertFalse(row.has("seen"))
        } finally { directory.deleteRecursively() }
    }
    @Test fun stoppedOrExpiredWatchCannotPublishLateFetch() {
        val directory = Files.createTempDirectory("thread-watch-test").toFile()
        try {
            var now = 1000000L
            val store = WatchStore(directory.resolve("watches.json")) { now }
            val row = store.create(JSONObject().put("topic", "Council").put("every_minutes", 15).put("stop_after", 20))
            now += 1200000
            val receipt = store.record(row.getString("id"), row.getString("generation"), feed("news.xml"))
            assertEquals("cancelled", receipt.getString("status"))
            assertFalse(store.list().single().getBoolean("active"))
        } finally { directory.deleteRecursively() }
    }
    @Test fun stopAndRestartRejectsPreviousGenerationWithoutErasingHistory() {
        val directory = Files.createTempDirectory("thread-watch-test").toFile()
        try {
            val store = WatchStore(directory.resolve("watches.json"))
            val args = JSONObject().put("topic", "Council").put("every_minutes", 15)
            val row = store.create(args)
            store.record(row.getString("id"), row.getString("generation"), feed("news.xml"))
            store.stop(JSONObject().put("topic", "Council"))
            store.create(args)
            assertEquals("cancelled", store.record(row.getString("id"), row.getString("generation"), feed("news-next.xml")).getString("status"))
            assertEquals(2, store.list().single().getJSONArray("items").length())
        } finally { directory.deleteRecursively() }
    }
    @Test fun failuresKeepExistingReportsAndAmbiguousStopDoesNotStopEverything() {
        val directory = Files.createTempDirectory("thread-watch-test").toFile()
        try {
            val store = WatchStore(directory.resolve("watches.json"))
            val row = store.create(JSONObject().put("topic", "Council").put("every_minutes", 15))
            store.record(row.getString("id"), row.getString("generation"), feed("news.xml"))
            assertEquals("failed", store.record(row.getString("id"), row.getString("generation"), emptyList(), "Network unavailable.").getString("status"))
            assertEquals(2, store.list().single().getJSONArray("items").length())
            store.create(JSONObject().put("topic", "Weather").put("every_minutes", 30))
            rejects { store.stop(JSONObject()) }
            assertTrue(store.list().all { it.getBoolean("active") })
        } finally { directory.deleteRecursively() }
    }
    @Test fun cadenceAndCorruptStorageAreNotSilentlyRepaired() {
        rejects { WatchStore.minutes(JSONObject().put("every_minutes", 14)) }
        rejects { WatchStore.minutes(JSONObject().put("every_hours", true)) }
        rejects { WatchStore.minutes(JSONObject().put("every_hours", 2).put("every_minutes", 120)) }
        val directory = Files.createTempDirectory("thread-watch-test").toFile()
        try {
            val file = directory.resolve("watches.json"); file.writeText("broken")
            try { WatchStore(file).list(); fail("Corrupt data accepted") } catch (_: org.json.JSONException) { }
            assertEquals("broken", file.readText())
        } finally { directory.deleteRecursively() }
    }
}
