package com.thread.app

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.hardware.camera2.*
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import java.io.ByteArrayOutputStream

/** Foreground-only rear camera. Capture/encode one small JPEG at a time; never save to disk. */
class LiveCamera(context: Context, private val model: ThreadModel, private val rotation: Int,
                 private val failed: () -> Unit) : AutoCloseable {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("THREAD camera").apply { start() }
    private val handler = Handler(thread.looper)
    @Volatile private var stopped = false
    private var camera: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private var ticket: CameraFrameGate.Ticket? = null
    private var orientation = 0
    private val timeout = Runnable { error() }

    @SuppressLint("MissingPermission") // Activity requests permission immediately before starting.
    fun start() { handler.post {
        if (stopped) return@post
        try {
            val id = manager.cameraIdList.firstOrNull {
                manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
            } ?: throw IllegalStateException("No rear camera")
            val characteristics = manager.getCameraCharacteristics(id)
            orientation = ((characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0) - rotation + 360) % 360
            val size = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)!!
                .getOutputSizes(ImageFormat.JPEG).filter { maxOf(it.width, it.height) <= 768 }
                .maxByOrNull { it.width * it.height } ?: throw IllegalStateException("No bounded capture size")
            reader = ImageReader.newInstance(size.width, size.height, ImageFormat.JPEG, 2).also { output ->
                output.setOnImageAvailableListener({ source ->
                    try {
                        val bytes = source.acquireLatestImage()?.use { image ->
                            ByteArray(image.planes[0].buffer.remaining()).also { image.planes[0].buffer.get(it) }
                        } ?: return@setOnImageAvailableListener
                        handler.removeCallbacks(timeout)
                        val captured = ticket; ticket = null
                        if (!stopped && captured != null) {
                            val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: throw IllegalStateException("Unreadable frame")
                            val upright = if (orientation == 0) bitmap else Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height,
                                Matrix().apply { postRotate(orientation.toFloat()) }, true).also { bitmap.recycle() }
                            val buffer = ByteArrayOutputStream()
                            upright.compress(Bitmap.CompressFormat.JPEG, 65, buffer)
                            model.sendCameraFrame(captured, buffer.toByteArray(), upright)
                        }
                        if (!stopped) handler.postDelayed(::capture, 1000)
                    } catch (_: Exception) { error() }
                }, handler)
            }
            handler.postDelayed(timeout, 5000)
            manager.openCamera(id, object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    if (stopped) { device.close(); return }
                    camera = device
                    try {
                        @Suppress("DEPRECATION")
                        device.createCaptureSession(listOf(reader!!.surface), object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(value: CameraCaptureSession) {
                                if (stopped) { value.close(); return }
                                handler.removeCallbacks(timeout); session = value; capture()
                            }
                            override fun onConfigureFailed(value: CameraCaptureSession) { value.close(); error() }
                        }, handler)
                    } catch (_: Exception) { error() }
                }
                override fun onDisconnected(device: CameraDevice) { device.close(); error() }
                override fun onError(device: CameraDevice, code: Int) { device.close(); error() }
            }, handler)
        } catch (_: Exception) { error() }
    } }

    private fun capture() {
        if (stopped) return
        val owned = model.cameraTicket()
        if (owned == null) { handler.postDelayed(::capture, 250); return }
        try {
            ticket = owned
            val request = camera!!.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                addTarget(reader!!.surface)
                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                set(CaptureRequest.JPEG_ORIENTATION, 0)
                set(CaptureRequest.JPEG_QUALITY, 65.toByte())
            }.build()
            handler.postDelayed(timeout, 5000)
            session!!.capture(request, object : CameraCaptureSession.CaptureCallback() {
                override fun onCaptureFailed(session: CameraCaptureSession, request: CaptureRequest, failure: CaptureFailure) = error()
            }, handler)
        } catch (_: Exception) { error() }
    }
    private fun error() { if (!stopped) { close(); failed() } }
    override fun close() {
        if (stopped) return
        stopped = true
        handler.post {
            handler.removeCallbacksAndMessages(null)
            session?.close(); camera?.close(); reader?.close()
            session = null; camera = null; reader = null; ticket = null
            thread.quitSafely()
        }
    }
}
