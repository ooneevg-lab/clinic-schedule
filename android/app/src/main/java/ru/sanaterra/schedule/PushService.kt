package ru.sanaterra.schedule

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/** Прием пушей: показываем шторку, по нажатию открываем URL в WebView. */
class PushService : FirebaseMessagingService() {

    companion object {
        const val CHANNEL_ID = "schedule_ready"
    }

    override fun onNewToken(token: String) {
        // Новый адрес появится у MainActivity при следующем запуске:
        // страница заново отправит его в Django и перепривяжет телефон.
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val title = message.notification?.title ?: "Расписание опубликовано"
        val body = message.notification?.body ?: "Расписание на завтра доступно."
        val url = message.data["url"] ?: "/schedule/"
        showNotification(title, body, url)
    }

    private fun showNotification(title: String, body: String, url: String) {
        ensureChannel()
        val intent = Intent(this, MainActivity::class.java).apply {
            action = "ru.sanaterra.schedule.OPEN_SCHEDULE"
            putExtra(MainActivity.EXTRA_URL, url)
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pending = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(url.hashCode(), notification)
    }

    private fun ensureChannel() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (manager.getNotificationChannel(CHANNEL_ID) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Расписание", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
    }
}
