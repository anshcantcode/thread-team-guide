package com.thread.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.*
import android.hardware.camera2.*
import android.media.Image
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Size
import android.view.Surface
import android.view.TextureView
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** GPU preview runs continuously; only bounded, independently owned snapshots are encoded. */
internal class CameraRotation(initialDegrees: Int) {
    @Volatile var displayDegrees = normalize(initialDegrees)
        private set

    fun update(degrees: Int): Boolean {
        val next = normalize(degrees)
        if (next == displayDegrees) return false
        displayDegrees = next
        return true
    }

    fun captureDegrees(sensorDegrees: Int): Int = normalize(sensorDegrees - displayDegrees)

    private fun normalize(degrees: Int) = ((degrees % 360) + 360) % 360
}

class LiveCamera(private val context: Context, private val model: ThreadModel, initialRotation: Int,
                 private val failed: () -> Unit) : AutoCloseable {
    val preview = TextureView(context).apply { isOpaque = false; contentDescription = "Live rear-camera preview" }
    private val manager = context.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("THREAD camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val encoder = Executors.newSingleThreadExecutor()
    private val encoding = AtomicBoolean(false)
    @Volatile private var stopped = false
    // Counts actual TextureView updates, not requested camera frames; used by device performance checks.
    @Volatile var previewFrames = 0L; private set
    private var camera: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private var surface: Surface? = null
    private var ticket: CameraFrameGate.Ticket? = null
    private var waitingFrames = 0
    private var pipelineDepth = 8
    private var realtimeTimestamps = false
    private var sensorOrientation = 0
    private val rotation = CameraRotation(initialRotation)
    @Volatile private var orientation = 0
    private var previewSize = Size(1280, 960)
    private val timeout = Runnable { error() }

    private fun hasCameraPermission() = context.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    fun start() {
        preview.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(texture: SurfaceTexture, width: Int, height: Int) = open(texture)
            override fun onSurfaceTextureSizeChanged(texture: SurfaceTexture, width: Int, height: Int) = transform()
            override fun onSurfaceTextureUpdated(texture: SurfaceTexture) { previewFrames++ }
            override fun onSurfaceTextureDestroyed(texture: SurfaceTexture): Boolean { error(); return true }
        }
        if (preview.isAvailable) open(preview.surfaceTexture!!)
    }

    // TextureView already applies sensor orientation. Undo its stretch, fit, then compensate display rotation.
    private fun transform() {
        val w = preview.width.toFloat(); val h = preview.height.toFloat()
        if (w <= 0 || h <= 0) return
        val naturalW = (if (sensorOrientation % 180 == 0) previewSize.width else previewSize.height).toFloat()
        val naturalH = (if (sensorOrientation % 180 == 0) previewSize.height else previewSize.width).toFloat()
        val displayDegrees = rotation.displayDegrees
        val scale = if (displayDegrees % 180 == 0) minOf(w / naturalW, h / naturalH) else minOf(w / naturalH, h / naturalW)
        preview.setTransform(Matrix().apply {
            setScale(naturalW * scale / w, naturalH * scale / h, w / 2, h / 2)
            postRotate(-displayDegrees.toFloat(), w / 2, h / 2)
        })
    }

    fun updateRotation(degrees: Int) { handler.post {
        if (stopped || !rotation.update(degrees)) return@post
        orientation = rotation.captureDegrees(sensorOrientation)
        preview.post { if (!stopped) transform() }
    } }

    @SuppressLint("MissingPermission") // Activity requests permission immediately before starting.
    private fun open(texture: SurfaceTexture) { handler.post {
        if (stopped) return@post
        try {
            val id = manager.cameraIdList.firstOrNull {
                manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
            } ?: error("No rear camera")
            val characteristics = manager.getCameraCharacteristics(id)
            sensorOrientation = characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0
            orientation = rotation.captureDegrees(sensorOrientation)
            realtimeTimestamps = characteristics.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
            pipelineDepth = (characteristics.get(CameraCharacteristics.REQUEST_PIPELINE_MAX_DEPTH)?.toInt() ?: 8) + 1
            val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)!!
            val sample = map.getOutputSizes(ImageFormat.YUV_420_888).filter { maxOf(it.width, it.height) <= 768 }
                .maxByOrNull { it.width * it.height } ?: error("No bounded sample size")
            previewSize = map.getOutputSizes(SurfaceTexture::class.java).filter {
                maxOf(it.width, it.height) <= 1280 && it.width * sample.height == it.height * sample.width
            }.maxByOrNull { it.width * it.height } ?: sample
            texture.setDefaultBufferSize(previewSize.width, previewSize.height)
            preview.post { if (!stopped) transform() }
            surface = Surface(texture)
            reader = ImageReader.newInstance(sample.width, sample.height, ImageFormat.YUV_420_888, 2).also { output ->
                output.setOnImageAvailableListener({ source ->
                    try { source.acquireLatestImage()?.use { image -> sample(image) } }
                    catch (_: Exception) { error() }
                }, handler)
            }
            handler.postDelayed(timeout, 5000)
            manager.openCamera(id, object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    if (stopped) { device.close(); return }
                    camera = device
                    try {
                        @Suppress("DEPRECATION")
                        device.createCaptureSession(listOf(surface!!, reader!!.surface), object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(value: CameraCaptureSession) {
                                if (stopped) { value.close(); return }
                                session = value
                                try {
                                    val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                                        addTarget(surface!!); addTarget(reader!!.surface)
                                        set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO)
                                        characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
                                            ?.filter { it.upper == 30 }?.maxByOrNull { it.lower }
                                            ?.let { set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, it) }
                                    }.build()
                                    value.setRepeatingRequest(request, null, handler)
                                    handler.removeCallbacks(timeout)
                                } catch (_: Exception) { error() }
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

    private fun sample(image: Image) {
        if (stopped || stopIfCameraPermissionMissing(hasCameraPermission()) { error() } || encoding.get()) return
        val owned = ticket
        if (owned == null) { ticket = model.cameraTicket(); waitingFrames = 0; return }
        // Select an exposure made after ownership was acquired, never a buffered pre-correction frame.
        if (realtimeTimestamps) { if (image.timestamp < owned.captured * 1_000_000) return }
        else if (++waitingFrames < pipelineDepth) return
        ticket = null
        if (SystemClock.elapsedRealtime() - owned.captured > 1500) return
        val w = image.width; val h = image.height
        val imageOrientation = orientation
        val nv21 = ByteArray(w * h * 3 / 2)
        image.planes.forEachIndexed { index, plane ->
            val width = if (index == 0) w else w / 2
            val height = if (index == 0) h else h / 2
            val offset = if (index == 0) 0 else w * h + if (index == 1) 1 else 0
            val stride = if (index == 0) 1 else 2
            val start = plane.buffer.position()
            for (y in 0 until height) for (x in 0 until width)
                nv21[offset + (y * width + x) * stride] = plane.buffer.get(start + y * plane.rowStride + x * plane.pixelStride)
        }
        encoding.set(true)
        encoder.execute {
            try {
                if (!stopped && !stopIfCameraPermissionMissing(hasCameraPermission()) { error() }) {
                    val buffer = ByteArrayOutputStream()
                    YuvImage(nv21, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), 65, buffer)
                    var bytes = buffer.toByteArray()
                    if (imageOrientation != 0) {
                        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                        val upright = Bitmap.createBitmap(bitmap, 0, 0, w, h, Matrix().apply { postRotate(imageOrientation.toFloat()) }, true)
                        buffer.reset(); upright.compress(Bitmap.CompressFormat.JPEG, 65, buffer)
                        bytes = buffer.toByteArray(); upright.recycle(); if (upright !== bitmap) bitmap.recycle()
                    }
                    if (!stopped && !stopIfCameraPermissionMissing(hasCameraPermission()) { error() }) model.sendCameraFrame(owned, bytes)
                }
            } catch (_: Exception) { error() }
            finally { encoding.set(false) }
        }
    }
    private fun error() { if (!stopped) { close(); failed() } }
    override fun close() {
        if (stopped) return
        stopped = true
        handler.post {
            handler.removeCallbacksAndMessages(null)
            session?.close(); camera?.close(); reader?.close(); surface?.release()
            session = null; camera = null; reader = null; surface = null; ticket = null
            encoder.shutdown(); thread.quitSafely()
        }
    }
}
