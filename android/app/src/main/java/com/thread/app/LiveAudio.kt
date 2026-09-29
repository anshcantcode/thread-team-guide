package com.thread.app

import android.content.Context
import android.media.*
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.SystemClock
import android.util.Base64
import org.json.JSONObject
import java.util.concurrent.ConcurrentLinkedQueue
import kotlin.concurrent.thread
import kotlin.math.sqrt

/** Continuous PCM. Pausing retains AudioTrack's unheard buffer until actual words arrive. */
class LiveAudio(private val context: Context, private val send: (JSONObject) -> Unit,
                private val pcm: (ByteArray) -> Unit, private val state: (String, Float) -> Unit,
                private val error: (String) -> Unit) {
    data class Chunk(val id: String, val bytes: ByteArray, val level: Float, var offset: Int = 0)
    private val lock = Any()
    private val queue = ConcurrentLinkedQueue<Chunk>()
    private val blocked = mutableSetOf<String>()
    private val completed = mutableSetOf<String>()
    private var track: AudioTrack? = null
    private var record: AudioRecord? = null
    private var echo: AcousticEchoCanceler? = null
    private var noise: NoiseSuppressor? = null
    private var ack: MediaPlayer? = null
    private var capture: Thread? = null
    private var output: Thread? = null
    @Volatile private var running = false
    @Volatile var muted = false
    @Volatile var speaking = false
        private set
    @Volatile private var pausedId: String? = null
    @Volatile private var currentId: String? = null
    private var writtenFrames = 0L
    private var lastQuiet = 0L
    private var lastSpeech = 0L
    private var nextRecovery = 0L
    private var recoveryRetries = 0
    private var continuation: String? = null
    private var ackUntil = 0L
    private var lastAck = -6000L
    var acknowledgments = true
    var voice = "Kore"
    private val audioManager = context.getSystemService(AudioManager::class.java)
    private var focus: AudioFocusRequest? = null
    private var previousMode = AudioManager.MODE_NORMAL

    fun start(microphone: Boolean) {
        if (running) return
        previousMode = audioManager.mode
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        if (android.os.Build.VERSION.SDK_INT >= 31) {
            val devices = audioManager.availableCommunicationDevices
            val preferred = devices.firstOrNull { it.type in setOf(AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_BLE_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADSET) }
                ?: devices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
            preferred?.let { audioManager.setCommunicationDevice(it) }
        }
        val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
        focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT).setAudioAttributes(attributes)
            .setOnAudioFocusChangeListener { change -> if (change < 0) { muted = true; synchronized(lock) { track?.pause() }; error("Audio paused for another call. End or reconnect when you're ready.") } }.build()
        if (audioManager.requestAudioFocus(focus!!) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            close(); error("Another call is using audio. Try again when it ends."); return
        }
        track = AudioTrack.Builder().setAudioAttributes(attributes).setAudioFormat(AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(24000).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setBufferSizeInBytes(maxOf(4096, AudioTrack.getMinBufferSize(24000, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)))
            .setTransferMode(AudioTrack.MODE_STREAM).build()
        running = true
        track!!.play()
        output = thread(name = "THREAD playback") { outputLoop() }
        if (microphone) enableMic() else muted = true
    }

    @Suppress("MissingPermission")
    fun enableMic() {
        if (!running) return
        if (record != null) { muted = false; return }
        try {
            record = AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_COMMUNICATION)
                .setAudioFormat(AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(16000).setChannelMask(AudioFormat.CHANNEL_IN_MONO).build())
                .setBufferSizeInBytes(maxOf(4096, AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT))).build()
            check(record!!.state == AudioRecord.STATE_INITIALIZED)
            if (AcousticEchoCanceler.isAvailable()) echo = AcousticEchoCanceler.create(record!!.audioSessionId)?.apply { enabled = true }
            if (NoiseSuppressor.isAvailable()) noise = NoiseSuppressor.create(record!!.audioSessionId)?.apply { enabled = true }
            muted = false
            capture = thread(name = "THREAD microphone") {
                val buffer = ByteArray(1024) // 32 ms, never a completed recording.
                state("Preparing microphone", 0f)
                try { NeuralVad(context).use { detector ->
                val gate = SpeechGate()
                if (!running) return@thread
                record!!.startRecording(); state("Ready", 0f)
                while (running && !Thread.currentThread().isInterrupted) {
                    val count = record?.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING) ?: break
                    if (count <= 0) { if (running) error("The microphone stopped. Reconnect to continue."); break }
                    if (count != buffer.size) continue
                    val frame = buffer.copyOf()
                    if (muted) frame.fill(0)
                    var energy = 0.0
                    for (i in frame.indices step 2) { val v = ((frame[i].toInt() and 255) or (frame[i + 1].toInt() shl 8)).toShort() / 32768.0; energy += v * v }
                    val rms = sqrt(energy / (frame.size / 2)).toFloat()
                    val probability = detector.probability(frame)
                    val voiced = probability >= .4f
                    val transition = gate.update(probability)
                    if (voiced) lastSpeech = SystemClock.elapsedRealtime()
                    if (transition == 1) {
                        speaking = true
                        synchronized(lock) { pause(currentId) }
                        send(JSONObject().put("type", "speech_start").put("message_id", pausedId))
                    }
                    if (transition == -1) {
                        speaking = false; lastQuiet = SystemClock.elapsedRealtime()
                        send(JSONObject().put("type", "speech_end")); nextRecovery = lastQuiet + 1250
                        state("Thinking", 0f)
                    }
                    if (speaking) state("Listening", (rms * 9).coerceIn(0f, 1f))
                    pcm(frame)
                }
                } } catch (failure: Exception) {
                    if (running) { muted = true; speaking = false; send(JSONObject().put("type", "speech_end")); error("The microphone needs to reconnect. Your results are saved.") }
                }
            }
        } catch (_: Exception) { muted = true; error("Microphone permission is needed. You can still type.") }
    }

    private fun outputLoop() {
        var announced: String? = null
        while (running && !Thread.currentThread().isInterrupted) {
            val now = SystemClock.elapsedRealtime()
            synchronized(lock) {
                if (pausedId != null && !speaking && now >= nextRecovery && now - lastQuiet >= 1100 && recoveryRetries < 20) {
                    send(JSONObject().put("type", "resume_after_noise").put("message_id", pausedId)); nextRecovery = now + 900; recoveryRetries++
                }
                if (pausedId == null && !speaking && now > ackUntil) {
                    val item = queue.peek()
                    if (item != null) {
                        if (item.id in blocked) queue.poll()
                        else {
                            currentId = item.id
                            if (announced != item.id) {
                                announced = item.id; playback(item.id, "playing")
                                if (lastSpeech > 0) { send(JSONObject().put("type", "latency").put("value_ms", (now - lastSpeech).coerceIn(0, 60000))); lastSpeech = 0 }
                            }
                            val count = minOf(960, item.bytes.size - item.offset)
                            val wrote = track?.write(item.bytes, item.offset, count, AudioTrack.WRITE_NON_BLOCKING) ?: 0
                            if (wrote > 0) { item.offset += wrote; writtenFrames += wrote / 2; state("Speaking", item.level) }
                            if (item.offset >= item.bytes.size) queue.poll()
                        }
                    } else if (currentId != null && (track?.playbackHeadPosition?.toLong()?.and(0xffffffffL) ?: 0) >= writtenFrames) {
                        val id = currentId!!
                        if (id in completed || continuation == id) {
                            playback(id, "played"); currentId = null; announced = null
                            state(if (speaking) "Listening" else "Ready", 0f)
                            if (continuation == id) { continuation = null; send(JSONObject().put("type", "continue_after_noise").put("message_id", id)) }
                        }
                    }
                }
            }
            try { Thread.sleep(10) } catch (_: InterruptedException) { break }
        }
    }

    fun event(event: JSONObject) = synchronized(lock) {
        val id = event.optString("message_id")
        when (event.optString("type")) {
            "audio" -> {
                if (id !in blocked && event.optInt("sample_rate") == 24000) {
                    val bytes = try { Base64.decode(event.getString("data"), Base64.NO_WRAP) } catch (_: Exception) { return@synchronized }
                    if (bytes.isNotEmpty() && bytes.size % 2 == 0 && queue.sumOf { it.bytes.size } + bytes.size < 4_000_000) {
                        var energy = 0.0
                        for (i in bytes.indices step 2) { val sample = ((bytes[i].toInt() and 255) or (bytes[i + 1].toInt() shl 8)).toShort() / 32768.0; energy += sample * sample }
                        queue.add(Chunk(id, bytes, (sqrt(energy / (bytes.size / 2)) * 7).toFloat().coerceIn(0f, 1f)))
                    }
                    else error("Audio playback fell behind. Reconnect to continue.")
                }
            }
            "interrupted" -> if (event.optBoolean("recoverable")) { pause(id); lastQuiet = SystemClock.elapsedRealtime(); nextRecovery = lastQuiet + 1800 } else discard(false)
            "caption" -> if (event.optString("role") == "user" && hasWords(event.optString("text"))) discard(true)
            "resume_after_noise" -> if (pausedId == id) {
                pausedId = null; track?.play(); recoveryRetries = 0
                if (event.optBoolean("continue_needed")) continuation = id
                playback(id, "resumed")
            }
            "resume_denied" -> if (pausedId == id) discard(false)
            "resume_deferred" -> nextRecovery = SystemClock.elapsedRealtime() + 700
            "turn_complete" -> { completed.add(id); if (completed.size > 64) completed.remove(completed.first()) }
            "silenced" -> {
                currentId?.let(blocked::add); pausedId?.let(blocked::add); queue.forEach { blocked.add(it.id) }
                queue.clear(); track?.pause(); track?.flush(); writtenFrames = 0; track?.play()
                currentId = null; pausedId = null; continuation = null; state("Ready", 0f)
            }
        }
    }

    private fun pause(id: String?) {
        if (pausedId != null || id.isNullOrEmpty() || id in blocked) return
        pausedId = id; track?.pause(); recoveryRetries = 0; continuation = null
        playback(id, "paused")
    }

    fun typed() = synchronized(lock) { pause(currentId); discard(false) }

    private fun discard(withAck: Boolean) {
        val id = pausedId ?: return
        blocked.add(id); if (blocked.size > 64) blocked.remove(blocked.first())
        track?.pause(); track?.flush(); writtenFrames = 0
        queue.removeIf { it.id == id }; pausedId = null; currentId = null; continuation = null
        playback(id, "interrupted"); track?.play()
        val now = SystemClock.elapsedRealtime()
        if (withAck && acknowledgments && now - lastAck >= 6000) {
            lastAck = now; ackUntil = now + 650
            try {
                ack?.release()
                val asset = context.assets.openFd("ack-$voice.wav")
                ack = MediaPlayer().apply {
                    setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    setDataSource(asset.fileDescriptor, asset.startOffset, asset.length); setVolume(.18f, .18f); prepare(); start()
                    setOnCompletionListener { it.release(); if (ack === it) ack = null }
                }
                asset.close()
            } catch (_: Exception) { /* Backchannel absence never blocks the actual conversation. */ }
        }
    }

    private fun playback(id: String, status: String) = send(JSONObject().put("type", "playback").put("message_id", id).put("status", status))

    fun close() {
        running = false
        capture?.interrupt(); output?.interrupt()
        try { record?.stop() } catch (_: Exception) { }
        capture?.join(350); output?.join(350)
        synchronized(lock) {
            record?.release(); record = null; echo?.release(); noise?.release()
            try { track?.pause(); track?.flush(); track?.release() } catch (_: Exception) { }
            track = null; ack?.release(); ack = null; queue.clear()
            pausedId = null; currentId = null; speaking = false; writtenFrames = 0
        }
        focus?.let { audioManager.abandonAudioFocusRequest(it) }; focus = null
        if (android.os.Build.VERSION.SDK_INT >= 31) audioManager.clearCommunicationDevice()
        audioManager.mode = previousMode
    }

    companion object {
        fun hasWords(text: String) = text.replace(Regex("\\[(noise|silence|cough|inaudible|unintelligible|music|breathing)[^]]*]", RegexOption.IGNORE_CASE), "").any { it.isLetterOrDigit() }
    }
}
