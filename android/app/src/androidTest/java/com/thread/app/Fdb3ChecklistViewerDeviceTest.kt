package com.thread.app

import android.content.Context
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class Fdb3ChecklistViewerDeviceTest {
    private fun id() = UUID.randomUUID().toString().replace("-", "")
    private fun texts(view: View): List<String> = when (view) {
        is TextView -> listOf(view.text.toString())
        is ViewGroup -> (0 until view.childCount).flatMap { texts(view.getChildAt(it)) }
        else -> emptyList()
    }

    @Test fun viewerShowsActualStoredItemAndReceiptWithoutChangingStoreAcrossRecreation() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val session = id()
        val receipt = id()
        fun request(command: String, args: JSONObject = JSONObject(), requestId: String = id()) =
            JSONObject().put("session_id", session).put("request_id", requestId).put("input_token", "input-1").put("command", command).put("args", args)
        val store = Fdb3ExtensionStore(context) { error("Viewer/checklist must never invoke Clock") }
        try {
            store.execute(request("set_input"))
            store.execute(request("add_checklist_item", JSONObject().put("text", "Rinse basil"), receipt))
            val prefs = context.getSharedPreferences("fdb3-$session", Context.MODE_PRIVATE)
            val before = prefs.all.toMap()
            val intent = Intent(context, Fdb3ChecklistViewerActivity::class.java).putExtra("session_id", session).putExtra("request_id", receipt)
            ActivityScenario.launch<Fdb3ChecklistViewerActivity>(intent).use { scenario ->
                fun check() = scenario.onActivity { activity ->
                    val visible = texts(activity.window.decorView)
                    assertTrue(visible.contains("○  Rinse basil"))
                    assertTrue(visible.contains("Added checklist step: Rinse basil"))
                    assertEquals(before, prefs.all)
                }
                check()
                scenario.recreate()
                check()
            }
            assertEquals(before, prefs.all)
        } finally { store.execute(request("cleanup")) }
    }

    @Test fun unknownOrInvalidSessionDoesNotInventItemsOrReadAnotherSession() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        for ((session, expected) in listOf(id() to "No saved checklist for this session.", "../other" to "Choose a valid checklist session.")) {
            val intent = Intent(context, Fdb3ChecklistViewerActivity::class.java).putExtra("session_id", session)
            ActivityScenario.launch<Fdb3ChecklistViewerActivity>(intent).use { scenario ->
                scenario.onActivity { activity ->
                    val visible = texts(activity.window.decorView)
                    assertTrue(visible.contains(expected))
                    assertFalse(visible.any { it.startsWith("○  ") || it.startsWith("✓  ") })
                }
            }
        }
    }
}
