package com.thread.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun HistoryScreen(model: ThreadModel) {
    val sessions = remember { model.loadSessionHistory() }
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 26.dp),
        contentPadding = PaddingValues(top = 28.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Text("Past conversations", fontSize = 34.sp, letterSpacing = (-.8).sp, color = White)
            Spacer(Modifier.height(8.dp))
            Text("What you talked about, kept on this phone.", color = Muted)
            Spacer(Modifier.height(18.dp))
        }
        if (sessions.isEmpty()) {
            item { Text("Nothing here yet — start a conversation, then tap \"New conversation\" and it'll show up here.", color = Muted) }
        }
        items(sessions) { session ->
            Surface(color = Panel.copy(alpha = .8f), shape = RoundedCornerShape(20.dp), modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text(session.optString("summary"), color = White, fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        java.text.SimpleDateFormat("MMM d, h:mm a").format(java.util.Date(session.optLong("endedAt"))),
                        color = Muted, fontSize = 12.sp
                    )
                }
            }
        }
    }
}