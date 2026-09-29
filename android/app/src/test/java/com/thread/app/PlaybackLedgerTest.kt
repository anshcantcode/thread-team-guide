package com.thread.app

import org.junit.Assert.assertEquals
import org.junit.Test

class PlaybackLedgerTest {
    @Test fun queuedSamplesAreNotHeardUntilThePlaybackHeadPassesThem() {
        val ledger = PlaybackLedger()
        ledger.written("reply", 0, 24000)
        assertEquals(0L, ledger.heard("reply", 0))
        assertEquals(6000L, ledger.heard("reply", 6000))
        assertEquals(24000L, ledger.heard("reply", 48000))
    }
    @Test fun interleavedMessagesDoNotCountEachOthersSamples() {
        val ledger = PlaybackLedger()
        ledger.written("first", 0, 100)
        ledger.written("second", 100, 300)
        ledger.written("first", 300, 400)
        assertEquals(150L, ledger.heard("first", 350))
        assertEquals(200L, ledger.heard("second", 350))
    }
    @Test fun flushRetainsOnlyHeardSamplesAndUsesTheNewPlaybackHead() {
        val ledger = PlaybackLedger()
        ledger.written("reply", 0, 100)
        ledger.flush(40)
        ledger.written("reply", 0, 60)
        assertEquals(40L, ledger.heard("reply", 0))
        assertEquals(70L, ledger.heard("reply", 30))
        ledger.flush(30)
        ledger.flush(0)
        assertEquals(70L, ledger.heard("reply", 0))
    }
    @Test fun adjacentPacketsCombineWithoutCountingUndeliveredAudio() {
        val ledger = PlaybackLedger()
        ledger.written("reply", 0, 30)
        ledger.written("reply", 30, 80)
        assertEquals(55L, ledger.heard("reply", 55))
        assertEquals(0L, ledger.heard("unknown", 100))
    }
}
