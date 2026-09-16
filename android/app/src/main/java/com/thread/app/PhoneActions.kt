package com.thread.app

import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.provider.AlarmClock
import android.provider.CalendarContract
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject
import java.time.OffsetDateTime

/** Only these typed actions cross the model/device boundary. No arbitrary intent URIs or shell. */
class PhoneActions(private val activity: Activity, private val widgetPreview: (JSONObject) -> Unit) {
    private val prefs = activity.getSharedPreferences("phone-actions", 0)

    fun execute(request: JSONObject): JSONObject {
        val id = request.optString("request_id")
        if (!id.startsWith("phone-") || id.length > 180) return outcome("failed", "Invalid action reference.")
        prefs.getString(id, null)?.let { return JSONObject(it) }
        val action = request.optString("action")
        val args = request.optJSONObject("arguments") ?: JSONObject()
        val result = try {
            when (action) {
                "set_alarm" -> {
                    val hour = int(args, "hour", 0, 23); val minute = int(args, "minute", 0, 59); val label = text(args, "label", 120)
                    val days = args.optJSONArray("days") ?: JSONArray()
                    require(days.length() <= 7)
                    val repeat = ArrayList<Int>()
                    for (i in 0 until days.length()) { val day = days.getInt(i); require(day in 1..7 && day !in repeat); repeat.add(day) }
                    val intent = Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, hour).putExtra(AlarmClock.EXTRA_MINUTES, minute)
                        .putExtra(AlarmClock.EXTRA_MESSAGE, label).putExtra(AlarmClock.EXTRA_SKIP_UI, true)
                    if (repeat.isNotEmpty()) intent.putIntegerArrayListExtra(AlarmClock.EXTRA_DAYS, repeat)
                    handoff(intent, "Sent ${"%02d:%02d".format(hour, minute)} · $label to Clock. Check Clock to review or change it.")
                }
                "set_timer" -> handoff(Intent(AlarmClock.ACTION_SET_TIMER).putExtra(AlarmClock.EXTRA_LENGTH, int(args, "seconds", 1, 86400))
                    .putExtra(AlarmClock.EXTRA_MESSAGE, text(args, "label", 120)).putExtra(AlarmClock.EXTRA_SKIP_UI, true), "Timer request accepted by Clock. Clock handles the countdown and ringing.")
                "show_alarms" -> handoff(Intent(AlarmClock.ACTION_SHOW_ALARMS), "Opened the phone's alarms.")
                "web_search" -> {
                    val query = text(args, "query", 500); val tab = text(args, "tab", 20)
                    val uri = searchUri("google", query, tab)
                    handoff(Intent(Intent.ACTION_VIEW, uri), "Opened Google $tab results for $query. The browser handles loading.")
                        .put("title", "Google · $query").put("query", query).put("tab", tab).put("url", uri.toString())
                }
                "media_search" -> {
                    val query = text(args, "query", 500); val provider = text(args, "provider", 20)
                    require(provider in listOf("youtube", "spotify"))
                    val uri = searchUri(provider, query)
                    val appUri = if (provider == "spotify") Uri.parse("spotify:search:" + Uri.encode(query)) else uri
                    val preferred = Intent(Intent.ACTION_VIEW, appUri).setPackage(if (provider == "spotify") "com.spotify.music" else "com.google.android.youtube")
                    val intent = if (preferred.resolveActivity(activity.packageManager) != null) preferred else Intent(Intent.ACTION_VIEW, uri)
                    handoff(intent, "Opened $provider search for $query. Choose a result there; playback has not been verified.")
                        .put("title", "${provider.replaceFirstChar { it.uppercase() }} · $query").put("query", query).put("url", uri.toString())
                }
                "open_app" -> {
                    val query = text(args, "query", 100).lowercase().trim()
                    val apps = activity.packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
                    val exact = apps.filter { it.loadLabel(activity.packageManager).toString().equals(query, true) }
                    val matches = (if (exact.isNotEmpty()) exact else apps.filter { it.loadLabel(activity.packageManager).toString().lowercase().contains(query) }).distinctBy { it.activityInfo.packageName }
                    when (matches.size) {
                        0 -> outcome("failed", "No installed app matches that name.")
                        1 -> { val app = matches.first(); handoff(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setClassName(app.activityInfo.packageName, app.activityInfo.name), "Opened ${app.loadLabel(activity.packageManager)}.") }
                        else -> outcome("ambiguous", "Several installed apps match: ${matches.take(5).joinToString { it.loadLabel(activity.packageManager).toString() }}. Say the full name.")
                    }
                }
                "navigate" -> handoff(Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=" + Uri.encode(text(args, "query", 500)))), "Opened the destination in Maps. Choose your route there.")
                "dial" -> handoff(Intent(Intent.ACTION_DIAL, Uri.fromParts("tel", number(args), null)), "The number is ready in the dialer. Tap Call to place it.")
                "compose_sms" -> handoff(Intent(Intent.ACTION_SENDTO, Uri.fromParts("smsto", number(args), null)).putExtra("sms_body", text(args, "body", 4000)), "The message draft is ready. Review and send it in your messaging app.")
                "compose_email" -> {
                    val recipient = text(args, "recipient", 320); require(Regex("^[^\\s@,;]+@[^\\s@,;]+\\.[^\\s@,;]+$").matches(recipient))
                    handoff(Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:" + Uri.encode(recipient) + "?subject=" + Uri.encode(text(args, "subject", 200)) + "&body=" + Uri.encode(text(args, "body", 8000)))), "The email draft is ready. Review and send it in your email app.")
                }
                "calendar_event" -> {
                    val start = OffsetDateTime.parse(text(args, "start", 40)); val end = OffsetDateTime.parse(text(args, "end", 40)); require(end.isAfter(start))
                    handoff(Intent(Intent.ACTION_INSERT).setData(CalendarContract.Events.CONTENT_URI)
                        .putExtra(CalendarContract.Events.TITLE, text(args, "title", 200)).putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, start.toInstant().toEpochMilli())
                        .putExtra(CalendarContract.EXTRA_EVENT_END_TIME, end.toInstant().toEpochMilli()).putExtra(CalendarContract.Events.EVENT_LOCATION, args.optString("location").take(500)),
                        "Your event draft is open in Calendar. Tap Save to add it.")
                }
                "set_volume" -> {
                    val percent = int(args, "percent", 0, 100); val audio = activity.getSystemService(AudioManager::class.java)
                    val maximum = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                    audio.setStreamVolume(AudioManager.STREAM_MUSIC, (percent * maximum + 50) / 100, AudioManager.FLAG_SHOW_UI)
                    outcome("completed", "Media volume is ${audio.getStreamVolume(AudioManager.STREAM_MUSIC) * 100 / maximum}%.")
                }
                "flashlight" -> {
                    require(args.get("enabled") is Boolean)
                    if (activity.checkSelfPermission(android.Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) outcome("needs_permission", "Allow Camera in THREAD settings to control the flashlight.")
                    else {
                        val camera = activity.getSystemService(CameraManager::class.java)
                        val id = camera.cameraIdList.firstOrNull { camera.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
                        if (id == null) outcome("failed", "This device does not have an available torch.")
                        else { camera.setTorchMode(id, args.getBoolean("enabled")); outcome("completed", "Flashlight ${if (args.getBoolean("enabled")) "on" else "off"}.") }
                    }
                }
                "open_settings" -> {
                    val screen = text(args, "screen", 30)
                    val route = mapOf("internet" to Settings.Panel.ACTION_INTERNET_CONNECTIVITY, "bluetooth" to Settings.ACTION_BLUETOOTH_SETTINGS,
                        "display" to Settings.ACTION_DISPLAY_SETTINGS, "notifications" to Settings.ACTION_APP_NOTIFICATION_SETTINGS,
                        "assistant" to Settings.ACTION_VOICE_INPUT_SETTINGS, "battery" to Settings.ACTION_BATTERY_SAVER_SETTINGS)[screen] ?: error("Unknown settings screen")
                    handoff(Intent(route).putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName), "Opened $screen settings. Make the change there.")
                }
                "create_widget" -> {
                    val title = text(args, "title", 60); val results = args.getJSONArray("results"); require(results.length() in 1..2 && ThreadModel.rows(results).all(::canMakeWidget))
                    widgetPreview(JSONObject().put("title", title).put("results", results))
                    outcome("prepared", "Your widget preview is ready. Tap Add to home screen to pin it.")
                }
                else -> outcome("failed", "This phone action is not connected.")
            }
        } catch (_: SecurityException) { outcome("needs_permission", "Android requires permission for this action. Open THREAD settings to review permissions.") }
        catch (_: android.content.ActivityNotFoundException) { outcome("failed", "No installed app can handle this action.") }
        catch (_: Exception) { outcome("failed", "This action could not be completed. No success was confirmed.") }
        // Record outcomes even if an external activity is opened. Redelivery never repeats a side effect.
        prefs.edit().putString(id, result.toString()).apply()
        val keys = prefs.all.keys
        if (keys.size > 200) prefs.edit().apply { keys.take(keys.size - 200).forEach { remove(it) } }.apply()
        return result
    }

    private fun handoff(intent: Intent, detail: String): JSONObject {
        if (intent.resolveActivity(activity.packageManager) == null) return outcome("failed", "No installed app can handle this action.")
        activity.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return outcome("handed_off", detail)
    }

    companion object {
        fun searchUri(provider: String, query: String, tab: String = "all"): Uri {
            require(query.isNotBlank() && query.length <= 500 && '\u0000' !in query)
            return when (provider) {
                "google" -> {
                    require(tab in listOf("all", "images", "videos", "news"))
                    Uri.parse("https://www.google.com/search").buildUpon().appendQueryParameter("q", query).apply {
                        mapOf("images" to "isch", "videos" to "vid", "news" to "nws")[tab]?.let { appendQueryParameter("tbm", it) }
                    }.build()
                }
                "youtube" -> Uri.parse("https://www.youtube.com/results").buildUpon().appendQueryParameter("search_query", query).build()
                "spotify" -> Uri.parse("https://open.spotify.com/search").buildUpon().appendPath(query).build()
                else -> throw IllegalArgumentException("Unsupported search provider")
            }
        }
        fun outcome(status: String, detail: String) = JSONObject().put("status", status).put("detail", detail)
        fun int(args: JSONObject, key: String, low: Int, high: Int): Int {
            val value = args.get(key); require(value is Int || value is Long)
            val number = (value as Number).toLong(); require(number in low.toLong()..high.toLong()); return number.toInt()
        }
        fun text(args: JSONObject, key: String, maximum: Int): String {
            val value = args.get(key); require(value is String); return value.trim().also { require(it.length in 1..maximum && '\u0000' !in it) }
        }
        fun number(args: JSONObject): String = text(args, "number", 40).also { require(Regex("^\\+?[0-9 ()-]{3,40}$").matches(it)) }
    }
}
