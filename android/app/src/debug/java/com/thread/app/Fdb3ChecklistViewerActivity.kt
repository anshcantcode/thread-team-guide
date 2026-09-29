package com.thread.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject

/** Separate read-only window onto the existing diagnostic store; never dispatches tools. */
class Fdb3ChecklistViewerActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState) }
    override fun onResume() { super.onResume(); render() }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); render() }

    private fun render() {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(36), dp(24), dp(32))
            setBackgroundColor(Color.rgb(247, 249, 251))
        }
        setContentView(ScrollView(this).apply { addView(content) })
        fun text(value: String, size: Float = 17f, bold: Boolean = false, color: Int = Color.rgb(26, 40, 56)) {
            content.addView(TextView(this).apply {
                this.text = value; textSize = size; setTextColor(color)
                if (bold) setTypeface(typeface, Typeface.BOLD)
                setPadding(0, dp(8), 0, dp(8))
            })
        }
        text("THREAD  /  KITCHEN", 13f, true, Color.rgb(16, 110, 105))
        text("Saved checklist", 30f, true)
        text("Read-only view of this device's saved state.", 15f)
        val session = intent.getStringExtra("session_id")
        if (session == null || !Regex("[a-f0-9]{32}").matches(session)) {
            text("Choose a valid checklist session.")
            return
        }
        text("Session ${session.take(8)}", 13f)
        val prefs = getSharedPreferences("fdb3-$session", MODE_PRIVATE)
        val savedItems = prefs.getString("items", null)
        if (savedItems == null) {
            text("No saved checklist for this session.")
        } else {
            try {
                val items = JSONArray(savedItems)
                text("${items.length()} saved ${if (items.length() == 1) "step" else "steps"}", 15f, true)
                if (items.length() == 0) text("The checklist is empty.")
                for (index in 0 until items.length()) {
                    val row = items.getJSONObject(index)
                    text("${if (row.getBoolean("checked")) "✓" else "○"}  ${row.getString("text")}", 23f, true)
                    text(if (row.getBoolean("checked")) "Checked" else "Not checked", 14f)
                }
            } catch (_: org.json.JSONException) { text("Saved checklist could not be read.") }
        }
        text("Action receipt", 21f, true)
        val request = intent.getStringExtra("request_id")
        if (request == null) {
            text("No action receipt selected.", 15f)
        } else if (!Regex("[a-f0-9]{32}").matches(request)) {
            text("Invalid receipt reference.", 15f)
        } else {
            val savedReceipt = prefs.getString("request-$request", null)
            if (savedReceipt == null) text("Selected receipt not found.", 15f)
            else try {
                val result = JSONObject(savedReceipt).getJSONObject("result")
                text(result.getString("status").uppercase(), 13f, true)
                text(result.getString("detail"), 18f)
            } catch (_: org.json.JSONException) { text("Saved receipt could not be read.", 15f) }
        }
        text("Reopen this view to read the saved state again.", 14f)
    }
}
