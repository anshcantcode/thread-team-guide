package com.thread.probe;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** Read-only shell-invoked observer. Uses framework APIs in its own process. */
public class ReleaseUiProbe extends Instrumentation {
    private final Set<String> labels = new HashSet<>(Arrays.asList("Start talking", "Mute", "Unmute", "End conversation", "End"));
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            JSONArray rows = new JSONArray();
            UiAutomation automation = getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            // Compose publishes its accessibility tree after service registration.
            // Retry fresh roots briefly; never use a cached file or wait for UI idle.
            for (int attempt = 0; attempt < 6 && rows.length() == 0; attempt++) {
                AccessibilityNodeInfo root = automation.getRootInActiveWindow();
                if (root != null) visit(root, rows);
                if (rows.length() == 0) SystemClock.sleep(150);
            }
            result.putString("thread_controls", rows.toString());
            finish(0, result);
        } catch (Exception error) {
            result.putString("probe_error", error.getClass().getSimpleName());
            finish(1, result);
        }
    }
    private void visit(AccessibilityNodeInfo node, JSONArray rows) throws JSONException {
        String text = String.valueOf(node.getText());
        String description = String.valueOf(node.getContentDescription());
        String label = labels.contains(text) ? text : (labels.contains(description) ? description : null);
        if ("com.thread.app".contentEquals(String.valueOf(node.getPackageName())) && node.isVisibleToUser() && label != null) {
            AccessibilityNodeInfo target = node;
            while (!target.isClickable() && target.getParent() != null) target = target.getParent();
            Rect bounds = new Rect(); target.getBoundsInScreen(bounds);
            if (target.isClickable() && target.isEnabled() && !bounds.isEmpty()) rows.put(new JSONObject().put("label", label)
                .put("bounds", "[" + bounds.left + "," + bounds.top + "][" + bounds.right + "," + bounds.bottom + "]"));
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) visit(child, rows);
        }
    }
}
