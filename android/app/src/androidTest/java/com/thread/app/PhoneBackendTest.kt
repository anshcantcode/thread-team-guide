package com.thread.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** No model calls. Exercises the actual packaged Python server in the Android process. */
@RunWith(AndroidJUnit4::class)
class PhoneBackendTest {
    @Test fun packagedBackendRequiresNativeCredentialAndRunsLocalCalculation() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertTrue(ThreadBackend.onPhone(context))
        val http = ThreadBackend.client(context, OkHttpClient.Builder().readTimeout(45, TimeUnit.SECONDS))
        val started = android.os.SystemClock.elapsedRealtime()
        fun get(path: String): JSONObject = http.newCall(Request.Builder().url(ThreadBackend.PHONE_ENDPOINT + path).build()).execute().use {
            assertEquals(200, it.code); JSONObject(it.body!!.string())
        }
        val config = get("/api/config")
        assertEquals("phone", config.getString("runtime"))
        assertEquals(ThreadBackend.hasKey(context), config.getBoolean("configured"))
        assertFalse(context.filesDir.resolve("phone-config-import.json").exists())
        val key = ThreadBackend.configuration(context).optString("THREAD_API_KEY")
        if (key.isNotEmpty()) {
            assertFalse("Configuration must not expose the API key", config.toString().contains(key))
            val encrypted = context.getSharedPreferences("backend-credentials", 0).getString("encrypted-config", "")!!
            assertTrue(encrypted.isNotEmpty())
            assertFalse("Saved preferences must not contain the plaintext key", encrypted.contains(key))
        }
        OkHttpClient().newCall(Request.Builder().url(ThreadBackend.PHONE_ENDPOINT + "/api/config").build()).execute().use { assertEquals(401, it.code) }
        val session = http.newCall(Request.Builder().url(ThreadBackend.PHONE_ENDPOINT + "/api/sessions")
            .post("{}".toRequestBody("application/json".toMediaType())).build()).execute().use {
                assertEquals(200, it.code); JSONObject(it.body!!.string()).getString("session_id")
            }
        for (path in listOf("/ws/", "/live/")) {
            val denied = CountDownLatch(1)
            var denial = 0
            val socket = OkHttpClient().newWebSocket(Request.Builder().url(ThreadBackend.PHONE_ENDPOINT.replace("http", "ws") + path + session).build(), object : WebSocketListener() {
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { denial = response?.code ?: 0; denied.countDown() }
                override fun onOpen(webSocket: WebSocket, response: Response) { denied.countDown() }
            })
            try { assertTrue(denied.await(10, TimeUnit.SECONDS)); assertEquals(403, denial) } finally { socket.cancel() }
        }
        val body = """{"modules":[{"id":"phone-calculator-test","domain":"calculate","arguments":{"expression":"17*19"}}]}"""
        val result = http.newCall(Request.Builder().url(ThreadBackend.PHONE_ENDPOINT + "/api/widgets/refresh")
            .post(body.toRequestBody("application/json".toMediaType())).build()).execute().use { assertEquals(200, it.code); JSONObject(it.body!!.string()) }
        val rows = result.getJSONArray("results")
        assertEquals(1, rows.length())
        assertEquals("323", rows.getJSONObject(0).getJSONArray("items").getJSONObject(0).getString("value"))
        val notebook = Python.getInstance().getModule("thread_agent.capabilities").get("Notebook")!!
        val localPath = notebook.call().get("path").toString()
        assertEquals(context.filesDir.resolve("backend/notebook.sqlite3").absolutePath, localPath)
        val report = JSONObject().put("passed", true).put("runtime", "phone").put("version", BuildConfig.VERSION_NAME)
            .put("pydantic_version", Python.getInstance().getModule("pydantic").get("VERSION").toString())
            .put("pydantic_compiled", Python.getInstance().getModule("pydantic").get("compiled").toString())
            .put("startup_and_checks_ms", android.os.SystemClock.elapsedRealtime() - started)
            .put("http_auth_required", true).put("websocket_auth_required", true).put("configured", config.getBoolean("configured"))
            .put("calculation", rows.getJSONObject(0)).put("notebook_private", true)
            .put("scope", "Packaged Python server, native authentication, encrypted key presence, offline calculator and private notebook location. No Gemini call or microphone claim.")
        context.filesDir.resolve("qa-phone-backend.json").writeText(report.toString(2))
    }

    @Test fun malformedDevelopmentImportPreservesWorkingCredentials() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = context.getSharedPreferences("backend-credentials", 0)
        val original = prefs.getString("encrypted-config", null)
        val before = ThreadBackend.configuration(context).toString()
        val imported = context.filesDir.resolve("phone-config-import.json")
        try {
            imported.writeText(JSONObject().put("THREAD_API_KEY", "nonsecret.test-key-for-validation").put("THREAD_MODEL", 123).toString())
            assertTrue("Invalid metadata must preserve the working configuration", before == ThreadBackend.configuration(context).toString())
            assertFalse(imported.exists())
            assertTrue("Invalid import must not overwrite encrypted preferences", original == prefs.getString("encrypted-config", null))
        } finally {
            imported.delete()
            prefs.edit().putString("encrypted-config", original).commit()
        }
    }
}
