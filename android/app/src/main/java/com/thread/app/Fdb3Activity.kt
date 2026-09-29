package com.thread.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.*
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import okhttp3.*
import okio.ByteString.Companion.toByteString
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.util.UUID
import java.util.concurrent.TimeUnit

/** Host-backed AgentSession, native microphone/speaker and real app-private storage. */
class Fdb3Activity : ComponentActivity() {
    private val main = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS).pingInterval(20, TimeUnit.SECONDS).build()
    private lateinit var store: Fdb3ClientStore
    private lateinit var host: EditText
    private lateinit var input: EditText
    private lateinit var state: TextView
    private lateinit var transcript: TextView
    private lateinit var items: TextView
    private lateinit var receipt: TextView
    private var socket: WebSocket? = null
    private var audio: LiveAudio? = null
    private var generation = 0
    private var connected = false
    private var microphoneWanted = false
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) connect(true) else state.text = "Microphone permission is off. You can connect and type."
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Fdb3ClientStore(this)
        fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(28), dp(24), dp(24))
            setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars())
                view.setPadding(dp(24) + bars.left, dp(20) + bars.top, dp(24) + bars.right, dp(24) + bars.bottom)
                insets
            }
            setBackgroundColor(Color.rgb(9, 17, 28))
        }
        fun text(value: String, size: Float = 16f): TextView = TextView(this).apply {
            text = value; textSize = size; setTextColor(Color.rgb(228, 237, 249))
            setPadding(0, dp(8), 0, dp(8)); layout.addView(this)
        }
        fun field(hintText: String): EditText = EditText(this).apply {
            hint = hintText; setTextColor(Color.WHITE); setHintTextColor(Color.LTGRAY)
            setSingleLine(); layout.addView(this)
        }
        fun button(label: String, action: () -> Unit) = Button(this).also {
            it.text = label; it.isAllCaps = false; it.setOnClickListener { action() }; layout.addView(it)
        }
        text("THREAD / KITCHEN", 14f)
        text("One request. Keep going.", 30f)
        text("Checkpoint mode · current FDB-v3 controller", 14f)
        text("Connect to your trusted development host. Audio and typed requests go to its LiveKit agent. Only checklist tools are enabled; items and receipts stay in this app. Voice stops when you leave this screen.", 15f)
        host = field("Host address").apply {
            setText(getSharedPreferences("fdb3-client", MODE_PRIVATE).getString("host", "http://127.0.0.1:8768"))
        }
        state = text("Disconnected. Start the host service and configure USB forwarding first.", 14f)
        button("Connect and talk") {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) connect(true)
            else permission.launch(Manifest.permission.RECORD_AUDIO)
        }
        button("Connect without microphone") { connect(false) }
        button("End conversation") { disconnect(); state.text = "Ended. Saved checklist retained." }
        input = field("Ask for a checklist change")
        button("Send request") {
            val value = input.text.toString().trim()
            if (!connected) state.text = "Connect before sending a request."
            else if (value.isNotEmpty()) {
                audio?.typed(); send(JSONObject().put("type", "text").put("text", value.take(2000)))
                state.text = "Working on your request…"
                input.setText("")
            }
        }
        transcript = text("Your conversation appears here.")
        text("Saved on this phone", 23f)
        items = text("")
        text("Latest action receipt", 20f)
        receipt = text("")
        text("Reconnecting starts a fresh conversation. The checklist remains. This mode uses the host's recognizer, planner and local speech synthesizer; it does not use your saved Gemini key.", 13f)
        setContentView(ScrollView(this).apply { addView(layout) })
        refresh()
    }

    private fun connect(microphone: Boolean) {
        if (socket != null) { state.text = "End the current connection before starting another."; return }
        val endpoint = try { checkedHost(host.text.toString()) } catch (_: Exception) {
            state.text = "Use a loopback HTTP address or an HTTPS address without credentials, a path or a query."; return
        }
        try { store.newInput() } catch (_: Exception) { state.text = "Local storage is unavailable. The conversation was not started."; return }
        microphoneWanted = microphone
        val current = ++generation
        getSharedPreferences("fdb3-client", MODE_PRIVATE).edit().putString("host", endpoint).apply()
        state.text = "Connecting to the FDB-v3 host…"
        socket = http.newWebSocket(Request.Builder().url(endpoint.replaceFirst("http", "ws") + "/voice").build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (current != generation) { webSocket.close(1000, "Superseded"); return }
                webSocket.send(JSONObject().put("type", "hello").put("client", "android")
                    .put("session_id", store.sessionId).put("input_token", store.inputToken).toString())
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                main.post {
                    if (current == generation) try { event(JSONObject(text)) }
                    catch (_: Exception) { disconnect(); state.text = "Invalid host response. No retry was sent; inspect the saved checklist." }
                }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = main.post {
                if (current == generation) { disconnect(); state.text = "Host unavailable. Start serve_fdb3_clients.py and check USB forwarding. Saved items remain." }
            }.let { Unit }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = main.post {
                if (current == generation) { disconnect(); state.text = "Host connection ended. Saved items remain." }
            }.let { Unit }
        })
    }

    private fun event(event: JSONObject) {
        when (event.optString("type")) {
            "live_ready" -> {
                connected = true; state.text = if (microphoneWanted) "Listening through the host" else "Connected. Type a request."
                audio = LiveAudio(this, ::send, { frame ->
                    if ((socket?.queueSize() ?: 0) > 128000) main.post { disconnect(); state.text = "Audio fell behind. Reconnect on a stable connection." }
                    else socket?.send(frame.toByteString())
                }, { mode, _ -> main.post { if (connected) state.text = mode } }, { message -> main.post { state.text = message } }).also {
                    it.acknowledgments = false; it.start(microphoneWanted)
                }
            }
            "tool_request" -> {
                val result = store.execute(event)
                socket?.send(JSONObject().put("type", "tool_result").put("request_id", event.optString("request_id"))
                    .put("session_id", store.sessionId).put("input_token", event.optString("input_token"))
                    .put("result", result).toString())
                refresh()
            }
            "caption" -> {
                audio?.event(event)
                val speaker = if (event.optString("role") == "user") "You" else "THREAD"
                transcript.text = speaker + ": " + event.optString("text")
            }
            "live_error" -> { val message = event.optString("text"); disconnect(); state.text = message }
            else -> audio?.event(event)
        }
    }

    @Synchronized private fun send(event: JSONObject) {
        if (event.optString("type") in setOf("latency", "resume_after_noise", "continue_after_noise")) return
        if (event.optString("type") in setOf("text", "speech_start")) {
            try { store.newInput() } catch (_: Exception) {
                main.post { disconnect(); state.text = "Local storage is unavailable. Voice stopped; inspect your saved checklist." }
                return
            }
            event.put("input_token", store.inputToken)
        }
        if (event.optString("type") == "playback") {
            event.put("seconds", event.optDouble("played_ms", 0.0) / 1000.0)
            event.put("interrupted", event.optString("status") == "interrupted")
        }
        socket?.send(event.toString())
    }

    private fun refresh() {
        items.text = store.displayItems()
        receipt.text = store.lastReceipt()
    }

    private fun disconnect() {
        ++generation; connected = false
        // The in-memory token changes even if disk persistence fails; resource closure must still run.
        runCatching { store.newInput() }
        val old = socket; socket = null
        old?.send(JSONObject().put("type", "end").toString()); old?.close(1000, "Ended")
        audio?.close(); audio = null
    }
    override fun onPause() { disconnect(); state.text = "Conversation stopped. Saved checklist retained."; super.onPause() }
    override fun onDestroy() { http.dispatcher.executorService.shutdown(); http.connectionPool.evictAll(); super.onDestroy() }

    companion object {
        fun checkedHost(value: String): String {
            val uri = URI(value.trim().trimEnd('/'))
            require(uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null && (uri.path ?: "").isEmpty())
            require(uri.port == -1 || uri.port in 1..65535)
            require(uri.host != null && (uri.scheme == "https" || (uri.scheme == "http" && uri.host in setOf("127.0.0.1", "localhost", "[::1]"))))
            return uri.toASCIIString()
        }
    }
}

/** Network authority is separate from the reusable local command implementation. */
class Fdb3ClientStore(context: Context) {
    private val client = context.getSharedPreferences("fdb3-client", Context.MODE_PRIVATE)
    val sessionId: String = client.getString("session", null) ?: UUID.randomUUID().toString().replace("-", "").also {
        check(client.edit().putString("session", it).commit())
    }
    private val prefs = context.getSharedPreferences("fdb3-$sessionId", Context.MODE_PRIVATE)
    private val store = Fdb3ExtensionStore(context) { error("Network Kitchen tools cannot invoke device intents") }
    @Volatile var inputToken = ""; private set
    init { require(Regex("[a-f0-9]{32}").matches(sessionId)); newInput() }
    @Synchronized fun newInput() {
        inputToken = UUID.randomUUID().toString().replace("-", "")
        check(prefs.edit().putString("input", inputToken).commit())
    }
    @Synchronized fun execute(request: JSONObject): JSONObject {
        fun denied(detail: String) = JSONObject().put("status", "error").put("error", "invalid_args")
            .put("detail", detail).put("session_id", sessionId).put("request_id", request.optString("request_id"))
        if (request.optString("session_id") != sessionId || request.optString("input_token") != inputToken)
            return denied("A newer input or ended conversation replaced this request. No action was submitted.")
        if (request.optString("command") !in setOf("read_checklist", "add_checklist_item", "set_checklist_item"))
            return denied("This mode only exposes checklist tools.")
        return try {
            store.execute(request).also { result ->
                check(client.edit().putString("last-receipt", result.toString()).commit())
            }
        } catch (_: Exception) {
            JSONObject().put("status", "error").put("error", "outcome_unknown")
                .put("detail", "The local receipt could not be verified. No retry was submitted; inspect the saved checklist.")
                .put("session_id", sessionId).put("request_id", request.optString("request_id"))
        }
    }
    fun displayItems(): String = try {
        val rows = JSONArray(prefs.getString("items", "[]"))
        if (rows.length() == 0) "No saved steps yet." else (0 until rows.length()).joinToString("\n\n") {
            val row = rows.getJSONObject(it)
            val marker = if (row.getBoolean("checked")) "✓" else "○"
            marker + " " + row.getString("text")
        }
    } catch (_: Exception) { "Saved checklist could not be read. Its data has been retained." }
    fun lastReceipt(): String = try {
        client.getString("last-receipt", null)?.let { JSONObject(it).getString("detail") } ?: "No action receipt yet."
    } catch (_: Exception) { "The saved receipt could not be read." }
}
