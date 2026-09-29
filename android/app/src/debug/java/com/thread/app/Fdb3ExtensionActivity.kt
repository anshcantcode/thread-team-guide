package com.thread.app

import android.app.Activity
import android.os.Build
import android.os.Bundle
import android.util.Base64
import org.json.JSONObject

/** Debug-only, tethered emulator transport; no Python/Gemini app runtime involved. */
class Fdb3ExtensionActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            require(Build.HARDWARE in setOf("ranchu", "goldfish")) { "Emulator required" }
            val encoded = intent.getStringExtra("payload") ?: error("Missing payload")
            require(encoded.length <= 11000 && Regex("[A-Za-z0-9_=-]+").matches(encoded))
            val request = JSONObject(String(Base64.decode(encoded, Base64.URL_SAFE), Charsets.UTF_8))
            val id = Fdb3ExtensionStore.reference(request, "request_id")
            Fdb3ExtensionStore.reference(request, "session_id")
            val store = Fdb3ExtensionStore(this) { PhoneActions(this) {}.execute(it) }
            val result = store.execute(request)
            val destination = filesDir.resolve("fdb3-$id.json")
            val temporary = filesDir.resolve("fdb3-$id.tmp")
            temporary.writeText(result.toString())
            check(temporary.renameTo(destination))
        } finally { finish() }
    }
}
