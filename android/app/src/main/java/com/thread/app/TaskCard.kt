package com.thread.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject

fun hasTask(ui: ThreadState) = !ui.task?.optString("domain").isNullOrBlank() || ui.activeAction != null

fun taskHeading(ui: ThreadState): String {
    ui.activeAction?.let { return it.optString("title", "Your latest action") }
    val task = ui.task ?: return "Your latest action"
    val slots = task.optJSONObject("slots") ?: JSONObject()
    return if (slots.has("origin") && slots.has("destination")) "${slots.optString("origin")} → ${slots.optString("destination")}"
    else task.optJSONObject("capability")?.optString("title")?.takeIf { it.isNotBlank() } ?: "Your latest action"
}

fun taskStatus(ui: ThreadState): String {
    ui.activeAction?.let { return if (!ui.connected && it.optString("status") == "running") "Saved · outcome not confirmed" else statusLabel(it.optString("status")) }
    val task = ui.task ?: return "Action receipt"
    val operations = ThreadModel.rows(task.optJSONArray("operations"))
    return when {
        !ui.connected -> "Saved task"
        task.optBoolean("ended") -> "Task ended"
        task.optBoolean("paused") -> "Paused · details kept"
        task.optBoolean("understanding") || task.optBoolean("floor_held") -> "Checking your update"
        (task.optJSONArray("unresolved")?.length() ?: 0) > 0 -> "Action outcome unresolved"
        operations.any { it.optString("status") == "prepared" } -> "Action prepared"
        operations.any { it.optString("status") == "running" } -> "Working on your request"
        else -> "Current task"
    }
}

@Composable fun ActiveTaskCard(model: ThreadModel) {
    val ui = model.ui
    Surface(color = Panel, shape = RoundedCornerShape(22.dp), modifier = Modifier.fillMaxWidth().testTag("active-task").clickable { model.taskExpanded = true }) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.AccountTree, null, tint = Pale, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(10.dp))
                Text(taskHeading(ui), color = White, fontSize = 16.sp, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Icon(Icons.Outlined.ChevronRight, "Task details", tint = Muted)
            }
            Spacer(Modifier.height(7.dp))
            Text(taskStatus(ui), color = Pale, fontSize = 12.sp)
            if (ui.activeAction == null && ui.changedSlots.isNotEmpty()) Text("Updated ${ui.changedSlots.joinToString { it.replace('_', ' ') }}", color = Muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            else if (ui.taskNotice.isNotBlank()) Text(ui.taskNotice, color = Muted, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun TaskSheet(model: ThreadModel) {
    val ui = model.ui
    val task = ui.task ?: JSONObject()
    val slots = ui.activeAction?.optJSONObject("arguments") ?: task.optJSONObject("slots") ?: JSONObject()
    ModalBottomSheet(onDismissRequest = { model.taskExpanded = false }, containerColor = Panel, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp).testTag("task-details")) {
            Text(taskHeading(ui), fontSize = 28.sp, color = White)
            Spacer(Modifier.height(8.dp)); Text(taskStatus(ui), color = Pale)
            if (ui.taskNotice.isNotBlank()) { Spacer(Modifier.height(14.dp)); Text(ui.taskNotice, color = Muted) }
            Spacer(Modifier.height(18.dp))
            slots.keys().asSequence().toList().forEach { key ->
                Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                    Column(Modifier.weight(1f)) {
                        Text(key.replace('_', ' ').replaceFirstChar { it.uppercase() }, color = Muted, fontSize = 12.sp)
                        Text(slots.opt(key).toString(), color = White, modifier = Modifier.padding(top = 3.dp))
                    }
                    if (ui.activeAction == null && key in ui.changedSlots) Text("Changed", color = Pale, fontSize = 11.sp)
                    else if (ui.activeAction == null && ui.changedSlots.isNotEmpty()) Text("Kept", color = Muted, fontSize = 11.sp)
                }
            }
            if (ui.activeAction == null) task.optJSONObject("selection")?.let { Spacer(Modifier.height(12.dp)); Text("Selected · ${it.optString("title")}", color = White) }
            ui.activeAction?.let { action ->
                if (action.optString("detail").isNotBlank()) Text(action.optString("detail"), color = Muted, modifier = Modifier.padding(vertical = 12.dp))
                ThreadModel.rows(action.optJSONArray("steps")).forEach { step -> Text("${statusLabel(step.optString("status"))} · ${step.optString("label")}", color = Pale, modifier = Modifier.padding(top = 8.dp)) }
                if (action.optString("status") == "needs_connection") HapticButton("Connect Spotify", primary = true, haptics = model.haptics) { model.taskExpanded = false; model.route = "settings" }
            }
            val operations = if (ui.activeAction == null) ThreadModel.rows(task.optJSONArray("operations")).takeLast(5) else emptyList()
            if (operations.isNotEmpty()) {
                HorizontalDivider(Modifier.padding(vertical = 18.dp), color = Line)
                Text("Work & outcomes", color = White, fontWeight = FontWeight.Medium)
                operations.forEach { operation ->
                    val label = when (operation.optString("status")) {
                        "not_submitted" -> "Stopped before submission"
                        "cancelled" -> "Cancelled"
                        "unknown" -> "Outcome unresolved"
                        else -> operation.optString("status").replace('_', ' ').replaceFirstChar { it.uppercase() }
                    }
                    Text("${operation.optString("purpose").replaceFirstChar { it.uppercase() }} · $label", color = Muted, modifier = Modifier.padding(top = 10.dp))
                    operation.optString("confirmed_reference").takeIf { it.isNotBlank() }?.let { Text("Reference $it", color = Pale, fontSize = 12.sp) }
                }
            }
            if (ui.connected && ui.activeAction == null) {
                Spacer(Modifier.height(22.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    HapticButton(if (task.optBoolean("paused")) "Resume task" else "Pause task", haptics = model.haptics, modifier = Modifier.weight(1f)) { model.controlTask(if (task.optBoolean("paused")) "resume" else "pause") }
                    HapticButton("Stop work", haptics = model.haptics, modifier = Modifier.weight(1f)) { model.controlTask("stop_work") }
                }
                Text("Stopping work keeps actions already submitted. Their outcomes remain visible.", color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 12.dp))
            } else if (ui.connected && ui.activeAction?.optString("status") == "running") {
                Spacer(Modifier.height(18.dp)); HapticButton("Stop remaining steps", haptics = model.haptics) { model.controlTask("stop_work") }
            } else Text("This card records the task state. A new action needs a fresh request.", color = Muted, modifier = Modifier.padding(top = 16.dp))
            Spacer(Modifier.height(24.dp))
        }
    }
}
