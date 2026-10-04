package com.thread.app

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class StoredWidgetTextTest {
    private fun receipt(status: String, id: String = "receipt") = JSONObject().put("id", id).put("domain", "phone")
        .put("items", JSONArray().put(JSONObject().put("status", status).put("detail", "Device outcome")))

    @Test fun nowDoingNeverPromotesCaptionOrRunningRequestToReceipt() {
        val snapshot = JSONObject().put("caption", "I booked it").put("transcript", JSONArray().put(JSONObject().put("text", "Done")))
            .put("active_action", JSONObject().put("title", "Book a table").put("status", "running"))
            .put("workspace", JSONArray().put(receipt("running")))
        val text = StoredWidgetText.now(snapshot)
        assertEquals("Book a table", text[0].title)
        assertTrue(text[0].detail.contains("outcome not confirmed"))
        assertEquals("No stored action receipt yet.", text[1].detail)
        assertTrue(StoredWidgetText.now(snapshot, true)[0].detail.startsWith("Working"))
    }
    @Test fun latestRealReceiptSurvivesLaterDraftAndRequest() {
        val draft = JSONObject().put("id", "draft").put("domain", "document").put("provenance", "draft").put("status", "completed")
        val saved = JSONArray().put(receipt("completed")).put(draft).put(receipt("running", "request"))
        val result = StoredWidgetText.receipt(saved)!!
        assertEquals("receipt:completed", result.id)
        assertTrue(result.confirmed)
    }
    @Test fun handoffAndPreparedAreShownAsSuchNeverConfirmed() {
        val handoff = StoredWidgetText.receipt(JSONArray().put(receipt("handed_off")))!!
        assertFalse(handoff.confirmed); assertTrue(handoff.text.contains("completion unverified"))
        val prepared = StoredWidgetText.receipt(JSONArray().put(receipt("prepared")))!!
        assertFalse(prepared.confirmed); assertTrue(prepared.text.contains("not completed"))
        val failed = StoredWidgetText.receipt(JSONArray().put(receipt("failed")))!!
        assertFalse(failed.confirmed); assertTrue(failed.text.startsWith("Failed:"))
    }
    @Test fun taskUsesStoredSlotsAndPauseStatusWithoutImplyingLiveWork() {
        val task = JSONObject().put("domain", "travel").put("slots", JSONObject().put("origin", "Pune").put("destination", "Delhi"))
        val snapshot = JSONObject().put("task", task)
        assertEquals("Pune → Delhi", StoredWidgetText.now(snapshot)[0].title)
        assertTrue(StoredWidgetText.now(snapshot)[0].detail.startsWith("Saved task"))
        task.put("paused", true)
        assertEquals("Paused · details kept", StoredWidgetText.now(snapshot, true)[0].detail)
    }
    @Test fun missingAndUnreadableStateHaveDistinctGracefulEmptyStates() {
        assertEquals("No current task", StoredWidgetText.now(JSONObject())[0].title)
        assertEquals("Saved task unavailable", StoredWidgetText.now(null)[0].title)
        assertEquals("No Watches yet", StoredWidgetText.watches(emptyList())[0].title)
        assertEquals("Watches unavailable", StoredWidgetText.watches(null)[0].title)
        assertEquals("No saved steps yet", StoredWidgetText.kitchen(JSONArray()).title)
        assertEquals("Checklist unavailable", StoredWidgetText.kitchen(null).title)
    }
    @Test fun watchShowsOnlyActualNewItemNotBaselineAndKeepsItAfterNoNewsOrFailure() {
        val dir = Files.createTempDirectory("thread-widget-watch").toFile()
        try {
            var changes = 0
            val store = WatchStore(dir.resolve("watches.json")).apply { onChanged = { changes++ } }
            val watch = store.create(JSONObject().put("topic", "Local council").put("every_minutes", 15))
            val id = watch.getString("id"); val generation = watch.getString("generation")
            fun item(id: String, title: String) = JSONObject().put("id", id).put("story_key", "story-$id").put("title", title).put("source", "Journal")
            val baseline = item("baseline", "Old news")
            store.record(id, generation, listOf(baseline))
            assertFalse(StoredWidgetText.watches(store.list()).single().detail.contains("Old news"))
            val fresh = item("fresh", "A new vote")
            store.record(id, generation, listOf(fresh, baseline))
            store.record(id, generation, listOf(fresh, baseline))
            store.record(id, generation, emptyList(), "Offline")
            val restarted = WatchStore(dir.resolve("watches.json"))
            val row = StoredWidgetText.watches(restarted.list()).single()
            assertEquals(id, row.target); assertTrue(row.detail.contains("A new vote")); assertTrue(row.detail.contains("Last check failed"))
            assertEquals(5, changes)
        } finally { dir.deleteRecursively() }
    }
    @Test fun kitchenCountsActualBooleansAndSelectsNextUncheckedStep() {
        val items = JSONArray("""[{"text":"Wash rice","checked":true},{"text":"Boil water","checked":false}]""")
        assertEquals(StoredWidgetText.Row("1 of 2 steps checked", "Next: Boil water"), StoredWidgetText.kitchen(items))
        items.getJSONObject(1).put("checked", true)
        assertEquals("All saved steps checked.", StoredWidgetText.kitchen(items).detail)
        items.getJSONObject(1).put("checked", "true")
        assertEquals("Checklist unavailable", StoredWidgetText.kitchen(items).title)
    }
}
