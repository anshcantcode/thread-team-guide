package com.thread.app

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder

/** Foreground lifetime of the ONE shared ThreadModel microphone, never a second recorder. */
class VoiceService : Service() {
    private val model get() = ThreadApplication.model(this)
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "end") { model.disconnect(); stopSelf(); return START_NOT_STICKY }
        if (!model.microphoneRequested) { stopSelf(); return START_NOT_STICKY }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("voice", "Voice conversation", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val end = PendingIntent.getService(this, 1, Intent(this, VoiceService::class.java).setAction("end"), PendingIntent.FLAG_IMMUTABLE)
        try {
            startForeground(10, Notification.Builder(this, "voice").setSmallIcon(R.drawable.ic_thread).setContentTitle("THREAD voice session")
                .setContentText("Microphone session active ? tap to open THREAD").setContentIntent(open).setOngoing(true)
                .addAction(Notification.Action.Builder(null, "End conversation", end).build()).build(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
            // Only now may ThreadModel open its sockets and enable capture.
            model.microphoneServiceStarted()
        } catch (_: RuntimeException) { model.microphoneServiceFailed(); stopSelf() }
        return START_NOT_STICKY
    }
    override fun onDestroy() { model.microphoneServiceStopped(); super.onDestroy() }
}
