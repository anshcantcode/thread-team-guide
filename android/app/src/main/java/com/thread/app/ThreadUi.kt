package com.thread.app

import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.Settings
import android.view.HapticFeedbackConstants
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.*
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import kotlin.math.*
import androidx.compose.ui.platform.testTag

val Ink = Color(0xFF080D14)
val Panel = Color(0xFF131D2A)
val Line = Color(0xFF283648)
val Pale = Color(0xFFA9C7F5)
val Muted = Color(0xFFA6B3C7)
val White = Color(0xFFF5F7FC)
val Blue = Color(0xFF2378F3)

@Composable fun ThreadTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = darkColorScheme(primary = Pale, onPrimary = Ink, background = Ink, surface = Panel,
        onBackground = White, onSurface = White, outline = Line, surfaceVariant = Panel, secondary = Pale),
        typography = Typography(bodyLarge = androidx.compose.ui.text.TextStyle(fontSize = 16.sp, lineHeight = 25.sp),
            bodyMedium = androidx.compose.ui.text.TextStyle(fontSize = 14.sp, lineHeight = 21.sp)), content = content)
}

@Composable fun AcousticSphere(modifier: Modifier = Modifier, level: Float = 0f, active: Boolean = false) {
    val context = LocalContext.current
    val motion = remember { Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) > 0 }
    val drift = if (active && motion) rememberInfiniteTransition(label = "Acoustic drift").animateFloat(-1f, 1f, infiniteRepeatable(tween(5500, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "Drift").value else 0f
    val amplitude by animateFloatAsState(if (motion) level else 0f, tween(220), label = "Voice intensity")
    Image(painterResource(R.drawable.thread_sphere), contentDescription = "THREAD voice sphere", contentScale = ContentScale.Fit,
        modifier = modifier.graphicsLayer {
            scaleX = 1f + amplitude * .045f; scaleY = 1f + amplitude * .035f
            rotationZ = drift * 1.5f; alpha = .92f + amplitude * .08f
        })
}

@Composable fun HapticButton(label: String, icon: ImageVector? = null, primary: Boolean = false, enabled: Boolean = true,
                             haptics: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val view = LocalView.current
    Button(onClick = { if (haptics) view.performHapticFeedback(HapticFeedbackConstants.CONFIRM); onClick() }, enabled = enabled,
        modifier = modifier.heightIn(min = 56.dp), shape = RoundedCornerShape(28.dp),
        colors = ButtonDefaults.buttonColors(containerColor = if (primary) Blue else Panel, contentColor = White, disabledContainerColor = Panel)) {
        icon?.let { Icon(it, null, Modifier.size(21.dp)); Spacer(Modifier.width(10.dp)) }; Text(label, fontSize = 16.sp, fontWeight = FontWeight.Medium)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun ThreadApp(model: ThreadModel, start: () -> Unit, addImage: () -> Unit, camera: () -> Unit, permissions: () -> Unit) {
    val ui = model.ui
    val context = LocalContext.current
    val view = LocalView.current
    var selected by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(model.openResult) { model.openResult?.let { selected = it; model.openResult = null } }
    var typed by remember { mutableStateOf("") }
    LaunchedEffect(model.sharedText) { if (model.sharedText.isNotBlank()) { typed = model.sharedText; model.sharedText = "" } }
    var showPrivacy by remember { mutableStateOf(false) }
    var sendAfterConsent by remember { mutableStateOf(false) }
    val changeRoute: (String) -> Unit = { if (model.haptics) view.performHapticFeedback(HapticFeedbackConstants.SEGMENT_TICK); selected = null; model.route = it }
    BackHandlerCompat(selected != null || model.route != "voice") { if (selected != null) selected = null else changeRoute("voice") }
    Surface(color = Ink, modifier = Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Brush.radialGradient(listOf(Color(0xFF102235), Ink), Offset(650f, 0f), 1100f))) {
            Column(Modifier.fillMaxSize().safeDrawingPadding()) {
                Row(Modifier.fillMaxWidth().height(60.dp).padding(horizontal = 18.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (selected != null || model.route == "settings") IconButton(onClick = { if (selected != null) selected = null else changeRoute("voice") }) { Icon(Icons.Outlined.ArrowBack, "Back", tint = White) }
                    Text("THREAD", color = White, fontSize = 14.sp, letterSpacing = 5.sp, modifier = Modifier.weight(1f).padding(start = 6.dp))
                    if (selected != null) {
                        val result=selected!!
                        if(canMakeWidget(result)) IconButton(onClick={model.widget=JSONObject().put("title",title(result).take(60)).put("results",org.json.JSONArray(listOf(result)))}) { Icon(Icons.Outlined.Widgets,"Make a widget",tint=Pale,modifier=Modifier.size(21.dp)) }
                        IconButton(onClick={share(context,result)}) { Icon(Icons.Outlined.IosShare,"Share result",tint=Pale,modifier=Modifier.size(21.dp)) }
                    } else IconButton(onClick = { changeRoute("settings") }) { Icon(Icons.Outlined.Settings, "Settings", tint = Pale, modifier = Modifier.size(23.dp)) }
                }
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    AnimatedContent(targetState = if (selected != null) "detail" else model.route, transitionSpec = {
                        (fadeIn(tween(220)) + slideInHorizontally(tween(240)) { it / 12 }) togetherWith fadeOut(tween(140))
                    }, label = "Screen transition") { route ->
                        when (route) {
                            "detail" -> selected?.let { ResultDetail(it, model, { url -> openUrl(context, url) }) }
                            "voice" -> VoiceScreen(model, start, { model.keyboard = true }, camera, { changeRoute("library") })
                            "home" -> HomeScreen(model, { selected = it }, { changeRoute("voice"); start() }, { changeRoute("widgets") })
                            "library" -> LibraryScreen(model, { selected = it })
                            "widgets" -> WidgetScreen(model)
                            "settings" -> SettingsScreen(model, permissions, { showPrivacy = true })
                        }
                    }
                }
                if (ui.connected && (model.route != "voice" || selected != null)) CompactDock(model, { changeRoute("voice") }, start, selected?.let(::title))
                if (!ui.connected && !ui.connecting && !ui.ended && selected == null && model.route != "settings") {
                    Row(Modifier.fillMaxWidth().height(66.dp).padding(horizontal = 12.dp), horizontalArrangement = Arrangement.SpaceAround) {
                        listOf(Triple("home", "Home", Icons.Outlined.Home), Triple("voice", "Talk", Icons.Outlined.GraphicEq), Triple("library", "Library", Icons.Outlined.Bookmarks), Triple("widgets", "Widgets", Icons.Outlined.Widgets)).forEach { (key, title, icon) ->
                            Column(Modifier.weight(1f).fillMaxHeight().clickable { changeRoute(key) }.padding(top = 9.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                Icon(icon, title, tint = if (model.route == key) Pale else Muted, modifier = Modifier.size(22.dp))
                                Spacer(Modifier.height(4.dp)); Text(title, fontSize = 10.sp, color = if (model.route == key) Pale else Muted)
                            }
                        }
                    }
                }
            }
        }
    }
    if (model.keyboard) ModalBottomSheet(onDismissRequest = { model.keyboard = false }, containerColor = Panel, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().padding(24.dp).imePadding()) {
            Text("Say it your way.", fontSize = 24.sp, color = White)
            Spacer(Modifier.height(16.dp))
            OutlinedTextField(typed, { typed = it.take(12000) }, Modifier.fillMaxWidth(), placeholder = { Text("Ask, plan, or change your mind…") }, minLines = 2, maxLines = 6, shape = RoundedCornerShape(20.dp))
            Spacer(Modifier.height(16.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = addImage) { Icon(Icons.Outlined.AddPhotoAlternate, "Share an image") }
                Spacer(Modifier.weight(1f))
                HapticButton("Send", Icons.Outlined.ArrowUpward, primary = true, enabled = typed.isNotBlank(), haptics = model.haptics) {
                    if (model.consent) { model.sendText(typed); typed = "" } else { sendAfterConsent = true; showPrivacy = true }
                }
            }
        }
    }
    if (ui.error != null) ModalBottomSheet(onDismissRequest = model::clearError, containerColor = Panel) {
        Column(Modifier.fillMaxWidth().padding(28.dp)) {
            Icon(Icons.Outlined.WifiOff, null, tint = Pale, modifier = Modifier.size(28.dp))
            Spacer(Modifier.height(20.dp)); Text("A moment to reconnect.", color = White, fontSize = 26.sp)
            Spacer(Modifier.height(12.dp)); Text(ui.error, color = Muted)
            Spacer(Modifier.height(24.dp)); HapticButton("Try again", primary = true, modifier = Modifier.fillMaxWidth(), haptics = model.haptics) { model.clearError(); start() }
            TextButton(onClick = model::clearError, modifier = Modifier.align(Alignment.CenterHorizontally)) { Text("Keep browsing my results") }
        }
    }
    if (showPrivacy) AlertDialog(onDismissRequest = { showPrivacy = false; sendAfterConsent = false }, title = { Text("Your voice, with your permission.") },
        text = { Text("During a conversation, audio, messages, shared images and relevant task context go to Google Gemini over the internet. Searches go to their named sources. THREAD runs its task engine and saves text, notes and results on this phone; raw microphone audio is not saved. Phone actions use Android's own apps and permissions.") },
        confirmButton = { TextButton(onClick = { model.preference("consent", true); showPrivacy = false; if (sendAfterConsent) { model.sendText(typed); typed = ""; sendAfterConsent = false } }) { Text("Continue") } },
        dismissButton = { TextButton(onClick = { showPrivacy = false; sendAfterConsent = false }) { Text("Close") } })
    model.widget?.let { config -> WidgetPreview(model, config) }
    if (model.taskExpanded) TaskSheet(model)
}

@Composable fun BackHandlerCompat(enabled: Boolean, onBack: () -> Unit) = androidx.activity.compose.BackHandler(enabled, onBack)

@Composable private fun VoiceScreen(model: ThreadModel, start: () -> Unit, type: () -> Unit, camera: () -> Unit, results: () -> Unit) {
    val ui = model.ui
    Column(Modifier.fillMaxSize().padding(horizontal = 26.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        if (ui.ended) {
            Spacer(Modifier.height(48.dp)); Text("Conversation saved.", fontSize = 32.sp, lineHeight = 38.sp, color = White, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(14.dp)); Text("${ui.results.size} results in your Library", color = Muted, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(32.dp)); ui.results.takeLast(3).reversed().forEach { ResultRow(it, results) }
            Spacer(Modifier.weight(1f)); HapticButton("New conversation", Icons.Outlined.Add, true, modifier = Modifier.fillMaxWidth(), haptics = model.haptics) { model.newConversation(); start() }
            TextButton(onClick = results) { Text("Open Library") }; Spacer(Modifier.height(20.dp))
        } else {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                AcousticSphere(Modifier.fillMaxWidth().aspectRatio(1f), ui.level, ui.connected)
            }
            if (ui.connected || ui.connecting) {
                Column(Modifier.fillMaxWidth().heightIn(min = 110.dp, max = 190.dp).verticalScroll(rememberScrollState())) {
                    Text(if (ui.muted && ui.connected) "Microphone muted" else ui.mode, color = Pale, fontSize = 14.sp, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                    Spacer(Modifier.height(10.dp))
                    Text(ui.caption.ifBlank { if (ui.connecting) "A moment. We’re connecting." else "I’m listening." }, fontSize = 23.sp, lineHeight = 31.sp, color = White)
                }
                if (hasTask(ui)) { Spacer(Modifier.height(12.dp)); ActiveTaskCard(model) }
                ui.results.lastOrNull { it.optString("domain")!="phone" && (it.optJSONArray("items")?.length() ?: 0)>0 }?.let { result ->
                    TextButton(onClick={model.openResult=result}) { Text("View result");Spacer(Modifier.width(7.dp));Icon(Icons.Outlined.ArrowForward,null,Modifier.size(17.dp)) }
                }
                Spacer(Modifier.height(22.dp))
                if (ui.connecting) { LinearProgressIndicator(Modifier.fillMaxWidth().height(2.dp), color = Pale, trackColor = Line); TextButton(onClick = { model.disconnect(false) }) { Text("Cancel") } }
                else VoiceControls(model, camera, type, start)
            } else {
                Text("Go on.", fontSize = 44.sp, letterSpacing = (-1.5).sp, fontWeight = FontWeight.SemiBold, color = White)
                Spacer(Modifier.height(8.dp)); Text("Your day, in conversation.", fontSize = 18.sp, color = Pale)
                Spacer(Modifier.height(38.dp)); HapticButton("Start talking", Icons.Outlined.Mic, true, modifier = Modifier.fillMaxWidth(), haptics = model.haptics, onClick = start)
                Spacer(Modifier.height(8.dp)); TextButton(onClick = type) { Text("Type instead", color = Pale) }
            }
            Spacer(Modifier.height(18.dp))
        }
    }
}

@Composable private fun VoiceControls(model: ThreadModel, camera: () -> Unit, type: () -> Unit, enableMic: () -> Unit) {
    val view = LocalView.current
    Surface(color = Panel.copy(alpha = .72f), shape = RoundedCornerShape(30.dp), border = BorderStroke(.5.dp, Line)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text("%02d:%02d".format(model.ui.elapsed / 60, model.ui.elapsed % 60), fontSize = 12.sp, color = Muted, modifier = Modifier.align(Alignment.End))
            Spacer(Modifier.height(12.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                @Composable fun control(icon: ImageVector, label: String, red: Boolean = false, click: () -> Unit) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        FilledIconButton(onClick = { if (model.haptics) view.performHapticFeedback(HapticFeedbackConstants.CONFIRM); click() },
                            modifier = Modifier.size(54.dp), colors = IconButtonDefaults.filledIconButtonColors(containerColor = if (red) Color(0xFFE83B43) else Color(0xFF202D3D), contentColor = White)) { Icon(icon, label, Modifier.size(24.dp)) }
                        Spacer(Modifier.height(7.dp)); Text(label, color = White, fontSize = 11.sp)
                    }
                }
                control(Icons.Outlined.PhotoCamera, "Camera", click = camera)
                control(if (model.ui.muted) Icons.Outlined.MicOff else Icons.Outlined.Mic, if (model.ui.muted) "Unmute" else "Mute") { if (model.ui.muted) enableMic() else model.toggleMute() }
                control(Icons.Outlined.Keyboard, "Keyboard", click = type)
                control(Icons.Outlined.CallEnd, "End", true) { model.disconnect() }
            }
        }
    }
}

@Composable private fun CompactDock(model: ThreadModel, open: () -> Unit, enableMic: () -> Unit, subject: String? = null) {
    val view = LocalView.current
    Surface(modifier = Modifier.padding(14.dp).fillMaxWidth(), color = Color(0xFF152130), shape = RoundedCornerShape(26.dp), border = BorderStroke(.5.dp, Line), onClick = open) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.GraphicEq, null, tint = Pale, modifier = Modifier.size(30.dp)); Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) { Text(if (model.ui.muted) "Muted" else model.ui.mode, fontSize = 12.sp, color = Pale); Text(subject ?: model.ui.caption.ifBlank { "Voice conversation" }, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 11.sp, color = Muted) }
            IconButton(onClick = { if (model.ui.muted) enableMic() else model.toggleMute(); if (model.haptics) view.performHapticFeedback(HapticFeedbackConstants.CONFIRM) }) { Icon(if (model.ui.muted) Icons.Outlined.MicOff else Icons.Outlined.Mic, if (model.ui.muted) "Unmute" else "Mute", tint = White) }
            FilledIconButton(onClick = { model.disconnect(); if (model.haptics) view.performHapticFeedback(HapticFeedbackConstants.CONFIRM) }, colors = IconButtonDefaults.filledIconButtonColors(containerColor = Color(0xFFE83B43))) { Icon(Icons.Outlined.CallEnd, "End conversation", tint = White) }
        }
    }
}

@Composable private fun HomeScreen(model: ThreadModel, select: (JSONObject) -> Unit, talk: () -> Unit, widgets: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 26.dp), contentPadding = PaddingValues(top = 38.dp, bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("A little more\nroom in your day.", fontSize = 34.sp, lineHeight = 41.sp, letterSpacing = (-.6).sp, color = White); Spacer(Modifier.height(12.dp)); Text("Talk, explore, pick up where you left off.", color = Muted); Spacer(Modifier.height(20.dp)) }
        item { HapticButton("Start a conversation", Icons.Outlined.Mic, true, haptics = model.haptics, modifier = Modifier.fillMaxWidth(), onClick = talk) }
        if (hasTask(model.ui)) item { ActiveTaskCard(model) }
        if (model.ui.results.isNotEmpty()) {
            item { SectionLabel("Recent activity") }
            items(model.ui.results.takeLast(5).reversed(), key = { it.optString("id") }) { ResultRow(it) { select(it) } }
        } else item { Group { Text("It starts with a conversation.", color = White, fontSize = 18.sp); Spacer(Modifier.height(10.dp)); Text("Your research, plans and phone actions will stay here, ready to pick up again.", color = Muted) } }
        item { Spacer(Modifier.height(8.dp)); Group { Text("Your day, at a glance.", fontSize = 22.sp, color = White); Spacer(Modifier.height(10.dp)); Text("Choose exactly what belongs on your home screen.", color = Muted); TextButton(onClick = widgets, contentPadding = PaddingValues(top = 12.dp)) { Text("Make a widget", color = Pale); Spacer(Modifier.width(8.dp)); Icon(Icons.Outlined.ArrowForward, null, Modifier.size(17.dp)) } } }
    }
}

@Composable private fun LibraryScreen(model: ThreadModel, select: (JSONObject) -> Unit) {
    var query by remember { mutableStateOf("") }
    val rows = model.ui.results.reversed().filter { query.isBlank() || it.toString().contains(query, true) }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 26.dp), contentPadding = PaddingValues(top = 28.dp, bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("Your Library", fontSize = 34.sp, letterSpacing = (-.8).sp, color = White); Spacer(Modifier.height(8.dp)); Text("Kept on this phone.", color = Muted); Spacer(Modifier.height(18.dp)) }
        item { OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true, placeholder = { Text("Search your results") }, leadingIcon = { Icon(Icons.Outlined.Search, null) }, shape = RoundedCornerShape(22.dp)) }
        if (rows.isEmpty()) item { Text(if (query.isBlank()) "Your first result will appear here." else "No matching results.", modifier = Modifier.padding(vertical = 24.dp), color = Muted) }
        items(rows, key = { it.optString("id") }) { ResultRow(it) { select(it) } }
        if (model.ui.transcript.isNotEmpty()) item {
            SectionLabel("Conversation")
            model.ui.transcript.filter { it.optString("source") == "native_audio" }.takeLast(30).forEach { row ->
                Text(if (row.optString("role") == "user") "You" else "THREAD", color = Pale, fontSize = 12.sp, modifier = Modifier.padding(top = 18.dp))
                Text(row.optString("text"), color = White, modifier = Modifier.padding(top = 5.dp))
            }
        }
    }
}

@Composable private fun ResultRow(result: JSONObject, click: () -> Unit) {
    Surface(onClick = click, color = Panel.copy(alpha = .85f), shape = RoundedCornerShape(22.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(domainIcon(result.optString("domain")), null, tint = Pale, modifier = Modifier.size(23.dp)); Spacer(Modifier.width(15.dp))
            Column(Modifier.weight(1f)) { Text(title(result), color = White, fontSize = 16.sp, maxLines = 2, overflow = TextOverflow.Ellipsis); Spacer(Modifier.height(5.dp)); Text(result.optString("source"), color = Muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            Spacer(Modifier.width(10.dp)); Icon(Icons.Outlined.ChevronRight, null, tint = Muted, modifier = Modifier.size(18.dp))
        }
    }
}

@Composable private fun ResultDetail(result: JSONObject, model: ThreadModel, url: (String) -> Unit) {
    val rows = ThreadModel.rows(result.optJSONArray("items"))
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 25.dp).testTag("result-detail"), contentPadding = PaddingValues(top = 12.dp, bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (result.optString("provenance") in listOf("demo", "synthetic", "draft")) item {
            Text(if (result.optString("provenance") == "draft") "AI draft · review before using" else "Demo inventory · fictional options", color = Pale, fontSize = 12.sp)
        }
        items(rows, key = { it.optString("id", it.optString("title")) }) { row ->
            when {
                row.optString("kind") == "sports_profile" || row.has("matches") -> SportsProfile(sportProfile(row), result, model, url)
                result.optString("domain") == "sports" && row.has("score") -> MatchRow(row, url)
                result.optString("domain") == "weather" -> WeatherDetail(row)
                result.optString("domain") == "world_clocks" -> Group {
                    Text(row.optString("title"), color = Pale, fontSize = 18.sp)
                    androidx.compose.ui.viewinterop.AndroidView(factory = { android.widget.TextClock(it).apply { timeZone = row.getString("zone"); format12Hour = "HH:mm:ss"; format24Hour = "HH:mm:ss"; textSize = 48f; setTextColor(android.graphics.Color.WHITE); typeface = android.graphics.Typeface.create("sans-serif-light", android.graphics.Typeface.NORMAL) } }, modifier = Modifier.fillMaxWidth())
                    Text(row.optString("zone"), color = Muted, fontSize = 12.sp)
                }
                result.optString("domain") == "phone" -> {
                    Text(row.optString("title"), fontSize = 32.sp, color = White); Spacer(Modifier.height(18.dp))
                    Group {
                        Text(statusLabel(row.optString("status")), color = Pale, fontSize = 14.sp); Spacer(Modifier.height(10.dp)); Text(row.optString("detail"), color = White, fontSize = 19.sp, lineHeight = 28.sp)
                        ThreadModel.rows(row.optJSONArray("steps")).forEach { step -> Text("${statusLabel(step.optString("status"))} · ${step.optString("label")}", color = Muted, modifier = Modifier.padding(top = 10.dp)) }
                        if (row.optString("url").isNotBlank()) TextButton(onClick = { url(row.optString("url")) }) { Text("Open search again") }
                        if (row.optString("status") == "needs_connection") Text("Connect Spotify in Settings, then make a fresh request.", color = Pale, modifier = Modifier.padding(top = 12.dp))
                    }
                }
                row.has("document") -> DocumentDetail(row.getJSONObject("document"))
                result.optString("domain") in listOf("calculate", "currency", "convert", "dates", "clock", "timer") -> {
                    Text(row.optString("title"), fontSize = 28.sp, color = White); Spacer(Modifier.height(18.dp))
                    Text((row.opt("value") ?: row.opt("to_time") ?: row.opt("seconds") ?: "—").toString(), fontSize = 44.sp, color = White, fontWeight = FontWeight.Light)
                    Spacer(Modifier.height(12.dp)); Text(row.optString("expression", result.optString("summary")), color = Muted)
                }
                result.optString("domain") == "travel" -> FlightDetail(row)
                else -> {
                    Column(Modifier.fillMaxWidth().padding(vertical = 10.dp)) {
                        Text(row.optString("provider", result.optString("source")), fontSize = 11.sp, color = Pale)
                        Spacer(Modifier.height(9.dp)); Text(row.optString("title"), fontSize = 22.sp, lineHeight = 28.sp, color = White)
                        val body = row.optString("body", row.optString("detail", row.optString("summary", row.optString("snippet", row.optString("description")))))
                        if (body.isNotBlank()) { Spacer(Modifier.height(10.dp)); Text(body, color = Muted) }
                        if (row.optString("published").isNotBlank()) Text(row.optString("published"), fontSize = 11.sp, color = Muted, modifier = Modifier.padding(top = 8.dp))
                        if (row.optString("url").isNotBlank()) TextButton(onClick = { url(row.optString("url")) }, contentPadding = PaddingValues(top = 8.dp)) { Text("Open source"); Spacer(Modifier.width(6.dp)); Icon(Icons.Outlined.NorthEast, null, Modifier.size(15.dp)) }
                        HorizontalDivider(Modifier.padding(top = 16.dp), color = Line)
                    }
                }
            }
        }
        item {
            if (rows.isEmpty()) Text(result.optString("error", result.optString("note", "No matching source records.")), color = Muted)
            Spacer(Modifier.height(10.dp)); HorizontalDivider(color = Line); Spacer(Modifier.height(14.dp))
            Text("Source · ${result.optString("source")}", color = Muted, fontSize = 11.sp)
            Text("Retrieved ${formatDate(result.optString("retrieved_at"))}", color = Muted, fontSize = 11.sp)
        }
    }
}

@Composable private fun SportsProfile(row: JSONObject, result: JSONObject, model: ThreadModel, url: (String) -> Unit) {
    val metrics = ThreadModel.rows(row.optJSONArray("metrics"))
    val records = ThreadModel.rows(row.optJSONArray("records"))
    val sport = row.optString("sport")
    val view = LocalView.current
    Column {
        Box(Modifier.fillMaxWidth().height(if (row.optString("portrait").isNotBlank()) 264.dp else 116.dp)) {
            if (row.optString("portrait").isNotBlank()) RemotePortrait(row.optString("portrait"), Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(205.dp).testTag("sports-portrait"))
            Box(Modifier.matchParentSize().background(Brush.verticalGradient(0f to Ink.copy(alpha = .01f), .75f to Ink.copy(alpha = .04f), 1f to Ink)))
            Column(Modifier.align(Alignment.TopStart).padding(end=57.dp)) {
                Text(row.optString("title"), fontSize = 29.sp, lineHeight = 34.sp, letterSpacing = (-.7).sp, color = White)
                val affiliation=row.optString("team").ifBlank { row.optString("league") }
                if(affiliation.isNotBlank()) { Spacer(Modifier.height(7.dp)); Text(affiliation, color = Pale, fontSize = 14.sp) }
                val identity=listOf(row.optString("position"),row.optString("jersey").takeIf(String::isNotBlank)?.let { "#$it" }.orEmpty(),row.optString("country")).filter(String::isNotBlank)
                val detail=if(identity.isEmpty()) row.optString("sport_label",sport).takeUnless { it.equals(affiliation,true) }.orEmpty() else identity.joinToString(" · ")
                if(detail.isNotBlank()) { Spacer(Modifier.height(4.dp)); Text(detail, color = Muted, fontSize = 11.sp) }
            }
            val mark=row.optString("logo").ifBlank { row.optString("flag") }
            if(mark.isNotBlank()) RemotePortrait(mark,Modifier.align(Alignment.TopEnd).size(49.dp).padding(top=4.dp))
        }
        if(sport=="cricket") {
            val format=result.optJSONObject("arguments")?.optString("cricket_format","all") ?: "all"
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(top=2.dp,bottom=14.dp)) {
                listOf("ODI","T20","Test","all").forEachIndexed { i,f -> SegmentedButton(selected=format==f,onClick={ if(model.haptics)view.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK);model.filterSports(result,f) },shape=SegmentedButtonDefaults.itemShape(i,4),enabled=!model.sportsLoading,colors=SegmentedButtonDefaults.colors(activeContainerColor=Blue,activeContentColor=White,inactiveContainerColor=Ink,inactiveContentColor=Muted,activeBorderColor=Blue,inactiveBorderColor=Line)) { Text(if(f=="all") "All" else f,fontSize=12.sp) } }
            }
            if(model.sportsLoading) LinearProgressIndicator(Modifier.fillMaxWidth().height(2.dp),color=Pale,trackColor=Line)
            model.sportsError?.let { Text(it,color=Pale,fontSize=12.sp,modifier=Modifier.padding(bottom=14.dp)) }
        }
        Text("${records.size} ${if(sport=="cricket") "innings" else if(sport=="racing") "Grands Prix" else "matches"} selected",color=Pale,fontSize=11.sp)
        if (metrics.isNotEmpty()) {
            Row(Modifier.fillMaxWidth().padding(top=9.dp,bottom=17.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                metrics.take(3).forEachIndexed { i,metric ->
                    if(i>0) VerticalDivider(Modifier.height(37.dp).padding(horizontal=10.dp),color=Line)
                    Column(Modifier.weight(1f)) { Text(metric.optString("value"), fontSize=26.sp,color=White,fontWeight=FontWeight.Medium);Text(metric.optString("label"),fontSize=10.sp,lineHeight=14.sp,color=Muted) }
                }
            }
        }
        Spacer(Modifier.height(11.dp))
        Text(when(sport){"cricket" -> "Recent innings";"racing" -> "Recent Grands Prix";"tennis" -> "Recent matches";else -> "Recent appearances"},fontSize=15.sp,color=White,fontWeight=FontWeight.Medium)
        SportsTable(row,records,result.optJSONObject("arguments")?.optString("cricket_skill") ?: "batting",model.haptics,url)
        if(records.isEmpty()) Text("The connected source has no structured records for this selection.",color=Muted,fontSize=12.sp,modifier=Modifier.padding(vertical=18.dp))
        if(row.optString("coverage_status")=="partial") Text("${records.size} of ${row.optInt("requested_count",5)} requested records available",color=Pale,fontSize=12.sp,modifier=Modifier.padding(top=12.dp))
        Text(row.optString("coverage"),color=Muted,fontSize=10.sp,lineHeight=15.sp,modifier=Modifier.padding(top=14.dp))
        if(row.optString("identity_source").isNotBlank()) Text("Profile · ${row.optString("identity_source")}",color=Muted,fontSize=10.sp)
        if(row.optString("url").isNotBlank()) TextButton(onClick={url(row.optString("url"))},contentPadding=PaddingValues(top=10.dp)){Text("Open source profile",fontSize=12.sp)}
    }
}

private data class StatColumn(val key:String,val label:String,val width:Int)
private fun sportsColumns(sport:String,skill:String):List<StatColumn> = when(sport) {
    "basketball" -> listOf(StatColumn("score","Result",73),StatColumn("points","PTS",29),StatColumn("totalRebounds","REB",29),StatColumn("assists","AST",29))
    "cricket" -> if(skill=="bowling") listOf(StatColumn("score","Figures",60),StatColumn("overs","Overs",42),StatColumn("economy","Econ",46)) else listOf(StatColumn("runs","Runs",43),StatColumn("balls","Balls",39),StatColumn("strike_rate","SR",48))
    "racing" -> listOf(StatColumn("score","Finish",43),StatColumn("grid","Grid",39),StatColumn("points","Points",45))
    "tennis" -> listOf(StatColumn("result","",15),StatColumn("score","Sets",137))
    "baseball" -> listOf(StatColumn("score","Result",67),StatColumn("hits","H",29),StatColumn("homeRuns","HR",29),StatColumn("RBIs","RBI",29))
    "hockey" -> listOf(StatColumn("score","Result",67),StatColumn("goals","G",29),StatColumn("assists","A",29),StatColumn("points","PTS",29))
    "football" -> listOf(StatColumn("score","Result",67),StatColumn("passingYards","Pass",43),StatColumn("rushingYards","Rush",43))
    else -> listOf(StatColumn("score","Score",83))
}
private fun statValue(row:JSONObject,key:String):String {
    if(key=="score" || key=="result")return row.optString(key,"—")
    val aliases=when(key){"overs"->listOf("overs","ov");"economy"->listOf("economy","econ","er");else->listOf(key)}
    val stat=ThreadModel.rows(row.optJSONArray("stats")).firstOrNull { it.optString("key") in aliases }
    return (stat?.opt("value")?.toString() ?: "—") + if(key=="runs" && row.optBoolean("not_out")) "*" else ""
}
@Composable private fun SportsTable(profile:JSONObject,records:List<JSONObject>,skill:String,haptics:Boolean,url:(String)->Unit) {
    val columns=sportsColumns(profile.optString("sport"),skill)
    val view=LocalView.current
    Row(Modifier.fillMaxWidth().padding(top=14.dp,bottom=10.dp)) {
        Text(if(profile.optString("sport")=="racing") "Race" else "Date · Opponent",color=Muted,fontSize=10.sp,modifier=Modifier.weight(1f))
        columns.forEach { Text(it.label,color=Muted,fontSize=9.sp,textAlign=TextAlign.End,modifier=Modifier.width(it.width.dp)) }
    }
    HorizontalDivider(color=Line,thickness=.5.dp)
    records.forEach { record ->
        var expanded by remember(record.optString("id")) { mutableStateOf(false) }
        Column(Modifier.fillMaxWidth().animateContentSize().clickable { if(haptics)view.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK);expanded=!expanded }) {
            Row(Modifier.fillMaxWidth().padding(vertical=10.dp),verticalAlignment=Alignment.CenterVertically) {
                Column(Modifier.weight(1f).padding(end=9.dp)) {
                    Text(record.optString("opponent").ifBlank { record.optString("title") },color=White,fontSize=12.sp,maxLines=2,lineHeight=16.sp)
                    val day=try{java.time.LocalDate.parse(record.optString("date").take(10)).format(DateTimeFormatter.ofPattern("d MMM yyyy"))}catch(_:Exception){record.optString("date")}
                    Text(day,color=Muted,fontSize=9.sp,modifier=Modifier.padding(top=3.dp))
                    if(profile.optString("sport") in listOf("tennis","cricket")) Text(record.optString("subtitle"),color=Muted,fontSize=9.sp,maxLines=1,overflow=TextOverflow.Ellipsis)
                }
                columns.forEach { col -> Text(statValue(record,col.key),color=if(col.key=="result" && record.optString("result")=="W") Color(0xff84c5ab) else White,fontSize=if(col.key=="score" && profile.optString("sport")=="tennis") 10.sp else 12.sp,fontWeight=FontWeight.Medium,textAlign=TextAlign.End,modifier=Modifier.width(col.width.dp),style=androidx.compose.ui.text.TextStyle(fontFeatureSettings="tnum")) }
            }
            if(expanded) {
                Text(record.optString("subtitle"),color=Pale,fontSize=11.sp)
                ThreadModel.rows(record.optJSONArray("stats")).forEach { stat -> Row(Modifier.fillMaxWidth().padding(vertical=5.dp)){Text(stat.optString("label"),color=Muted,fontSize=12.sp,modifier=Modifier.weight(1f));Text(stat.optString("value"),color=White,fontSize=12.sp)} }
                if(record.optString("url").isNotBlank())TextButton(onClick={url(record.optString("url"))}){Text("Match source",fontSize=12.sp)}
            }
            HorizontalDivider(color=Line,thickness=.5.dp)
        }
    }
}

@Composable private fun MatchRow(record: JSONObject, url: (String) -> Unit) {
    var expanded by remember(record.optString("id")) { mutableStateOf(false) }
    val stats = ThreadModel.rows(record.optJSONArray("stats"))
    Column(Modifier.fillMaxWidth().animateContentSize().clickable { expanded = !expanded }) {
        Row(Modifier.fillMaxWidth().padding(vertical = 13.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(formatDate(record.optString("date")), fontSize = 10.sp, color = Muted)
                Spacer(Modifier.height(5.dp)); Text(record.optString("opponent").ifBlank { record.optString("title") }, fontSize = 14.sp, color = White, maxLines = 2)
                if (expanded) Text(record.optString("subtitle"), color = Muted, fontSize = 11.sp)
            }
            Spacer(Modifier.width(10.dp)); Text(record.optString("score", "—"), fontSize = 19.sp, color = White, fontWeight = FontWeight.Medium)
            Spacer(Modifier.width(7.dp)); Icon(if (expanded) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, if (expanded) "Collapse game" else "Expand game", tint = Muted, modifier = Modifier.size(17.dp))
        }
        if (expanded) {
            stats.forEach { stat -> Row(Modifier.fillMaxWidth().padding(vertical = 6.dp)) { Text(stat.optString("label"), color = Muted, fontSize = 13.sp, modifier = Modifier.weight(1f)); Text(stat.optString("value"), color = White, fontSize = 13.sp) } }
            if (record.optString("url").isNotBlank()) TextButton(onClick = { url(record.optString("url")) }) { Text("Match source") }
        }
        HorizontalDivider(color = Line, thickness = .5.dp)
    }
}

@Composable private fun WeatherDetail(row: JSONObject) {
    Column {
        Text(row.optString("title"), fontSize = 34.sp, color = White)
        Text(listOf(row.optString("region"), row.optString("country")).filter { it.isNotBlank() }.joinToString(" · "), color = Muted, fontSize = 13.sp)
        Row(Modifier.fillMaxWidth().padding(vertical = 24.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
            Text("${row.opt("temperature")}°", fontSize = 82.sp, fontWeight = FontWeight.Light, letterSpacing = (-4).sp, color = White)
            Icon(if (row.optInt("code") <= 2) Icons.Outlined.WbSunny else Icons.Outlined.Cloud, null, tint = Pale, modifier = Modifier.size(74.dp))
        }
        Text(row.optString("condition"), fontSize = 24.sp, color = White); Spacer(Modifier.height(12.dp))
        Text("Humidity ${row.opt("humidity")}%     Wind ${row.opt("wind")} km/h", color = Muted, fontSize = 13.sp)
        SectionLabel("Forecast")
        ThreadModel.rows(row.optJSONArray("forecast")).forEach { day ->
            Row(Modifier.fillMaxWidth().padding(vertical = 13.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(formatDate(day.optString("date")), color = White, fontSize = 13.sp, modifier = Modifier.weight(1f))
                Text("${day.opt("rain")}% rain", color = Pale, fontSize = 12.sp, modifier = Modifier.padding(end = 20.dp))
                Text("${day.opt("high")}°  /  ${day.opt("low")}°", color = White, fontSize = 13.sp)
            }; HorizontalDivider(color = Line, thickness = .5.dp)
        }
    }
}

@Composable private fun DocumentDetail(doc: JSONObject) {
    Column {
        Text(doc.optString("title"), fontSize = 32.sp, lineHeight = 38.sp, color = White)
        if (doc.optString("summary").isNotBlank()) Text(doc.optString("summary"), color = Muted, modifier = Modifier.padding(top = 14.dp))
        ThreadModel.rows(doc.optJSONArray("blocks")).forEach { block ->
            SectionLabel(block.optString("heading")); Text(block.optString("text"), color = White)
            val entries = block.optJSONArray("items")
            if (entries != null) for (i in 0 until entries.length()) Row(Modifier.padding(vertical = 6.dp)) { Text("${i + 1}.", color = Pale, modifier = Modifier.width(28.dp)); Text(entries.optString(i), color = White) }
        }
        val columns = doc.optJSONArray("columns"); val rows = doc.optJSONArray("rows")
        if (columns != null && rows != null) Column(Modifier.horizontalScroll(rememberScrollState()).padding(top = 16.dp)) {
            Row { for (i in 0 until columns.length()) Text(columns.optString(i), Modifier.width(160.dp).padding(10.dp), color = Pale, fontSize = 13.sp) }
            for (r in 0 until rows.length()) Row { val row = rows.getJSONArray(r); for (c in 0 until row.length()) Text(row.optString(c), Modifier.width(160.dp).padding(10.dp), color = White, fontSize = 13.sp) }
        }
    }
}

@Composable private fun FlightDetail(row: JSONObject) {
    Group {
        Text(row.optString("airline", "Demo airline"), color = White, fontSize = 20.sp)
        Text(row.optString("flight_number"), color = Muted, fontSize = 12.sp); Spacer(Modifier.height(24.dp))
        Text("${row.optString("origin")}  →  ${row.optString("destination")}", fontSize = 26.sp, color = White)
        Spacer(Modifier.height(12.dp)); Text("${formatDate(row.optString("date"))} · ${row.optString("departure")}", color = Pale)
        Spacer(Modifier.height(24.dp)); HorizontalDivider(color = Line); Spacer(Modifier.height(14.dp))
        Text("${row.optString("currency", "INR")} ${row.opt("price")}", fontSize = 25.sp, color = White)
        Text("Fictional demo fare · not bookable", color = Muted, fontSize = 12.sp)
    }
}

@Composable private fun SettingsScreen(model: ThreadModel, permissions: () -> Unit, privacy: () -> Unit) {
    val context = LocalContext.current
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 25.dp), contentPadding = PaddingValues(top = 25.dp, bottom = 25.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { Text("Make yourself\nat home.", fontSize = 34.sp, lineHeight = 41.sp, color = White); Spacer(Modifier.height(15.dp)) }
        item { SectionLabel("Your phone, independent"); Group {
            Text("Task engine on this phone", color = White, fontSize = 21.sp)
            Text("No laptop or USB needed. Voice and AI requests use Wi-Fi or mobile data to reach Gemini. Saved results and notes stay here.", color = Muted, modifier = Modifier.padding(vertical = 10.dp))
            Text(if (model.phoneKeySaved) "Gemini key saved securely" else "Add your Gemini API key to get started", color = Pale, fontSize = 13.sp)
            OutlinedTextField(model.phoneKeyDraft, { model.phoneKeyDraft = it.take(256) }, singleLine = true,
                label = { Text(if (model.phoneKeySaved) "Replace API key" else "Gemini API key") },
                visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp).testTag("phone-api-key"))
            Text("Encrypted with Android Keystore. The key is never included in a shared result or the APK. Your API account's quota applies.", color = Muted, fontSize = 12.sp, modifier = Modifier.padding(vertical = 10.dp))
            HapticButton(if (model.phoneKeyBusy) "Saving…" else "Save key", primary = true, enabled = !model.phoneKeyBusy && model.phoneKeyDraft.isNotBlank(), haptics = model.haptics) { model.savePhoneKey() }
            if (model.phoneKeySaved) TextButton(onClick = { model.savePhoneKey(remove = true) }, enabled = !model.phoneKeyBusy) { Text("Remove saved key") }
            if (model.phoneSetupMessage.isNotBlank()) Text(model.phoneSetupMessage, color = Pale, fontSize = 13.sp)
        } }
        item { SectionLabel("Voice"); Group {
            listOf("Kore" to "Clear & composed", "Aoede" to "Warm & easy", "Puck" to "Bright & lively", "Charon" to "Low & measured").forEach { (name, subtitle) ->
                Row(Modifier.fillMaxWidth().heightIn(min = 58.dp).clickable(enabled = !model.ui.connected) { model.selectVoice(name) }, verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) { Text(name, color = White); Text(subtitle, color = Muted, fontSize = 12.sp) }; RadioButton(model.voice == name, onClick = { model.selectVoice(name) }, enabled = !model.ui.connected)
                }
            }
            if (model.ui.connected) Text("End the conversation to change voice.", color = Muted, fontSize = 12.sp)
        } }
        item { SectionLabel("Feel & feedback"); Group {
            SettingSwitch("Haptic feedback", "A light response to intentional actions", model.haptics) { model.preference("haptics", it) }
            HorizontalDivider(color = Line)
            SettingSwitch("Quiet acknowledgments", "A brief sound when you interrupt", model.acknowledgments) { model.preference("ack", it) }
            Text("Motion follows your Android animation settings.", color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 12.dp))
        } }
        item { SectionLabel("Connected apps"); Group {
            Text("Spotify", color = White, fontSize = 21.sp)
            Text(model.spotifyMessage, color = Muted, modifier = Modifier.padding(vertical = 10.dp))
            if (model.spotifyConnected) TextButton(onClick = model::disconnectSpotify) { Text("Disconnect Spotify") }
            else {
                Text("Developer setup · Register a Spotify app with the callback below. Playback needs Premium. Tokens stay in this app's memory; reconnect after the app process restarts.", color = Muted, fontSize = 12.sp)
                androidx.compose.foundation.text.selection.SelectionContainer { Text(model.spotifyRedirect, color = Pale, fontSize = 12.sp, modifier = Modifier.padding(vertical = 10.dp)) }
                OutlinedTextField(model.spotifyClientId, { model.spotifyClientId = it.take(32) }, singleLine = true, label = { Text("Spotify client ID") }, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(10.dp))
                HapticButton(if (model.spotifyBusy) "Connecting…" else "Connect Spotify", primary = true, enabled = !model.spotifyBusy, haptics = model.haptics) { model.connectSpotify { openUrl(context, it) } }
                TextButton(onClick = model::refreshSpotifyConnection) { Text("Check connection") }
                Text("Connecting ends the current voice session. Make a fresh music request after signing in.", color = Muted, fontSize = 12.sp)
            }
        } }
        item { SectionLabel("Permissions & connection"); Group {
            Text("Samsung Galaxy · Android", color = White); Text("Runs on this phone · internet for live AI", color = Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
            TextButton(onClick = permissions) { Text("Android app permissions") }
            TextButton(onClick = privacy) { Text("How your data is used") }
            Text("THREAD ${BuildConfig.VERSION_NAME} · Development build", color = Muted, fontSize = 11.sp)
        } }
    }
}

@Composable private fun SettingSwitch(label: String, detail: String, enabled: Boolean, change: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) { Text(label, color = White); Text(detail, color = Muted, fontSize = 11.sp) }; Switch(enabled, change)
    }
}

@Composable fun WidgetScreen(model: ThreadModel) {
    val context = LocalContext.current
    val existing = remember { model.widgetTargetId?.let { id -> context.getSharedPreferences("widgets", 0).getString("widget-$id", null)?.let(::JSONObject) } }
    var selected by remember { mutableStateOf(ThreadModel.rows(existing?.optJSONArray("results")).map { it.optString("id") }.toSet()) }
    var title by remember { mutableStateOf(existing?.optString("title") ?: "Your day") }
    var request by remember { mutableStateOf("") }
    var consentPrompt by remember { mutableStateOf(false) }
    fun createRequested() { model.sendText("Make a home-screen widget: " + request.trim()); request = "" }
    if (consentPrompt) AlertDialog(onDismissRequest = { consentPrompt = false }, title = { Text("Create with THREAD") }, text = { Text("Your request and relevant results go to Google Gemini over the internet. Public lookups use their named sources. No microphone recording is started here.") }, confirmButton = { TextButton(onClick = { model.preference("consent", true); consentPrompt = false; createRequested() }) { Text("Continue") } }, dismissButton = { TextButton(onClick = { consentPrompt = false }) { Text("Cancel") } })
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 25.dp), contentPadding = PaddingValues(top = 26.dp, bottom = 25.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("Made for\nyour home screen.", fontSize = 34.sp, lineHeight = 41.sp, color = White); Spacer(Modifier.height(14.dp)); Text("Ask THREAD to make a widget, or choose one or two results below.", color = Muted) }
        item {
            OutlinedTextField(request, { request = it.take(2000) }, Modifier.fillMaxWidth(), label = { Text("What should your widget show?") }, placeholder = { Text("Time in Manchester and Barcelona") }, minLines = 2, maxLines = 5, shape = RoundedCornerShape(22.dp))
            Spacer(Modifier.height(12.dp))
            HapticButton(if (model.ui.connecting || model.ui.mode == "Thinking") "Creating…" else "Create with THREAD", Icons.Outlined.Add, true, enabled = request.isNotBlank() && !model.ui.connecting, haptics = model.haptics, modifier = Modifier.fillMaxWidth()) { if (model.consent) createRequested() else consentPrompt = true }
            model.ui.error?.let { Text(it, color = Pale, fontSize = 12.sp, modifier = Modifier.padding(top = 12.dp)) }
            if (model.ui.caption.isNotBlank()) Text(model.ui.caption.takeLast(600), color = Muted, fontSize = 13.sp, modifier = Modifier.padding(top = 14.dp))
            HorizontalDivider(Modifier.padding(top = 20.dp, bottom = 8.dp), color = Line)
            Text("Or use saved results", color = Pale, fontSize = 15.sp)
        }
        item { OutlinedTextField(title, { title = it.take(60) }, Modifier.fillMaxWidth(), label = { Text("Widget name") }, singleLine = true, shape = RoundedCornerShape(22.dp)) }
        if (model.ui.results.none(::canMakeWidget)) item { Group { Text("Start with what matters to you.", color = White, fontSize = 20.sp); Spacer(Modifier.height(10.dp)); Text("Ask for your local weather, a player’s recent matches, a plan, or a topic you follow. You can turn the result into a widget.", color = Muted) } }
        items(model.ui.results.filter(::canMakeWidget).reversed(), key = { it.optString("id") }) { row ->
            Row(Modifier.fillMaxWidth().clickable { val id = row.optString("id"); selected = if (id in selected) selected - id else if (selected.size < 2) selected + id else selected }.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Checkbox(row.optString("id") in selected, null); Spacer(Modifier.width(9.dp)); Column(Modifier.weight(1f)) { Text(title(row), color = White, fontSize = 15.sp); Text(row.optString("source"), color = Muted, fontSize = 11.sp) }
            }
        }
        item { HapticButton("Preview widget", Icons.Outlined.Widgets, true, enabled = selected.isNotEmpty() && title.isNotBlank(), haptics = model.haptics, modifier = Modifier.fillMaxWidth()) { model.widget = JSONObject().put("title", title).put("results", org.json.JSONArray(model.ui.results.filter { it.optString("id") in selected })) } }
        if (model.widgetTargetId == null) item { HorizontalDivider(Modifier.padding(vertical = 12.dp), color = Line); Text("One tap to talk.", fontSize = 23.sp, color = White); Text("A quiet shortcut. The microphone starts only after you tap it.", color = Muted, modifier = Modifier.padding(vertical = 10.dp)); HapticButton("Add voice shortcut", Icons.Outlined.Mic, haptics = model.haptics) { android.appwidget.AppWidgetManager.getInstance(context).requestPinAppWidget(android.content.ComponentName(context, TalkWidget::class.java), null, null) } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun WidgetPreview(model: ThreadModel, config: JSONObject) {
    val context = LocalContext.current
    var requested by remember(config) { mutableStateOf(false) }
    var assetsReady by remember(config) { mutableStateOf(false) }
    LaunchedEffect(config) { withContext(Dispatchers.IO) { WidgetContent.cacheImages(context.applicationContext, config) }; assetsReady = true }
    ModalBottomSheet(onDismissRequest = { model.widget = null }, containerColor = Panel, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(25.dp)) {
            Text("Your widget", color = White, fontSize = 27.sp); Spacer(Modifier.height(8.dp)); Text("${config.optString("title")} · resizable", color = Muted)
            Spacer(Modifier.height(24.dp))
            key(config, assetsReady) { androidx.compose.ui.viewinterop.AndroidView(factory = { ThreadWidget.preview(it, config) }, modifier = Modifier.fillMaxWidth().height(if (ThreadModel.rows(config.optJSONArray("results")).all { it.optString("domain") == "world_clocks" } && (config.getJSONArray("results").getJSONObject(0).optJSONArray("items")?.length() ?: 0) <= 2) 224.dp else 370.dp)) }
            Spacer(Modifier.height(20.dp)); Text(when {
                ThreadModel.rows(config.optJSONArray("results")).all { it.optString("domain") == "world_clocks" } -> "Keeps time on your phone, even offline."
                ThreadModel.rows(config.optJSONArray("results")).all { it.optString("provenance") == "draft" } -> "Saved on this phone. Scroll through your content; tick checklist items from your home screen."
                else -> "Scroll for the full result. Tap to open details and sources. Refreshes directly from this phone when internet is available."
            }, color = Muted, fontSize = 12.sp)
            Spacer(Modifier.height(20.dp)); HapticButton(if (model.widgetTargetId != null) "Save widget" else if (requested) "Open home-screen confirmation" else "Add to home screen", if (model.widgetTargetId != null) Icons.Outlined.Check else Icons.Outlined.Add, true, haptics = model.haptics, modifier = Modifier.fillMaxWidth()) {
                val id = model.widgetTargetId
                if (id != null) { ThreadWidget.save(context, id, config); model.widget = null; model.onWidgetSaved?.invoke() }
                else requested = ThreadWidget.pin(context, config)
            }
            if (requested && model.widgetTargetId == null) Text("Finish adding it in your launcher.", color = Pale, fontSize = 12.sp, modifier = Modifier.padding(top = 12.dp))
            Spacer(Modifier.height(20.dp))
        }
    }
}

@Composable fun Group(content: @Composable ColumnScope.() -> Unit) = Surface(color = Panel.copy(alpha = .8f), shape = RoundedCornerShape(25.dp)) { Column(Modifier.fillMaxWidth().padding(21.dp), content = content) }
fun canMakeWidget(result: JSONObject) = result.optString("provenance") !in listOf("demo", "synthetic") && result.optString("domain") !in listOf("phone", "travel", "flights", "rooms", "device") && (result.optJSONArray("items")?.length() ?: 0) > 0
@Composable fun SectionLabel(text: String) { Text(text, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = Pale, modifier = Modifier.padding(top = 22.dp, bottom = 12.dp)) }

@Composable private fun RemotePortrait(url: String, modifier: Modifier) {
    val bitmap by produceState<ImageBitmap?>(null, url) {
        value = withContext(Dispatchers.IO) {
            try {
                val uri = Uri.parse(url)
                if (uri.scheme != "https" || uri.host != "a.espncdn.com") return@withContext null
                IMAGE_HTTP.newCall(Request.Builder().url(url).build()).execute().use { response ->
                    if (!response.isSuccessful || (response.body?.contentLength() ?: 0) > 4_000_000) null else response.body?.bytes()?.takeIf { it.size < 4_000_000 }?.let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }
                }
            } catch (_: Exception) { null }
        }
    }
    bitmap?.let { Image(it, null, modifier, contentScale = ContentScale.Fit) }
}
private val IMAGE_HTTP = OkHttpClient()
fun title(result: JSONObject) = result.optJSONArray("items")?.optJSONObject(0)?.optString("title")?.takeIf { it.isNotBlank() } ?: result.optString("domain", "Result").replaceFirstChar { it.uppercase() }
fun formatDate(value: String): String = try { OffsetDateTime.parse(value).atZoneSameInstant(java.time.ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("d MMM yyyy · HH:mm")) } catch (_: Exception) { try { java.time.LocalDate.parse(value.take(10)).format(DateTimeFormatter.ofPattern("d MMM yyyy")) } catch (_: Exception) { value } }
fun statusLabel(status: String) = mapOf("handed_off" to "Opened in Android", "completed" to "Completed", "prepared" to "Ready to review", "needs_permission" to "Permission needed", "needs_connection" to "Connect your account", "needs_device" to "Open a playback device", "partial" to "Partly completed", "cancelled" to "Cancelled", "running" to "Working", "ambiguous" to "Choose an app", "failed" to "Couldn’t complete", "unknown" to "Outcome not confirmed")[status] ?: status
fun domainIcon(domain: String): ImageVector = when (domain) { "sports" -> Icons.Outlined.SportsBasketball; "weather" -> Icons.Outlined.Cloud; "web", "research" -> Icons.Outlined.TravelExplore; "travel" -> Icons.Outlined.Flight; "phone" -> Icons.Outlined.PhoneAndroid; "calculate", "convert", "currency" -> Icons.Outlined.Calculate; "world_clocks", "clock" -> Icons.Outlined.Schedule; else -> Icons.Outlined.Article }
fun openUrl(context: Context, url: String) { try { val uri = Uri.parse(url); if (uri.scheme in listOf("https", "http") && !uri.host.isNullOrBlank() && uri.userInfo == null) context.startActivity(Intent(Intent.ACTION_VIEW, uri)) } catch (_: Exception) { } }
fun share(context: Context, result: JSONObject) {
    val text = buildString {
        appendLine(title(result)); appendLine()
        if (result.optString("provenance") in listOf("draft", "demo")) appendLine(result.optString("provenance").uppercase())
        ThreadModel.rows(result.optJSONArray("items")).forEach { item ->
            appendLine(item.optString("title"))
            item.optJSONObject("document")?.let { doc ->
                ThreadModel.rows(doc.optJSONArray("blocks")).forEach { block -> appendLine(block.optString("heading")); appendLine(block.optString("text")); val rows = block.optJSONArray("items"); if (rows != null) for (i in 0 until rows.length()) appendLine("• ${rows.optString(i)}"); appendLine() }
            }
            ThreadModel.rows(sportProfile(item).optJSONArray("records")).forEach { record -> appendLine("${formatDate(record.optString("date"))} · ${record.optString("title")} · ${record.optString("score")}") }
            for (key in listOf("body", "detail", "summary", "condition", "url")) if (item.optString(key).isNotBlank()) appendLine(item.optString(key))
            if (item.has("value")) appendLine(item.opt("value"))
            if (item.has("temperature")) appendLine("${item.opt("temperature")} °C · wind ${item.opt("wind")} km/h")
            appendLine()
        }
        appendLine("Source: ${result.optString("source")}"); appendLine("Retrieved: ${formatDate(result.optString("retrieved_at"))}")
    }
    context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), "Share result"))
}

fun sportProfile(item: JSONObject): JSONObject {
    if (!item.has("matches")) return item
    val profile = JSONObject(item.toString()).put("coverage", item.optString("scope")).put("sport", "soccer").put("sport_label", "Football")
    val matches = ThreadModel.rows(item.optJSONArray("matches"))
    val metrics = org.json.JSONArray()
    for (key in listOf("goals", "assists")) if (!item.isNull(key)) metrics.put(JSONObject().put("label", key.replaceFirstChar { it.uppercase() }).put("value", item.opt(key)))
    profile.put("metrics", metrics)
    profile.put("records", org.json.JSONArray(matches.map { match ->
        val stats = org.json.JSONArray()
        for (key in listOf("goals", "assists", "shots", "minutes")) if (match.has(key) && !match.isNull(key)) stats.put(JSONObject().put("label", key.replaceFirstChar { it.uppercase() }).put("value", match.opt(key)))
        val penalties = if (!match.isNull("home_penalties") && !match.isNull("away_penalties")) " · penalties ${match.opt("home_penalties")}–${match.opt("away_penalties")}" else ""
        JSONObject().put("id", match.optString("id")).put("date", match.optString("date")).put("title", "${match.optString("home")} · ${match.optString("away")}")
            .put("opponent", if (match.optString("home") == item.optString("team")) match.optString("away") else if (match.optString("away") == item.optString("team")) match.optString("home") else "${match.optString("home")} · ${match.optString("away")}")
            .put("opponent_logo", if (match.optString("home") == item.optString("team")) match.optString("away_logo") else match.optString("home_logo"))
            .put("venue", if (match.optString("home") == item.optString("team")) "Home" else if (match.optString("away") == item.optString("team")) "Away" else "")
            .put("score", "${match.opt("home_score")} – ${match.opt("away_score")}").put("subtitle", match.optString("competition") + penalties).put("url", match.optString("url")).put("stats", stats)
    }))
    if (matches.isNotEmpty()) profile.put("latest_record_at", matches.first().optString("date"))
    return profile
}
