package com.thread.app

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/** The launcher's real configure/reconfigure contract, independent of an active voice call. */
class WidgetConfigurationActivity : ComponentActivity() {
    private val model: ThreadModel by viewModels()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState); enableEdgeToEdge(); setResult(Activity.RESULT_CANCELED)
        val id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
        if (!ThreadWidget.owns(this, id)) { finish(); return }
        model.widgetTargetId = id
        model.deviceAction = { request ->
            if (request.optString("action") == "create_widget") PhoneActions(this) { model.widget = it }.execute(request)
            else PhoneActions.outcome("failed", "This screen edits a widget. Open a voice conversation for other phone actions.")
        }
        val current = getSharedPreferences("widgets", 0).getString("widget-$id", null)?.let(::JSONObject)
        current?.optJSONArray("results")?.let { results -> model.acceptSnapshot(JSONObject().put("workspace", results).put("transcript", org.json.JSONArray(model.ui.transcript)), persist = false) }
        model.onWidgetSaved = { setResult(Activity.RESULT_OK, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)); finish() }
        setContent {
            ThreadTheme {
                Surface(color = Ink, modifier = Modifier.fillMaxSize()) {
                    Column(Modifier.fillMaxSize().safeDrawingPadding()) {
                        TextButton(onClick = ::finish, modifier = Modifier.padding(start = 12.dp, top = 8.dp)) { Text("Close") }
                        WidgetScreen(model)
                    }
                }
                model.widget?.let { WidgetPreview(model, it) }
            }
        }
    }
}
