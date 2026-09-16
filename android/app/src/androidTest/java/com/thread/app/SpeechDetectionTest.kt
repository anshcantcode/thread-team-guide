package com.thread.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.sin
import kotlin.random.Random

/** Exercises the shipped ONNX model on the phone; fixtures never use its microphone. */
@RunWith(AndroidJUnit4::class)
class SpeechDetectionTest {
    @Test fun loudSteadyNoiseAndClicksDoNotHoldTheConversationFloor() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val random = Random(905)
        for (kind in listOf("silence", "fan", "hiss", "clicks")) {
            NeuralVad(context).use { detector ->
                val gate = SpeechGate()
                var starts = 0
                repeat(320) { frameIndex ->
                    val frame = ByteArray(1024)
                    repeat(512) { sampleIndex ->
                        val n = frameIndex * 512 + sampleIndex
                        val value = when (kind) {
                            "fan" -> .10 * sin(n * 2.0 * Math.PI * 120 / 16000) + .04 * sin(n * 2.0 * Math.PI * 240 / 16000) + random.nextDouble(-.015, .015)
                            "hiss" -> random.nextDouble(-.10, .10)
                            "clicks" -> if (frameIndex % 12 == 0 && sampleIndex < 70) random.nextDouble(-.4, .4) else 0.0
                            else -> 0.0
                        }
                        val pcm = (value * 32767).toInt()
                        frame[sampleIndex * 2] = pcm.toByte(); frame[sampleIndex * 2 + 1] = (pcm shr 8).toByte()
                    }
                    if (gate.update(detector.probability(frame)) == 1) starts++
                }
                assertEquals("$kind must not create repeated false interruptions", 0, starts)
                assertFalse(gate.speaking)
            }
        }
    }

    @Test fun speechIsDetectedAndTheFloorReleasesAfterSilence() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val fixture = instrumentation.context.assets.open("speech-fixture.pcm").use { it.readBytes() }
        NeuralVad(instrumentation.targetContext).use { detector ->
            val gate = SpeechGate()
            var starts = 0
            var speechFrames = 0
            val start = android.os.SystemClock.elapsedRealtimeNanos()
            for (offset in 0 until fixture.size - 1023 step 1024) {
                if (gate.update(detector.probability(fixture.copyOfRange(offset, offset + 1024))) == 1) starts++
                if (gate.speaking) speechFrames++
            }
            repeat(32) { gate.update(detector.probability(ByteArray(1024))) }
            val ms = (android.os.SystemClock.elapsedRealtimeNanos() - start) / 1_000_000
            assertTrue("The actual synthetic spoken sentence must be detected", starts > 0 && speechFrames >= 10)
            assertFalse("A quiet microphone releases the floor", gate.speaking)
            assertTrue("Local processing must be faster than real time on the target phone", ms < fixture.size / 32)
        }
    }

    @Test fun aBriefSpikeDoesNotInterruptButSustainedSpeechDoes() {
        val gate = SpeechGate()
        assertEquals(0, gate.update(.95f))
        repeat(8) { assertEquals(0, gate.update(.01f)) }
        assertFalse(gate.speaking)
        repeat(2) { assertEquals(0, gate.update(.95f)) }
        assertEquals(1, gate.update(.95f))
        repeat(8) { assertEquals(0, gate.update(.2f)) }
        assertTrue(gate.speaking)
        repeat(4) { gate.update(.01f) }
        assertEquals(-1, gate.update(.01f))
    }
}
