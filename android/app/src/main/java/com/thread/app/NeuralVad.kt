package com.thread.app

import android.content.Context
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer
import java.nio.LongBuffer

/** Silero v6.2.1, 16 kHz: 512 new samples + 64 context samples and recurrent state.
 * Runs only on the capture thread. No recording or network is needed for this detector. */
class NeuralVad(context: Context) : AutoCloseable {
    private val environment = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    private val samples = FloatArray(576)
    private val memory = FloatArray(256)
    private val rate = OnnxTensor.createTensor(environment, LongBuffer.wrap(longArrayOf(16000)), longArrayOf())
    init {
        OrtSession.SessionOptions().use { options ->
            options.setInterOpNumThreads(1); options.setIntraOpNumThreads(1)
            session = environment.createSession(context.assets.open("silero_vad_16k.onnx").use { it.readBytes() }, options)
        }
    }
    fun probability(frame: ByteArray): Float {
        require(frame.size == 1024)
        for (i in 0 until 512) samples[i + 64] = ((frame[i * 2].toInt() and 255) or (frame[i * 2 + 1].toInt() shl 8)).toShort() / 32768f
        val probability = OnnxTensor.createTensor(environment, FloatBuffer.wrap(samples), longArrayOf(1, 576)).use { input ->
            OnnxTensor.createTensor(environment, FloatBuffer.wrap(memory), longArrayOf(2, 1, 128)).use { state ->
                session.run(mapOf("input" to input, "state" to state, "sr" to rate)).use { result ->
                    (result[1] as OnnxTensor).floatBuffer.get(memory)
                    (result[0] as OnnxTensor).floatBuffer.get(0)
                }
            }
        }
        samples.copyInto(samples, 0, 512, 576)
        return probability
    }
    override fun close() { rate.close(); session.close() }
}

/** Hysteresis holds natural short pauses without mistaking energy alone for words. */
class SpeechGate {
    var speaking = false; private set
    private var voicedMs = 0
    private var quietMs = 0
    fun update(probability: Float): Int {
        if (probability >= if (speaking) .40f else .65f) { voicedMs += 32; quietMs = 0 }
        else { voicedMs = 0; quietMs += 32 }
        if (!speaking && voicedMs >= 96) { speaking = true; return 1 }
        if (speaking && quietMs >= 416) { speaking = false; return -1 }
        return 0
    }
}
