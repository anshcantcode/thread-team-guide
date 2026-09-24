package com.thread.app

/** One unacknowledged frame, with capture ownership checked again after encoding. */
class CameraFrameGate {
    data class Ticket(val stream: String, val context: String, val input: String, val captured: Long)
    var stream = ""; private set
    private var context = ""
    private var input = ""
    private var pending: Long? = null
    private var sequence = 0L
    private var lastSent = -1000L

    private fun estimatedWireBytes(ticket: Ticket, bytes: Int): Long =
        (bytes.toLong() + 2) / 3 * 4 + 512 +
            6L * (ticket.stream.length.toLong() + ticket.context.length + ticket.input.length)

    fun start(id: String) { stop(); stream = id }
    fun stop() { stream = ""; context = ""; input = ""; pending = null; lastSent = -1000L }
    fun invalidate() { context = "" }
    fun owns(ticket: Ticket): Boolean = stream.isNotEmpty() && context.isNotEmpty() && ticket.stream == stream && ticket.context == context && ticket.input == input
    fun awaiting(streamId: String, seq: Long): Boolean = stream == streamId && pending == seq
    fun context(streamId: String, token: String, inputId: String) {
        if (stream == streamId && stream.isNotEmpty()) { context = token; input = inputId }
    }
    fun capture(now: Long): Ticket? = if (stream.isNotEmpty() && context.isNotEmpty() && pending == null && now - lastSent >= 1000)
        Ticket(stream, context, input, now) else null
    // Leave 32 KB below LiveAudio's 128 KB queue cutoff, including Base64 expansion.
    fun deliver(ticket: Ticket, now: Long, bytes: Int, queued: Long): Long? {
        if (!owns(ticket)
            || pending != null || now - ticket.captured !in 0..1500 || now - lastSent < 1000 || bytes !in 1..131072
            || queued > 32768 || queued > 96000 - estimatedWireBytes(ticket, bytes)) return null
        lastSent = now
        return (++sequence).also { pending = it }
    }
    fun acknowledge(streamId: String, seq: Long) { if (streamId == stream && pending == seq) pending = null }
}
