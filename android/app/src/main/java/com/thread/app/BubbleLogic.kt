package com.thread.app

import kotlin.math.hypot

/** Coordinates are physical pixels in the safe display rectangle, never under system bars. */
data class BubbleBounds(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    fun clamp(x: Int, y: Int, size: Int): BubblePoint = BubblePoint(
        x.coerceIn(left, maxOf(left, right - size)), y.coerceIn(top, maxOf(top, bottom - size)))
    fun snap(x: Int, y: Int, size: Int): BubblePoint {
        val point = clamp(x, y, size)
        val edge = if (point.x + size / 2 <= (left + right) / 2) left else maxOf(left, right - size)
        return point.copy(x = edge)
    }
    fun dismissTarget(size: Int) = clamp((left + right - size) / 2, bottom - size, size)
}
data class BubblePoint(val x: Int, val y: Int)

fun onDismissTarget(bubble: BubblePoint, target: BubblePoint, size: Int): Boolean =
    hypot((bubble.x - target.x).toDouble(), (bubble.y - target.y).toDouble()) <= size * .8

enum class BubbleTap { OPEN_THREAD, TALK_IN_SESSION, NONE }

object BubblePermissionGate {
    fun canShow(optedIn: Boolean, overlayGranted: Boolean, notificationGranted: Boolean) =
        optedIn && overlayGranted && notificationGranted

    // Overlay permission is NOT a while-in-use microphone exemption on Android 14+.
    fun tap(consent: Boolean, microphoneGranted: Boolean, microphoneServiceReady: Boolean,
            connected: Boolean, connecting: Boolean): BubbleTap = when {
        !consent || !microphoneGranted -> BubbleTap.OPEN_THREAD
        connected && microphoneServiceReady -> BubbleTap.TALK_IN_SESSION
        connecting && microphoneServiceReady -> BubbleTap.NONE
        else -> BubbleTap.OPEN_THREAD
    }
}

/** Seed with the current receipt: reopening the overlay must not celebrate historical results. */
class BubbleFeedback(private var receipt: String?, private var listening: Boolean) {
    data class Change(val tick: Boolean, val confirm: Boolean)
    fun update(isListening: Boolean, receiptId: String?, enabled: Boolean): Change {
        val change = Change(enabled && isListening && !listening, enabled && receiptId != null && receiptId != receipt)
        listening = isListening
        receipt = receiptId
        return change
    }
}
