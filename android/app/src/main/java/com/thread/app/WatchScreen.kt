package com.thread.app

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID
import kotlin.math.abs
import kotlin.math.roundToLong

private val Live = Color(0xFF7FD1B2)
private val Warm = Color(0xFFFFC98A)

private fun watchTime(value: Long): String = if (value <= 0) "Not yet" else
    DateTimeFormatter.ofPattern("d MMM, HH:mm").withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(value))

/** "every 2 h", "hourly", "daily", "every 45 min" — the same wording as the browser's Watches strip. */
internal fun watchCadence(minutes: Int): String = when {
    minutes <= 0 -> ""
    minutes % 1440 == 0 -> if (minutes == 1440) "daily" else "every ${minutes / 1440} days"
    minutes % 60 == 0 -> if (minutes == 60) "hourly" else "every ${minutes / 60} h"
    else -> "every $minutes min"
}

/** "14 min ago", "in ~2 h", "just now"; empty for a missing time. */
internal fun watchRelative(value: Long, now: Long): String {
    if (value <= 0) return ""
    val diff = ((value - now) / 60000.0).roundToLong(); val size = abs(diff)
    if (size < 1) return "just now"
    val text = when { size < 60 -> "$size min"; size < 1440 -> "${(size / 60.0).roundToLong()} h"; else -> "${(size / 1440.0).roundToLong()} d" }
    return if (diff > 0) "in ~$text" else "$text ago"
}

/** Google News titles end with " - Source"; the source has its own line, so drop the repeat. */
internal fun watchHeadline(title: String, source: String): String {
    val suffix = " - $source"
    return if (source.isNotBlank() && title.endsWith(suffix) && title.length > suffix.length) title.dropLast(suffix.length) else title
}

@Composable private fun LiveDot(active: Boolean) {
    val still = Settings.Global.getFloat(LocalContext.current.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    val pulse = if (active && !still) rememberInfiniteTransition(label = "watch").animateFloat(1f, 2.4f,
        infiniteRepeatable(tween(1800), RepeatMode.Restart), label = "ring").value else 1f
    Box(Modifier.size(18.dp), contentAlignment = Alignment.Center) {
        if (active) Box(Modifier.size(7.dp).scale(pulse).alpha(((2.4f - pulse) / 1.4f).coerceIn(0f, 1f) * .55f).background(Live, CircleShape))
        Box(Modifier.size(7.dp).background(if (active) Live else Muted.copy(alpha = .5f), CircleShape))
    }
}

@Composable private fun Chip(text: String, color: Color = Pale) {
    Text(text, color = color, fontSize = 11.sp, modifier = Modifier.background(color.copy(alpha = .12f), RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 3.dp))
}

@Composable private fun WatchCard(row: JSONObject, now: Long, onClick: () -> Unit) {
    val active = row.getBoolean("active")
    val latest = WatchStore.rows(row.getJSONArray("items")).firstOrNull()
    Surface(color = Panel, shape = RoundedCornerShape(22.dp), border = BorderStroke(1.dp, Line),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(horizontal = 18.dp, vertical = 16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                LiveDot(active); Spacer(Modifier.width(8.dp))
                Text(row.getString("topic"), color = White, fontSize = 18.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.width(8.dp)); Chip(if (active) watchCadence(row.getInt("every_minutes")) else "stopped", if (active) Pale else Muted)
            }
            Text(listOfNotNull(
                watchRelative(row.optLong("last_checked"), now).ifBlank { null }?.let { "checked $it" } ?: "not checked yet",
                if (active) watchRelative(row.optLong("next_check"), now).ifBlank { null }?.let { "next $it" } else null,
            ).joinToString(" · "), color = Muted, fontSize = 12.sp, modifier = Modifier.padding(start = 26.dp, top = 2.dp))
            if (latest != null) Column(Modifier.padding(start = 26.dp, top = 12.dp)) {
                Text(watchHeadline(latest.getString("title"), latest.getString("source")), color = White.copy(alpha = .9f), fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(latest.getString("source") + (if (latest.optLong("published_at") > 0) " · " + watchRelative(latest.getLong("published_at"), now) else ""),
                    color = Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp))
            }
        }
    }
}

@Composable fun WatchScreen(model: ThreadModel) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var watches by remember { mutableStateOf(emptyList<JSONObject>()) }
    var selected by remember(model.watchId) { mutableStateOf(model.watchId) }
    var creating by remember { mutableStateOf(false) }
    var topic by remember { mutableStateOf("") }
    var minutes by remember { mutableStateOf("120") }
    var stopAfter by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }
    var alerts by remember { mutableStateOf(WatchRuntime.notifications(context)) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    suspend fun refresh() {
        try { watches = withContext(Dispatchers.IO) { WatchRuntime.store(context).list() }; alerts = WatchRuntime.notifications(context) }
        catch (_: Exception) { message = "Watch storage could not be read. The original data has been kept." }
        now = System.currentTimeMillis()
    }
    fun run(action: String, arguments: JSONObject) {
        busy = true
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                WatchRuntime.execute(context, JSONObject().put("request_id", "phone-watch-ui-${UUID.randomUUID()}").put("action", action).put("arguments", arguments))
            }
            message = result.optString("detail")
            if (action == "create_watch" && result.optString("status") == "completed") {
                creating = false; selected = result.getJSONObject("watch").getString("id")
                if (!result.optBoolean("notifications_enabled")) model.requestWatchNotifications?.invoke()
            }
            refresh(); busy = false
        }
    }
    LaunchedEffect(Unit) { while (true) { refresh(); delay(3000) } }
    val watch = watches.firstOrNull { it.optString("id") == selected }
    val active = watches.count { it.getBoolean("active") }
    LazyColumn(Modifier.fillMaxSize().testTag("watches"), contentPadding = PaddingValues(22.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Text(if (active > 0) "WATCHING · $active" else "WATCHES", color = Pale, fontSize = 11.sp, letterSpacing = 2.sp)
            Text("Watches", color = White, fontSize = 30.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 4.dp))
            Text("New reports, without repeating old headlines.", color = Muted)
            Text("Runs on this phone, even after you close THREAD. Android may delay checks to save battery or wait for a network.", color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
            if (!alerts) {
                Text("Alerts are off. Checks and headlines are still saved here.", color = Warm, modifier = Modifier.padding(top = 10.dp))
                TextButton(onClick = { model.requestWatchNotifications?.invoke() }) { Text("Enable notifications") }
            }
            if (message.isNotBlank()) Text(message, color = Pale, modifier = Modifier.padding(top = 10.dp))
            Row {
                if (watch != null || creating) TextButton(onClick = { selected = ""; creating = false }) { Text("All Watches") }
                TextButton(onClick = { creating = true; selected = "" }, enabled = !busy) { Text("New Watch") }
            }
        }
        if (creating) item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(topic, { topic = it.take(200) }, label = { Text("News topic") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(minutes, { minutes = it.take(5) }, label = { Text("Every minutes (minimum 15)") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(stopAfter, { stopAfter = it.take(6) }, label = { Text("Stop after minutes (optional)") }, modifier = Modifier.fillMaxWidth())
                Text("The first check quietly saves today's headlines. Only newly discovered reports after that can notify.", color = Muted, fontSize = 12.sp)
                HapticButton("Start watching", primary = true, enabled = !busy && topic.isNotBlank() && (minutes.toIntOrNull() ?: 0) in 15..10080 && (stopAfter.isBlank() || (stopAfter.toIntOrNull() ?: 0) in 1..525600)) {
                    run("create_watch", JSONObject().put("topic", topic).put("every_minutes", minutes.toInt()).apply { if (stopAfter.isNotBlank()) put("stop_after", stopAfter.toInt()) })
                }
            }
        }
        else if (watch != null) {
            val on = watch.getBoolean("active")
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    LiveDot(on); Spacer(Modifier.width(8.dp))
                    Chip(if (on) "Active · " + watchCadence(watch.getInt("every_minutes")) else "Stopped · history kept", if (on) Live else Muted)
                }
                Text(watch.getString("topic"), color = White, fontSize = 26.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 8.dp))
                Text("Last check: " + (watchRelative(watch.optLong("last_checked"), now).ifBlank { "not yet" }) +
                    (if (on) " · next target " + watchRelative(watch.optLong("next_check"), now).ifBlank { "unknown" } + " (approximate)" else ""),
                    color = Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp))
                if (watch.optLong("stop_at") > 0) Text("Stops: ${watchTime(watch.getLong("stop_at"))}", color = Muted, fontSize = 13.sp)
                if (on) Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 6.dp)) {
                    TextButton(onClick = { run("check_watch_now", JSONObject().put("id", selected)) }, enabled = !busy) { Text(if (busy) "Checking…" else "Check now") }
                    TextButton(onClick = { run("stop_watch", JSONObject().put("id", selected)) }, enabled = !busy) { Text("Stop Watch", color = Color(0xFFF0A48A)) }
                }
            }
            item { Text("HEADLINES", color = Pale, fontSize = 11.sp, letterSpacing = 2.sp) }
            val headlines = WatchStore.rows(watch.getJSONArray("items"))
            if (headlines.isEmpty()) item { Text("No headlines yet. The first successful check will save a baseline here.", color = Muted) }
            items(headlines, key = { it.getString("id") }) { article ->
                Surface(color = Panel, shape = RoundedCornerShape(20.dp), border = BorderStroke(1.dp, Line), modifier = Modifier.fillMaxWidth().clickable {
                    try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(article.getString("link")))) }
                    catch (_: Exception) { message = "No browser could open this report." }
                }) {
                    Column(Modifier.fillMaxWidth().padding(16.dp)) {
                        Text(watchHeadline(article.getString("title"), article.getString("source")), color = White, fontSize = 15.sp)
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp)) {
                            Chip(article.getString("source"))
                            Spacer(Modifier.width(8.dp))
                            Text(if (article.optLong("published_at") > 0) watchRelative(article.getLong("published_at"), now) else "Publication time unavailable", color = Muted, fontSize = 11.sp, modifier = Modifier.weight(1f))
                            Text("Open ↗", color = Pale, fontSize = 12.sp)
                        }
                    }
                }
            }
            item { Text("CHECK HISTORY", color = Pale, fontSize = 11.sp, letterSpacing = 2.sp, modifier = Modifier.padding(top = 8.dp)) }
            items(WatchStore.rows(watch.getJSONArray("history"))) { check ->
                Row(verticalAlignment = Alignment.Top) {
                    Box(Modifier.padding(top = 6.dp).size(6.dp).background(Line, CircleShape)); Spacer(Modifier.width(12.dp))
                    Column {
                        Text(check.getString("detail"), color = White.copy(alpha = .85f), fontSize = 13.sp)
                        Text(watchTime(check.getLong("checked_at")), color = Muted, fontSize = 11.sp)
                    }
                }
            }
        } else {
            if (watches.isEmpty()) item {
                Surface(color = Panel, shape = RoundedCornerShape(22.dp), border = BorderStroke(1.dp, Line)) {
                    Column(Modifier.fillMaxWidth().padding(18.dp)) {
                        Text("Nothing watched yet.", color = White, fontSize = 17.sp)
                        Text("Say: “Every 2 hours, give me updates on Manchester City 115 charges.” Or add one here without a voice connection.", color = Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
            items(watches, key = { it.getString("id") }) { row -> WatchCard(row, now) { selected = row.getString("id") } }
        }
    }
}
