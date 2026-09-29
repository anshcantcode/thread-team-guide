package com.thread.probe;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.graphics.Bitmap;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Opt-in, emulator-only release smoke. No model, microphone, or app internals. */
public class KitchenReleaseProbe extends Instrumentation {
    private UiAutomation automation;
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            require("ranchu".equals(Build.HARDWARE) || "goldfish".equals(Build.HARDWARE), "Owned emulator required");
            ApplicationInfo installed = getContext().getPackageManager().getApplicationInfo("com.thread.app", 0);
            require((installed.flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0, "Install the minified release first");
            automation = getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            getContext().startActivity(new Intent().setClassName("com.thread.app", "com.thread.app.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
            click("Settings");
            click("Open Kitchen");
            waitFor("Checkpoint mode", false);
            waitFor("Disconnected.", false);
            waitFor("Connect without microphone", true);
            waitFor("Saved on this phone", true);
            Bitmap screenshot = automation.takeScreenshot();
            require(screenshot != null, "Screenshot unavailable");
            try (FileOutputStream out = new FileOutputStream(new File(getContext().getExternalFilesDir(null), "kitchen-release.png"))) {
                screenshot.compress(Bitmap.CompressFormat.PNG, 100, out);
            }
            screenshot.recycle();
            JSONObject evidence = new JSONObject().put("passed", true).put("variant", "minified release; not debuggable")
                .put("entry", "MainActivity > Settings > Open Kitchen")
                .put("checks", "real release launch, navigation, scoped Kitchen UI and disconnected controls")
                .put("microphone_requested", false).put("model_calls", 0)
                .put("scope", "UI smoke in a separate Java-only companion process; no app test keep rules or internal APIs");
            try (FileOutputStream out = new FileOutputStream(new File(getContext().getExternalFilesDir(null), "kitchen-release.json"))) {
                out.write(evidence.toString(2).getBytes(StandardCharsets.UTF_8));
            }
            result.putString("kitchen_release", evidence.toString());
            finish(0, result);
        } catch (Exception error) {
            result.putString("probe_error", error.toString());
            finish(1, result);
        }
    }
    private void require(boolean value, String detail) { if (!value) throw new IllegalStateException(detail); }
    private AccessibilityNodeInfo find(AccessibilityNodeInfo node, String label, boolean exact) {
        if (node == null) return null;
        String text = String.valueOf(node.getText()), description = String.valueOf(node.getContentDescription());
        boolean matches = exact ? (label.equals(text) || label.equals(description)) : (text.startsWith(label) || description.startsWith(label));
        if ("com.thread.app".contentEquals(String.valueOf(node.getPackageName())) && node.isVisibleToUser() && matches) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo found = find(node.getChild(i), label, exact);
            if (found != null) return found;
        }
        return null;
    }
    private AccessibilityNodeInfo waitFor(String label, boolean exact) {
        long deadline = SystemClock.elapsedRealtime() + 30000;
        AccessibilityNodeInfo node;
        do {
            node = find(automation.getRootInActiveWindow(), label, exact);
            if (node != null) return node;
            SystemClock.sleep(150);
        } while (SystemClock.elapsedRealtime() < deadline);
        throw new IllegalStateException("Control not visible: " + label);
    }
    private void click(String label) {
        AccessibilityNodeInfo node = waitFor(label, true);
        while (!node.isClickable() && node.getParent() != null) node = node.getParent();
        require(node.isEnabled() && node.performAction(AccessibilityNodeInfo.ACTION_CLICK), "Could not click: " + label);
    }
}
