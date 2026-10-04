package com.thread.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Private preferences hold actual checked state and a durable no-replay journal. */
class Fdb3ExtensionStore(private val context: Context, private val timer: (JSONObject) -> JSONObject) {
    fun execute(request: JSONObject): JSONObject {
        val session = reference(request, "session_id")
        val id = reference(request, "request_id")
        val token = request.getString("input_token")
        require(Regex("[A-Za-z0-9_-]{1,100}").matches(token))
        val prefs = context.getSharedPreferences("fdb3-$session", Context.MODE_PRIVATE)
        fun reply(status: String, detail: String, error: String? = null): JSONObject =
            JSONObject().put("status", status).put("detail", detail).put("session_id", session).put("request_id", id)
                .also { if (error != null) it.put("error", error) }
        val command = request.getString("command")
        val args = request.getJSONObject("args")
        if (command == "cleanup") {
            check(prefs.edit().clear().commit())
            StoredStateWidgets.changed(context)
            context.filesDir.listFiles()?.filter { it.name.startsWith("fdb3-") && it.extension == "json" }?.forEach {
                if (runCatching { JSONObject(it.readText()).optString("session_id") == session }.getOrDefault(false)) it.delete()
            }
            return reply("success", "Diagnostic checklist and receipts removed. Review Clock manually to remove any timer; cleanup does not cancel it.")
        }
        if (command == "set_input") {
            check(prefs.edit().putString("input", token).commit())
            return reply("success", "Current input registered.")
        }
        val fingerprint = JSONObject().put("command", command).put("args", args).toString()
        prefs.getString("request-$id", null)?.let {
            val saved = JSONObject(it)
            return if (saved.getString("fingerprint") == fingerprint) saved.getJSONObject("result")
            else reply("error", "Request reference already belongs to different arguments.", "invalid_args")
        }
        if (prefs.getString("input", null) != token) return reply("error", "Stale input rejected before device action.", "invalid_args")
        if (prefs.all.keys.count { it.startsWith("request-") } >= 500) return reply("error", "Diagnostic journal is full; start a fresh session.", "invalid_args")
        val items = JSONArray(prefs.getString("items", "[]"))
        fun save(result: JSONObject, withItems: Boolean = false): JSONObject {
            val edit = prefs.edit().putString("request-$id", JSONObject().put("fingerprint", fingerprint).put("result", result).toString())
            if (withItems) edit.putString("items", items.toString())
            check(edit.commit())
            if (withItems) StoredStateWidgets.changed(context)
            return result
        }
        fun keys(vararg allowed: String) { require(args.keys().asSequence().toSet() == allowed.toSet()) }
        return try {
            when (command) {
                "read_checklist" -> {
                    keys()
                    save(reply("success", if (items.length() == 0) "The checklist is empty." else
                        (0 until items.length()).joinToString("; ") { val row = items.getJSONObject(it); "${if (row.getBoolean("checked")) "Checked" else "Unchecked"}: ${row.getString("text")}" })
                        .put("items", items))
                }
                "add_checklist_item" -> {
                    keys("text"); require(items.length() < 100)
                    val text = PhoneActions.text(args, "text", 300)
                    val itemId = UUID.randomUUID().toString().replace("-", "")
                    items.put(JSONObject().put("item_id", itemId).put("text", text).put("checked", false))
                    save(reply("success", "Added checklist step: $text").put("item_id", itemId).put("items", items), true)
                }
                "set_checklist_item" -> {
                    keys("item_id", "checked")
                    val itemId = reference(args, "item_id"); require(args.get("checked") is Boolean)
                    val row = (0 until items.length()).map { items.getJSONObject(it) }.firstOrNull { it.getString("item_id") == itemId }
                    if (row == null) reply("error", "The checklist item does not exist.", "not_found")
                    else {
                        row.put("checked", args.getBoolean("checked"))
                        save(reply("success", "${if (row.getBoolean("checked")) "Checked" else "Unchecked"}: ${row.getString("text")}")
                            .put("item_id", itemId).put("items", items), true)
                    }
                }
                "inspect_timer_handoff" -> {
                    keys()
                    save(reply("success", if (prefs.contains("timer"))
                        "A timer request was already submitted. Timer creation is unverified. I cannot cancel or change it; check Clock manually before another timer."
                        else "No timer request is recorded in this session. This is not a readback of Clock.")
                        .put("timer_creation_confirmed", false).put("receipt", prefs.getString("timer", null)))
                }
                "request_timer_handoff" -> {
                    keys("seconds", "label")
                    PhoneActions.int(args, "seconds", 1, 86400); PhoneActions.text(args, "label", 120)
                    if (prefs.contains("timer")) reply("error", "A prior timer may exist. Review Clock manually; no replacement or cancellation was submitted.", "outcome_unknown")
                    else {
                        val unknown = reply("error", "Timer outcome is unknown. Check Clock before any retry.", "outcome_unknown")
                        // Reserve synchronously BEFORE the external intent; process death cannot invite a duplicate.
                        check(prefs.edit().putString("timer", unknown.toString()).putString("request-$id",
                            JSONObject().put("fingerprint", fingerprint).put("result", unknown).toString()).commit())
                        val native = timer(JSONObject().put("request_id", "phone-fdb3-$session-$id").put("action", "set_timer").put("arguments", args))
                        val result = if (native.optString("status") == "handed_off")
                            reply("success", "Sent the timer request to Clock. Timer creation is unverified. Check Clock to review, change or cancel it.")
                        else reply("error", "No timer creation was confirmed. Check Clock before retrying.", "outcome_unknown")
                        result.put("device_status", native.optString("status", "unknown")).put("timer_creation_confirmed", false)
                        check(prefs.edit().putString("timer", result.toString()).commit())
                        save(result)
                    }
                }
                else -> reply("error", "Unknown extension command.", "unknown_tool")
            }
        } catch (_: IllegalArgumentException) { reply("error", "Invalid extension arguments.", "invalid_args") }
          catch (_: org.json.JSONException) { reply("error", "Invalid extension arguments.", "invalid_args") }
    }

    companion object {
        fun reference(value: JSONObject, key: String): String = value.getString(key).also {
            require(Regex("[a-f0-9]{32}").matches(it)) { "Invalid reference" }
        }
    }
}
