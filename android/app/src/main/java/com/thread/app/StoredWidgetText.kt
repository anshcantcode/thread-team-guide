package com.thread.app

import org.json.JSONArray
import org.json.JSONObject

/** Pure selection from local snapshots. Captions, drafts and requests are not receipts. */
object StoredWidgetText {
    data class Row(val title: String, val detail: String, val target: String = "")
    data class Receipt(val id: String, val text: String, val confirmed: Boolean)
    private fun rows(array: JSONArray?): List<JSONObject> =
        if (array == null) emptyList() else (0 until array.length()).mapNotNull { array.optJSONObject(it) }
    private fun text(row: JSONObject, key: String) = (row.opt(key) as? String)?.trim().orEmpty()

    fun receipt(workspace: JSONArray?): Receipt? = rows(workspace).asReversed().firstNotNullOfOrNull { result ->
        if (text(result, "id").isBlank() || text(result, "domain") != "phone" || text(result, "provenance") in setOf("draft", "demo", "synthetic")) return@firstNotNullOfOrNull null
        val item = rows(result.optJSONArray("items")).firstOrNull() ?: return@firstNotNullOfOrNull null
        val status = text(item, "status")
        val label = when (status) {
            "completed" -> "Confirmed"
            "handed_off" -> "Handed off · completion unverified"
            "prepared" -> "Prepared · not completed"
            "failed", "cancelled", "unknown", "needs_connection" -> status.replace('_', ' ').replaceFirstChar { it.uppercase() }
            else -> return@firstNotNullOfOrNull null
        }
        val detail = text(item, "detail")
        if (detail.isBlank()) null else Receipt(text(result, "id") + ":" + status, "$label: $detail", status == "completed")
    }

    fun now(snapshot: JSONObject?, live: Boolean = false): List<Row> {
        if (snapshot == null) return listOf(Row("Saved task unavailable", "Open THREAD to check the saved conversation."))
        val task = snapshot.optJSONObject("task")
        val action = snapshot.optJSONObject("active_action")
        val slots = task?.optJSONObject("slots") ?: JSONObject()
        val heading = action?.let { text(it, "title") }?.takeIf { it.isNotBlank() }
            ?: if (text(slots, "origin").isNotBlank() && text(slots, "destination").isNotBlank()) "${text(slots, "origin")} → ${text(slots, "destination")}"
            else task?.optJSONObject("capability")?.let { text(it, "title") }?.takeIf { it.isNotBlank() }
                ?: task?.let { text(it, "domain").replace('_', ' ').replaceFirstChar { c -> c.uppercase() } }?.takeIf { it.isNotBlank() }
                ?: "No current task"
        val status = when {
            task?.optBoolean("ended") == true -> "Task ended"
            task?.optBoolean("paused") == true -> "Paused · details kept"
            action?.optString("status") == "running" -> if (live) "Working · outcome not confirmed" else "Saved request · outcome not confirmed"
            task == null && action == null -> "Start talking to THREAD."
            !live -> "Saved task · open THREAD for current status"
            else -> "Current task · open for details"
        }
        return listOf(Row(heading.take(200), status), Row("Last action receipt",
            receipt(snapshot.optJSONArray("workspace"))?.text ?: "No stored action receipt yet."))
    }

    fun watches(watches: List<JSONObject>?): List<Row> {
        if (watches == null) return listOf(Row("Watches unavailable", "Open Watches to inspect saved data."))
        if (watches.isEmpty()) return listOf(Row("No Watches yet", "Open Watches to add a topic."))
        return watches.map { watch ->
            val items = rows(watch.optJSONArray("items")).associateBy { text(it, "id") }
            // Baseline articles never have new_ids. Walk newest-first history, retaining the
            // last genuinely new item across later empty or failed checks.
            val newest = rows(watch.optJSONArray("history")).firstNotNullOfOrNull { check ->
                if (check.optString("status") != "completed") return@firstNotNullOfOrNull null
                val ids = check.optJSONArray("new_ids") ?: return@firstNotNullOfOrNull null
                (0 until ids.length()).firstNotNullOfOrNull { items[ids.optString(it)] }
            }
            val lastCheck = rows(watch.optJSONArray("history")).firstOrNull()
            val state = when {
                !watch.optBoolean("active") -> "Stopped · history kept"
                lastCheck?.optString("status") == "failed" -> "Last check failed · saved update"
                else -> "Saved update"
            }
            Row(text(watch, "topic").take(200), if (newest == null) {
                val empty = if (watch.optBoolean("baseline")) "No new reports after the baseline." else "Waiting for the first successful check."
                "$state\n$empty"
            } else "$state\n${text(newest, "title")}\n${text(newest, "source")}", text(watch, "id"))
        }
    }

    fun kitchen(items: JSONArray?): Row {
        if (items == null) return Row("Checklist unavailable", "Open Kitchen to inspect saved data.")
        val saved = rows(items)
        if (saved.size != items.length() || saved.any { it.opt("checked") !is Boolean || text(it, "text").isBlank() })
            return Row("Checklist unavailable", "Open Kitchen to inspect saved data.")
        if (saved.isEmpty()) return Row("No saved steps yet", "Open Kitchen to start a checklist.")
        val done = saved.count { it.getBoolean("checked") }
        val next = saved.firstOrNull { !it.getBoolean("checked") }
        return Row("$done of ${saved.size} steps checked", next?.let { "Next: ${text(it, "text")}" } ?: "All saved steps checked.")
    }
}
