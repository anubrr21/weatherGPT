package in.weathergpt.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.BitmapFactory;
import android.os.Build;
import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;
import com.capacitorjs.plugins.pushnotifications.MessagingService;
import com.google.firebase.messaging.RemoteMessage;
import java.util.Map;

public class WeatherMessagingService extends MessagingService {

    static final String CHANNEL = "warnings";

    @Override
    public void onMessageReceived(@NonNull RemoteMessage remoteMessage) {
        super.onMessageReceived(remoteMessage);
        Map<String, String> data = remoteMessage.getData();
        String title = data.get("title");
        if (title == null || remoteMessage.getNotification() != null) {
            return;
        }
        show(this, remoteMessage.getMessageId(), data);
    }

    static int notificationId(String key) {
        int hash = 0;
        for (int i = 0; i < key.length(); ) {
            int codePoint = key.codePointAt(i);
            hash = hash * 31 + codePoint;
            i += Character.charCount(codePoint);
        }
        return (int) (Math.abs((long) hash) % 2_000_000_000L);
    }

    static void ensureChannel(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null || manager.getNotificationChannel(CHANNEL) != null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(CHANNEL, "Weather warnings", NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription("Official IMD and NDMA warnings for your saved places");
        channel.enableLights(true);
        channel.setLightColor(0xFFFF9933);
        channel.enableVibration(true);
        manager.createNotificationChannel(channel);
    }

    static void show(Context context, String messageId, Map<String, String> data) {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
            return;
        }
        ensureChannel(context);
        String key = data.containsKey("alert_id") ? data.get("alert_id") : String.valueOf(System.currentTimeMillis());
        int id = notificationId(key);

        Intent open = new Intent(context, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        open.putExtra("google.message_id", messageId != null ? messageId : key);
        for (Map.Entry<String, String> entry : data.entrySet()) {
            open.putExtra(entry.getKey(), entry.getValue());
        }
        PendingIntent tap = PendingIntent.getActivity(context, id, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        String body = data.containsKey("body") ? data.get("body") : "";
        boolean urgent = "Extreme".equals(data.get("severity")) || "Severe".equals(data.get("severity"));
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_weathergpt)
            .setColor(ContextCompat.getColor(context, R.color.weathergpt_saffron))
            .setLargeIcon(BitmapFactory.decodeResource(context.getResources(), R.drawable.weathergpt_notification_large))
            .setContentTitle(data.get("title"))
            .setContentText(body)
            .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(urgent ? NotificationCompat.PRIORITY_MAX : NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(true)
            .setContentIntent(tap);
        try {
            NotificationManagerCompat.from(context).notify(id, builder.build());
        } catch (SecurityException ignored) {
        }
    }
}
