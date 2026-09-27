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

    static final String WARNINGS = "warnings";
    static final String NOWCAST = "nowcast";
    static final String BRIEFING = "briefing";
    static final String ALERTS = "alerts";

    @Override
    public void onMessageReceived(@NonNull RemoteMessage remoteMessage) {
        super.onMessageReceived(remoteMessage);
        Map<String, String> data = remoteMessage.getData();
        if (data.get("title") == null || remoteMessage.getNotification() != null) {
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

    static void ensureChannels(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }
        channel(manager, WARNINGS, "Weather warnings", "Official IMD and NDMA warnings for your saved places", NotificationManager.IMPORTANCE_HIGH);
        channel(manager, NOWCAST, "Rain and storm nowcast", "Rain or thunderstorms starting soon where you are", NotificationManager.IMPORTANCE_HIGH);
        channel(manager, ALERTS, "Weather alerts", "Heat, heavy rain, strong wind and fog ahead", NotificationManager.IMPORTANCE_DEFAULT);
        channel(manager, BRIEFING, "Morning briefing", "Your daily weather summary", NotificationManager.IMPORTANCE_LOW);
    }

    private static void channel(NotificationManager manager, String id, String name, String description, int importance) {
        if (manager.getNotificationChannel(id) != null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(id, name, importance);
        channel.setDescription(description);
        channel.setLightColor(0xFFFF9933);
        channel.enableLights(importance >= NotificationManager.IMPORTANCE_HIGH);
        channel.enableVibration(importance >= NotificationManager.IMPORTANCE_HIGH);
        manager.createNotificationChannel(channel);
    }

    private static PendingIntent open(Context context, String messageId, Map<String, String> data, String action, int requestCode) {
        Intent intent = new Intent(context, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        intent.putExtra("google.message_id", messageId);
        for (Map.Entry<String, String> entry : data.entrySet()) {
            intent.putExtra(entry.getKey(), entry.getValue());
        }
        intent.putExtra("action", action);
        return PendingIntent.getActivity(context, requestCode, intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    static void show(Context context, String messageId, Map<String, String> data) {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
            return;
        }
        ensureChannels(context);
        String alertId = data.get("alert_id");
        String noticeId = data.get("notice_id");
        String key = alertId != null ? alertId : "notice:" + (noticeId != null ? noticeId : String.valueOf(System.currentTimeMillis()));
        int id = notificationId(key);
        String message = messageId != null ? messageId : key;
        String kind = data.containsKey("kind") ? data.get("kind") : "alert";
        String channel = data.containsKey("channel") ? data.get("channel") : WARNINGS;
        String severity = data.get("severity");
        boolean urgent = "Extreme".equals(severity) || "Severe".equals(severity);
        String body = data.containsKey("body") ? data.get("body") : "";

        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_stat_weathergpt)
            .setColor(ContextCompat.getColor(context, R.color.weathergpt_saffron))
            .setLargeIcon(BitmapFactory.decodeResource(context.getResources(), R.drawable.weathergpt_notification_large))
            .setContentTitle(data.get("title"))
            .setContentText(body)
            .setSubText(data.get("place"))
            .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
            .setCategory(BRIEFING.equals(channel) ? NotificationCompat.CATEGORY_RECOMMENDATION : NotificationCompat.CATEGORY_ALARM)
            .setPriority(urgent ? NotificationCompat.PRIORITY_MAX : BRIEFING.equals(channel) ? NotificationCompat.PRIORITY_LOW : NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(true)
            .setContentIntent(open(context, message, data, "open", id))
            .addAction(0, "Ask WeatherGPT", open(context, message, data, "ask", id + 1));
        if ("rain_soon".equals(kind) || "storm".equals(kind)) {
            builder.addAction(0, "Radar", open(context, message, data, "radar", id + 2));
        }
        try {
            NotificationManagerCompat.from(context).notify(id, builder.build());
        } catch (SecurityException ignored) {
        }
    }
}
