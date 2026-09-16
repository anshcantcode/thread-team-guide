package com.thread.app

import android.app.Application
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import okio.ByteString.Companion.toByteString
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

data class ThreadState(val connecting: Boolean = false, val connected: Boolean = false, val mode: String = "Ready",
    val level: Float = 0f, val muted: Boolean = false, val caption: String = "", val captionRole: String = "assistant",
    val error: String? = null, val results: List<JSONObject> = emptyList(), val transcript: List<JSONObject> = emptyList(),
    val ended: Boolean = false, val elapsed: Int = 0, val task: JSONObject? = null,
    val changedSlots: Set<String> = emptySet(), val taskNotice: String = "", val activeAction: JSONObject? = null)

class ThreadModel(app: Application) : AndroidViewModel(app) {
    var ui by mutableStateOf(ThreadState()); private set
    var route by mutableStateOf("voice")
    var keyboard by mutableStateOf(false)
    var taskExpanded by mutableStateOf(false)
    var sharedText by mutableStateOf("")
    var widget by mutableStateOf<JSONObject?>(null)
    var openResult by mutableStateOf<JSONObject?>(null)
    var sportsLoading by mutableStateOf(false); private set
    var sportsError by mutableStateOf<String?>(null); private set
    private var sportsRequest = 0
    var widgetTargetId: Int? = null
    var onWidgetSaved: (() -> Unit)? = null
    val prefs = app.getSharedPreferences("thread", 0)
    var voice by mutableStateOf(prefs.getString("voice", "Kore") ?: "Kore")
    var haptics by mutableStateOf(prefs.getBoolean("haptics", true))
    var acknowledgments by mutableStateOf(prefs.getBoolean("ack", true))
    var consent by mutableStateOf(prefs.getBoolean("consent", false))
    var spotifyClientId by mutableStateOf(prefs.getString("spotify-client-id", "") ?: "")
    var spotifyConnected by mutableStateOf(false); private set
    var spotifyBusy by mutableStateOf(false); private set
    var spotifyMessage by mutableStateOf("Connect your account to use personal listening history and playback."); private set
    var phoneKeyDraft by mutableStateOf("")
    var phoneKeySaved by mutableStateOf(ThreadBackend.hasKey(app)); private set
    var phoneSetupMessage by mutableStateOf(""); private set
    var phoneKeyBusy by mutableStateOf(false); private set
    var deviceAction: ((JSONObject) -> JSONObject)? = null
    private val main = Handler(Looper.getMainLooper())
    val http = ThreadBackend.client(app, OkHttpClient.Builder().connectTimeout(12, TimeUnit.SECONDS).readTimeout(45, TimeUnit.SECONDS).pingInterval(20, TimeUnit.SECONDS))
    private var live: WebSocket? = null
    private var updates: WebSocket? = null
    private var audio: LiveAudio? = null
    var sessionId: String? = null; private set
    private var generation = 0
    private var started = 0L
    private var microphoneWanted = false
    private var pendingText: String? = null
    private var pendingImage: ByteArray? = null
    private var lastLevel = 0L
    private var savePending = false
    @Volatile private var actionInputId = ""
    val endpoint: String get() = ThreadBackend.endpoint(getApplication())
    val spotifyRedirect: String get() = ThreadBackend.spotifyRedirect(getApplication())

    init {
        try {
            val saved = JSONObject(app.filesDir.resolve("workspace.json").takeIf { it.exists() }?.readText() ?: "{}")
            ui = ui.copy(results = rows(saved.optJSONArray("workspace")), transcript = rows(saved.optJSONArray("transcript")), task = saved.optJSONObject("task"), activeAction = saved.optJSONObject("active_action"))
        } catch (_: Exception) { }
    }

    fun preference(key: String, value: Boolean) {
        prefs.edit().putBoolean(key, value).apply()
        when (key) { "haptics" -> haptics = value; "ack" -> { acknowledgments = value; audio?.acknowledgments = value }; "consent" -> consent = value }
    }
    fun selectVoice(value: String) { if (value in listOf("Kore", "Aoede", "Puck", "Charon")) { voice = value; prefs.edit().putString("voice", value).apply() } }

    fun connect(microphone: Boolean = true, text: String? = null) {
        if (ThreadBackend.onPhone(getApplication()) && !ThreadBackend.hasKey(getApplication())) {
            route = "settings"; ui = ui.copy(error = "Add your Gemini API key in Settings to use voice directly from this phone.")
            return
        }
        if (ui.connected) { if (microphone) enableMic(); text?.let { sendText(it) }; return }
        if (ui.connecting) { pendingText = text ?: pendingText; return }
        microphoneWanted = microphone; pendingText = text; started = SystemClock.elapsedRealtime()
        val current = ++generation
        ui = ui.copy(connecting = true, error = null, ended = false, mode = "Connecting", caption = "", elapsed = 0)
        if (microphone) startMicrophoneService()
        if (sessionId != null) openSockets(current) else {
            val body = JSONObject().put("experience", "voice").put("external", false)
            http.newCall(Request.Builder().url("$endpoint/api/sessions").post(body.toString().toRequestBody(JSON)).build()).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) = fail(current, "Couldn’t start the task engine. Reopen THREAD and check your connection.")
                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        try {
                            check(it.isSuccessful); val data = JSONObject(it.body!!.string())
                            main.post { if (current == generation) { sessionId = data.getString("session_id"); openSockets(current) } }
                        } catch (_: Exception) { fail(current, "Couldn’t start a conversation. Reopen THREAD to try again.") }
                    }
                }
            })
        }
    }

    private fun openSockets(current: Int) {
        val websocketBase = endpoint.replaceFirst("http", "ws")
        updates?.close(1000, "Reconnect")
        updates = http.newWebSocket(Request.Builder().url("$websocketBase/ws/$sessionId").build(), object : WebSocketListener() {
            override fun onMessage(ws: WebSocket, text: String) {
                try { val event = JSONObject(text)
                    main.post { if (current == generation) {
                        event.optJSONObject("state")?.let { acceptSnapshot(it) }
                        if (event.optString("type") == "live_tool_call") ui = ui.copy(activeAction = null, taskNotice = "")
                        if (event.optString("type") == "phone_action_requested") ui = ui.copy(activeAction = JSONObject().put("id", event.optString("request_id"))
                            .put("title", event.optString("action").replace('_', ' ').replaceFirstChar { it.uppercase() }).put("action", event.optString("action"))
                            .put("arguments", event.optJSONObject("arguments")).put("status", "running"))
                        if (event.optString("type") == "smart_action_progress") ui.activeAction?.let { ui = ui.copy(activeAction = JSONObject(it.toString()).put("steps", event.optJSONArray("steps"))) }
                        if (event.optString("type") == "phone_action_result" && ui.activeAction?.optString("id") == event.optString("request_id"))
                            ui = ui.copy(activeAction = JSONObject(ui.activeAction.toString()).put("status", event.optString("status")).put("detail", event.optString("text")))
                        val notice = when (event.optString("type")) {
                            "stale_result_excluded" -> "An earlier result was kept out of this task."
                            "authorization_invalidated" -> "The previous action is held while your request changes."
                            "authorization_rejected" -> "The action needs a clear current request."
                            "phone_action_requested" -> "Waiting for the action outcome."
                            "phone_action_result" -> event.optString("text")
                            "smart_action_progress" -> event.optString("text")
                            else -> ""
                        }
                        if (notice.isNotBlank()) ui = ui.copy(taskNotice = notice)
                    } }
                } catch (_: Exception) { }
            }
        })
        live = http.newWebSocket(Request.Builder().url("$websocketBase/live/$sessionId?voice=$voice&client=android")
            .apply { prefs.getString("spotify-handle", null)?.let { header("X-Thread-Spotify", it) } }.build(), object : WebSocketListener() {
            override fun onMessage(ws: WebSocket, text: String) {
                try { val event = JSONObject(text); main.post { if (current == generation) onLive(event) } }
                catch (_: Exception) { fail(current, "The voice connection returned incomplete data. Reconnect to continue.") }
            }
            override fun onFailure(ws: WebSocket, error: Throwable, response: Response?) = fail(current, "Voice disconnected. Your results are saved. Reconnect when you’re ready.")
            override fun onClosed(ws: WebSocket, code: Int, reason: String) { if (code != 1000) fail(current, "Voice disconnected. Your results are saved.") }
        })
    }

    private fun onLive(event: JSONObject) {
        when (event.optString("type")) {
            "live_ready" -> {
                ui = ui.copy(connecting = false, connected = true, mode = "Ready", muted = !microphoneWanted)
                audio = LiveAudio(getApplication(), ::send, { frame ->
                    if ((live?.queueSize() ?: 0) > 128000) fail(generation, "The connection is falling behind. Reconnect for live audio.") else live?.send(frame.toByteString())
                }, { mode, level ->
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastLevel > 55) { lastLevel = now; main.post { if (ui.connected) ui = ui.copy(mode = mode, level = level) } }
                }, { message -> main.post { ui = ui.copy(error = message) } }).also { it.voice = voice; it.acknowledgments = acknowledgments; it.start(microphoneWanted) }
                pendingImage?.let { pendingImage = null; sendImage(it) }
                pendingText?.let { pendingText = null; sendText(it) }; tick()
            }
            "caption" -> {
                audio?.event(event)
                if (event.optString("role") != "user" || LiveAudio.hasWords(event.optString("text"))) {
                    ui = ui.copy(caption = event.optString("text"), captionRole = event.optString("role"), mode = if (event.optString("role") == "user") "Listening" else ui.mode)
                }
            }
            "device_action" -> {
                val result = if (!ui.connected || actionInputId.isBlank() || event.optString("client_input_id") != actionInputId)
                    PhoneActions.outcome("cancelled", "A newer input or ended conversation replaced this phone action.")
                else deviceAction?.invoke(event) ?: PhoneActions.outcome("failed", "Open THREAD to perform this phone action.")
                send(JSONObject().put("type", "device_result").put("request_id", event.optString("request_id")).put("result", result))
            }
            "live_error", "reconnect_needed" -> { val message = event.optString("text"); disconnect(false); ui = ui.copy(error = message) }
            else -> audio?.event(event)
        }
    }

    internal fun acceptSnapshot(state: JSONObject, persist: Boolean = true) {
        val incoming = rows(state.optJSONArray("workspace"))
        val knownIds=ui.results.map { it.optString("id") }.toSet()
        val arrived=incoming.lastOrNull { it.optString("id") !in knownIds && it.optString("domain")!="phone" && (it.optJSONArray("items")?.length() ?: 0)>0 }
        val all = (ui.results + incoming).associateBy { it.optString("id") }.values.toList().takeLast(40)
        val before = ui.task?.optJSONObject("slots") ?: JSONObject()
        val after = state.optJSONObject("slots") ?: JSONObject()
        val fullTask = state.has("domain") && state.has("revision")
        val changed = if (!fullTask) ui.changedSlots else if (ui.task?.optString("domain") == state.optString("domain") && state.optInt("revision") != ui.task?.optInt("revision"))
            (before.keys().asSequence().toSet() + after.keys().asSequence().toSet()).filter { before.opt(it)?.toString() != after.opt(it)?.toString() }.toSet()
        else if (ui.task?.optString("domain") != state.optString("domain")) emptySet() else ui.changedSlots
        val task = if (!fullTask) ui.task else JSONObject().apply {
            listOf("session_id", "domain", "revision", "slots", "selection", "capability", "paused", "ended", "understanding", "floor_held", "operations", "unresolved", "metrics", "missing").forEach { key -> if (state.has(key)) put(key, state.get(key)) }
        }
        val receipt = incoming.lastOrNull { it.optString("domain") == "phone" && (it.optString("id") !in knownIds || it.optString("id") == ui.activeAction?.optString("id")) }
        val activeAction = receipt?.optJSONArray("items")?.optJSONObject(0)?.let { JSONObject(it.toString()).put("arguments", receipt.optJSONObject("arguments")) } ?: ui.activeAction
        ui = ui.copy(results = all, transcript = if (state.has("transcript")) rows(state.optJSONArray("transcript")) else ui.transcript, task = task, changedSlots = changed, activeAction = activeAction,
            taskNotice = if (ui.taskNotice == "Waiting for task control confirmation…") "Task state updated." else ui.taskNotice)
        if(ui.connected && route!="settings" && arrived!=null) openResult=arrived
        if (!persist) return
        if (!savePending) { savePending = true; main.postDelayed({ savePending = false; save() }, 700) }
    }
    private fun save() {
        val data = JSONObject().put("workspace", JSONArray(ui.results)).put("transcript", JSONArray(ui.transcript.takeLast(100))).put("task", ui.task).put("active_action", ui.activeAction)
        val file = getApplication<Application>().filesDir.resolve("workspace.json")
        try { val temp = file.resolveSibling("workspace.tmp"); temp.writeText(data.toString()); temp.renameTo(file) } catch (_: IOException) { ui = ui.copy(error = "Couldn’t save this conversation on the phone.") }
    }
    private fun tick() { if (ui.connected) { ui = ui.copy(elapsed = ((SystemClock.elapsedRealtime() - started) / 1000).toInt()); main.postDelayed(::tick, 1000) } }
    fun send(data: JSONObject) {
        if (data.optString("type") in listOf("text", "speech_start")) {
            actionInputId = java.util.UUID.randomUUID().toString()
            data.put("client_input_id", actionInputId)
        }
        live?.send(data.toString())
    }
    fun controlTask(action: String) {
        if (!ui.connected || action !in listOf("pause", "resume", "stop_work")) return
        actionInputId = "" // Invalidate a device command already queued on the main thread.
        audio?.typed()
        val accepted = updates?.send(JSONObject().put("id", "android-" + java.util.UUID.randomUUID()).put("type", "control")
            .put("data", JSONObject().put("action", action)).toString()) == true
        ui = ui.copy(taskNotice = if (accepted) "Waiting for task control confirmation…" else "Task control could not reach THREAD.")
    }
    fun refreshSpotifyConnection() {
        val handle = prefs.getString("spotify-handle", null) ?: return
        http.newCall(Request.Builder().url("$endpoint/api/spotify/status").header("X-Thread-Spotify", handle).build()).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { main.post { spotifyMessage = "Couldn’t check Spotify. Reopen THREAD and check your internet connection." } }
            override fun onResponse(call: Call, response: Response) { response.use { try {
                check(it.isSuccessful); val data = JSONObject(it.body!!.string())
                main.post { if (prefs.getString("spotify-handle", null) == handle) {
                    spotifyConnected = data.optBoolean("connected")
                    spotifyMessage = if (spotifyConnected) "Connected for this app session. Music uses your active Spotify device." else if (data.optBoolean("pending")) "Finish signing in in your browser, then return here." else "The local connection expired. Connect Spotify again."
                } }
            } catch (_: Exception) { onFailure(call, IOException()) } } }
        })
    }
    fun connectSpotify(open: (String) -> Unit) {
        if (spotifyBusy) return
        if (!Regex("[A-Za-z0-9]{32}").matches(spotifyClientId.trim())) { spotifyMessage = "Enter the public client ID from your Spotify Developer app. No client secret is needed."; return }
        if (endpoint.trimEnd('/') !in listOf(ThreadBackend.PHONE_ENDPOINT, "http://127.0.0.1:8766")) { spotifyMessage = "Spotify sign-in requires the local callback shown below."; return }
        disconnect(false)
        spotifyBusy = true
        val clientId = spotifyClientId.trim()
        val body = JSONObject().put("client_id", clientId).toString().toRequestBody(JSON)
        http.newCall(Request.Builder().url("$endpoint/api/spotify/connect").post(body).build()).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { main.post { spotifyBusy = false; spotifyMessage = "Couldn’t begin Spotify sign-in. Check your internet connection." } }
            override fun onResponse(call: Call, response: Response) { response.use { try {
                check(it.isSuccessful); val data = JSONObject(it.body!!.string()); val url = data.getString("url")
                check(android.net.Uri.parse(url).host == "accounts.spotify.com" && android.net.Uri.parse(url).scheme == "https")
                main.post {
                    prefs.edit().putString("spotify-handle", data.getString("connection_handle")).putString("spotify-client-id", clientId).apply()
                    spotifyBusy = false; spotifyConnected = false; spotifyMessage = "Finish signing in in your browser, then return to THREAD."
                    open(url)
                }
            } catch (_: Exception) { onFailure(call, IOException()) } } }
        })
    }
    fun disconnectSpotify() {
        disconnect(false)
        val handle = prefs.getString("spotify-handle", null)
        prefs.edit().remove("spotify-handle").apply(); spotifyConnected = false; spotifyMessage = "Disconnected on this phone."
        if (handle != null) http.newCall(Request.Builder().url("$endpoint/api/spotify/connection").header("X-Thread-Spotify", handle).delete().build()).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { main.post { spotifyMessage = "Disconnected on this phone. The task engine could not confirm removal; closing and restarting THREAD clears its Spotify access." } }
            override fun onResponse(call: Call, response: Response) { response.use { if (!it.isSuccessful) onFailure(call, IOException()) } }
        })
    }
    fun sendText(text: String) {
        if (text.isBlank() || text.length > 12000) return
        if (!ui.connected) { connect(false, text); return }
        audio?.typed(); ui = ui.copy(caption = text.trim(), captionRole = "user", mode = "Thinking")
        send(JSONObject().put("type", "text").put("text", text.trim())); keyboard = false
    }
    fun savePhoneKey(remove: Boolean = false) {
        if (phoneKeyBusy) return
        disconnect(false)
        val value = if (remove) "" else phoneKeyDraft
        phoneKeyBusy = true; phoneKeyDraft = ""
        Thread {
            try {
                ThreadBackend.saveKey(getApplication(), value)
                val saved = ThreadBackend.hasKey(getApplication())
                main.post {
                    phoneKeyBusy = false; phoneKeySaved = saved
                    phoneSetupMessage = if (saved) "Key saved privately on this phone. You can start a conversation." else "Key removed from this phone."
                    clearError()
                }
            } catch (_: Exception) { main.post { phoneKeyBusy = false; phoneSetupMessage = "Couldn’t save that key. Enter a valid Gemini API key and try again." } }
        }.start()
    }
    fun filterSports(result: JSONObject, format: String) {
        if(format !in listOf("all","ODI","T20","Test")) return
        val args=JSONObject(result.optJSONObject("arguments")?.toString() ?: "{}").put("cricket_format",format)
        val request=++sportsRequest;sportsLoading=true;sportsError=null
        val module=JSONObject().put("id","profile-"+java.util.UUID.randomUUID()).put("domain","sports").put("arguments",args)
        val body=JSONObject().put("modules",JSONArray().put(module)).toString().toRequestBody(JSON)
        http.newCall(Request.Builder().url("$endpoint/api/widgets/refresh").post(body).build()).enqueue(object:Callback {
            override fun onFailure(call:Call,e:IOException) { main.post { if(request==sportsRequest){sportsLoading=false;sportsError="Couldn’t load $format. Your previous results are still here. Tap a format to retry."} } }
            override fun onResponse(call:Call,response:Response) {
                response.use { try {
                    check(it.isSuccessful);val fresh=JSONObject(it.body!!.string()).getJSONArray("results").getJSONObject(0)
                    check(fresh.optString("status")=="completed")
                    main.post { if(request==sportsRequest){sportsLoading=false;acceptSnapshot(JSONObject().put("workspace",JSONArray().put(fresh)).put("transcript",JSONArray(ui.transcript)));openResult=fresh} }
                }catch(_:Exception){onFailure(call,IOException())} }
            }
        })
    }
    fun sendImage(bytes: ByteArray) {
        if (!ui.connected) { ui = ui.copy(error = "Start a conversation before sharing an image."); return }
        send(JSONObject().put("type", "image").put("data", JSONObject().put("base64", android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)).put("mime", "image/jpeg").put("label", "Image shared from Android")))
    }
    fun queueImage(bytes: ByteArray) { if (ui.connected) sendImage(bytes) else { pendingImage = bytes; connect(false) } }
    fun showError(message: String) { ui = ui.copy(error = message) }
    fun toggleMute() { audio?.let { it.muted = !it.muted; ui = ui.copy(muted = it.muted) } }
    fun enableMic() { microphoneWanted = true; startMicrophoneService(); audio?.enableMic(); ui = ui.copy(muted = false) }
    private fun startMicrophoneService() {
        VoiceService.onEnd = { main.post { disconnect(true) } }
        try { getApplication<Application>().startForegroundService(Intent(getApplication(), VoiceService::class.java)) }
        catch (_: Exception) { ui = ui.copy(error = "Open THREAD and allow the microphone before starting voice.") }
    }
    fun clearError() { ui = ui.copy(error = null) }
    fun disconnect(ended: Boolean = true) {
        ++generation
        actionInputId = ""
        send(JSONObject().put("type", "end")); live?.close(1000, "End conversation"); live = null
        updates?.close(1000, "End conversation"); updates = null
        audio?.close(); audio = null
        if (microphoneWanted) { getApplication<Application>().stopService(Intent(getApplication(), VoiceService::class.java)); VoiceService.onEnd = null; microphoneWanted = false }
        ui = ui.copy(connecting = false, connected = false, ended = ended, mode = "Ready", level = 0f)
        if (started > 0) save()
    }
    fun newConversation() { disconnect(false); sessionId = null; ui = ui.copy(caption = "", transcript = emptyList(), error = null, task = null, changedSlots = emptySet(), taskNotice = "", activeAction = null); route = "voice" }
    private fun fail(current: Int, message: String) { main.post { if (current == generation) { disconnect(false); ui = ui.copy(error = message) } } }
    override fun onCleared() { sportsRequest++; disconnect(false); main.removeCallbacksAndMessages(null); http.dispatcher.executorService.shutdown(); super.onCleared() }
    companion object {
        val JSON = "application/json; charset=utf-8".toMediaType()
        fun rows(array: JSONArray?): List<JSONObject> = if (array == null) emptyList() else (0 until array.length()).mapNotNull { array.optJSONObject(it) }
    }
}
