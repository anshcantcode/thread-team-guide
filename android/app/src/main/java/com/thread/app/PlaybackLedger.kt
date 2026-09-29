package com.thread.app

/** Counts only each message's samples which the AudioTrack playback head has passed. */
internal class PlaybackLedger {
    private val spans = mutableMapOf<String, MutableList<Pair<Long, Long>>>()
    private val retained = linkedMapOf<String, Long>()

    fun written(id: String, start: Long, end: Long) {
        require(start >= 0 && end >= start)
        val rows = spans.getOrPut(id) { mutableListOf() }
        val previous = rows.lastOrNull()
        if (previous?.second == start) rows[rows.lastIndex] = previous.first to end
        else rows.add(start to end)
    }

    fun heard(id: String, head: Long): Long = (retained[id] ?: 0L) +
        (spans[id]?.sumOf { (start, end) -> (head.coerceAtMost(end) - start).coerceAtLeast(0L) } ?: 0L)

    fun flush(head: Long) {
        for (id in spans.keys) retained[id] = heard(id, head)
        spans.clear()
        while (retained.size > 64) retained.remove(retained.keys.first())
    }
}
