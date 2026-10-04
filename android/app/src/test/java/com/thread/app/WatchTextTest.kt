package com.thread.app

import org.junit.Assert.assertEquals
import org.junit.Test

class WatchTextTest {
    @Test fun cadenceMatchesTheBrowserWording() {
        assertEquals("every 2 h", watchCadence(120))
        assertEquals("hourly", watchCadence(60))
        assertEquals("every 15 min", watchCadence(15))
        assertEquals("daily", watchCadence(1440))
        assertEquals("every 2 days", watchCadence(2880))
        assertEquals("", watchCadence(0))
    }

    @Test fun relativeTimesAreApproximateAndNeverInvented() {
        val now = 1_800_000_000_000L
        assertEquals("in ~30 min", watchRelative(now + 30 * 60000, now))
        assertEquals("2 h ago", watchRelative(now - 2 * 3600000, now))
        assertEquals("just now", watchRelative(now, now))
        assertEquals("", watchRelative(0, now))
        assertEquals("3 d ago", watchRelative(now - 3 * 86400000L, now))
    }

    @Test fun headlineDropsOnlyTheRepeatedSource() {
        assertEquals("City appeal delayed", watchHeadline("City appeal delayed - Manchester Evening News", "Manchester Evening News"))
        assertEquals("Title only", watchHeadline("Title only", "BBC"))
        assertEquals(" - BBC", watchHeadline(" - BBC", "BBC"))
    }
}
