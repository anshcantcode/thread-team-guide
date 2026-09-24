package com.thread.app

import org.junit.Assert.*
import org.junit.Test

class CameraFrameGateTest {
    private fun gate() = CameraFrameGate().apply { start("stream"); context("stream", "turn-1", "input-1") }

    @Test fun oneFrameUntilMatchingAcknowledgmentAndRateLimit() {
        val gate = gate()
        val frame = gate.capture(1000)!!
        val seq = gate.deliver(frame, 1000, 10000, 0)!!
        assertNull(gate.capture(3000))
        gate.acknowledge("old-stream", seq)
        gate.acknowledge("stream", seq + 1)
        assertNull(gate.capture(3000))
        gate.acknowledge("stream", seq)
        assertNull(gate.capture(1999))
        assertNotNull(gate.capture(2000))
    }

    @Test fun stopAndRestartCannotDeliverCapturedOrQueuedOldFrame() {
        val gate = gate()
        val old = gate.capture(1000)!!
        gate.stop()
        assertNull(gate.capture(2000))
        assertNull(gate.deliver(old, 1100, 10000, 0))
        gate.start("new-stream"); gate.context("new-stream", "turn-2", "input-2")
        assertNull(gate.deliver(old, 1100, 10000, 0))
        val seq = gate.deliver(gate.capture(2000)!!, 2000, 10000, 0)!!
        gate.acknowledge("stream", seq)
        assertNull(gate.capture(3000))
    }

    @Test fun correctionAndInterruptionInvalidateEncodingInProgress() {
        val gate = gate()
        val old = gate.capture(1000)!!
        gate.invalidate()
        assertNull(gate.capture(1100))
        assertNull(gate.deliver(old, 1100, 10000, 0))
        gate.context("stream", "turn-2", "input-2")
        assertNull(gate.deliver(old, 1100, 10000, 0))
        val current = gate.capture(1200)!!
        gate.context("stream", "provider-interrupt", "input-2")
        assertNull(gate.deliver(current, 1300, 10000, 0))
        assertNotNull(gate.deliver(gate.capture(1400)!!, 1400, 10000, 0))
    }

    @Test fun agePayloadAndSocketBacklogAreBoundedWithoutRetainingFrames() {
        val gate = gate()
        val old = gate.capture(1000)!!
        assertNull(gate.deliver(old, 2501, 10000, 0))
        assertNull(gate.deliver(old, 999, 10000, 0))
        assertNull(gate.deliver(old, 1100, 131073, 0))
        assertNull(gate.deliver(old, 1100, 10000, 32769))
        assertNotNull(gate.deliver(gate.capture(3000)!!, 3000, 131072, 32768))
    }
}
