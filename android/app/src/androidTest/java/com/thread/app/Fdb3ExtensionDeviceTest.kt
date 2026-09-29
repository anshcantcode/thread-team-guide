package com.thread.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

/** Actual app-private storage checks; the injected Clock callback has no device effects. */
@RunWith(AndroidJUnit4::class)
class Fdb3ExtensionDeviceTest {
    private fun id() = UUID.randomUUID().toString().replace("-", "")

    @Test fun checklistPersistsCheckedStateAndDeduplicatesAcrossStoreInstances() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val session = id()
        fun request(command: String, args: JSONObject = JSONObject(), requestId: String = id(), token: String = "input-1") =
            JSONObject().put("session_id", session).put("request_id", requestId).put("input_token", token).put("command", command).put("args", args)
        fun store() = Fdb3ExtensionStore(context) { error("Checklist must never invoke Clock") }
        try {
            store().execute(request("set_input"))
            val add = request("add_checklist_item", JSONObject().put("text", "Rinse lentils"))
            val first = store().execute(add)
            val duplicate = store().execute(add)
            assertEquals(first.getString("item_id"), duplicate.getString("item_id"))
            val set = request("set_checklist_item", JSONObject().put("item_id", first.getString("item_id")).put("checked", true))
            assertEquals("success", store().execute(set).getString("status"))
            val rows = store().execute(request("read_checklist")).getJSONArray("items")
            assertEquals(1, rows.length())
            assertTrue(rows.getJSONObject(0).getBoolean("checked"))
            val stale = store().execute(request("add_checklist_item", JSONObject().put("text", "Stale item"), token = "input-0"))
            assertEquals("invalid_args", stale.getString("error"))
            val changed = JSONObject(add.toString()).put("args", JSONObject().put("text", "Changed duplicate"))
            assertEquals("invalid_args", store().execute(changed).getString("error"))
        } finally { store().execute(request("cleanup")) }
    }

    @Test fun handoffNeverClaimsCreationAndCannotBeReplayedOrReplaced() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val session = id()
        var handoffs = 0
        fun request(command: String, args: JSONObject = JSONObject(), requestId: String = id()) =
            JSONObject().put("session_id", session).put("request_id", requestId).put("input_token", "input-1").put("command", command).put("args", args)
        fun store() = Fdb3ExtensionStore(context) { handoffs++; JSONObject().put("status", "handed_off") }
        try {
            store().execute(request("set_input"))
            val timer = request("request_timer_handoff", JSONObject().put("seconds", 73).put("label", "Tea"))
            val first = store().execute(timer)
            assertEquals("success", first.getString("status"))
            assertEquals("handed_off", first.getString("device_status"))
            assertFalse(first.getBoolean("timer_creation_confirmed"))
            store().execute(timer)
            val replacement = store().execute(request("request_timer_handoff", JSONObject().put("seconds", 41).put("label", "Tea")))
            assertEquals("outcome_unknown", replacement.getString("error"))
            assertEquals(1, handoffs)
            assertTrue(store().execute(request("inspect_timer_handoff")).getString("detail").contains("cannot cancel or change"))
        } finally { store().execute(request("cleanup")) }
    }

    @Test fun processFailureAfterSubmissionLeavesDurableUnknownAndNoRetry() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val session = id()
        var handoffs = 0
        fun request(command: String, args: JSONObject = JSONObject(), requestId: String = id()) =
            JSONObject().put("session_id", session).put("request_id", requestId).put("input_token", "input-1").put("command", command).put("args", args)
        val store = Fdb3ExtensionStore(context) { handoffs++; throw IllegalStateException("Simulated process boundary") }
        try {
            store.execute(request("set_input"))
            val timer = request("request_timer_handoff", JSONObject().put("seconds", 37).put("label", "Test"))
            try { store.execute(timer); fail("Missing failure") } catch (_: IllegalStateException) { }
            assertEquals("outcome_unknown", store.execute(timer).getString("error"))
            assertEquals(1, handoffs)
        } finally { store.execute(request("cleanup")) }
    }
}
