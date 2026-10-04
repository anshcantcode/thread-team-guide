package com.thread.app

import org.junit.Assert.assertEquals
import org.junit.Test

class ThreadOrbTest {
    private fun phase(connected: Boolean = true, connecting: Boolean = false, muted: Boolean = false, error: Boolean = false,
                      mode: String = "Ready", acting: Boolean = false) = orbPhaseFor(connected, connecting, muted, error, mode, acting)

    @Test fun disconnectedStatesAreIdleOrConnecting() {
        assertEquals(OrbPhase.Idle, phase(connected = false))
        assertEquals(OrbPhase.Connecting, phase(connected = false, connecting = true))
    }

    @Test fun observedModesMapToTheirPhases() {
        assertEquals(OrbPhase.Listening, phase(mode = "Listening"))
        assertEquals(OrbPhase.Listening, phase(mode = "Ready"))
        assertEquals(OrbPhase.Thinking, phase(mode = "Thinking"))
        assertEquals(OrbPhase.Speaking, phase(mode = "Speaking"))
        assertEquals(OrbPhase.Working, phase(mode = "Working on your request…"))
        assertEquals(OrbPhase.Held, phase(mode = "Paused · details kept"))
    }

    @Test fun mutedErrorAndActiveActionTakePrecedenceCorrectly() {
        assertEquals(OrbPhase.Muted, phase(muted = true, mode = "Listening"))
        assertEquals(OrbPhase.Speaking, phase(muted = true, mode = "Speaking"))  // THREAD can still speak while the mic is muted
        assertEquals(OrbPhase.Error, phase(error = true, mode = "Speaking"))
        assertEquals(OrbPhase.Working, phase(acting = true, mode = "Listening"))
    }
}
