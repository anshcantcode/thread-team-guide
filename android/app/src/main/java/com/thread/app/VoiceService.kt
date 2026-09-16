package com.thread.app

import android.app.*
import android.content.Intent
import android.os.IBinder

class VoiceService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "end") { onEnd?.invoke(); stopSelf(); return START_NOT_STICKY }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("voice", "Voice conversation", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val end = PendingIntent.getService(this, 1, Intent(this, VoiceService::class.java).setAction("end"), PendingIntent.FLAG_IMMUTABLE)
        startForeground(10, Notification.Builder(this, "voice").setSmallIcon(R.drawable.ic_thread).setContentTitle("THREAD is connected")
            .setContentText("Your voice conversation is active").setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, "End conversation", end).build()).build())
        return START_NOT_STICKY
    }
    override fun onDestroy() { super.onDestroy() }
    companion object { var onEnd: (() -> Unit)? = null }
}
