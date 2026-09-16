package com.thread.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import okhttp3.OkHttpClient
import org.json.JSONObject
import java.io.IOException
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** One private Python backend per app process. Startup runs on OkHttp's worker. */
object ThreadBackend {
    const val PHONE_ENDPOINT = "http://127.0.0.1:8767"
    private const val KEY_ALIAS = "thread-phone-credentials-v1"
    private val localToken = UUID.randomUUID().toString() + UUID.randomUUID().toString()
    private val runtimeLock = Any()
    private val credentialLock = Any()
    private var backend: PyObject? = null
    @Volatile private var ready = false

    fun onPhone(context: Context) = context.getSharedPreferences("thread", 0).getString("backend-mode", "phone") != "laptop"
    fun endpoint(context: Context): String = if (onPhone(context)) PHONE_ENDPOINT
        else context.getSharedPreferences("thread", 0).getString("endpoint", "http://127.0.0.1:8766") ?: "http://127.0.0.1:8766"
    fun spotifyRedirect(context: Context) = endpoint(context).trimEnd('/') + "/api/spotify/callback"

    fun client(context: Context, builder: OkHttpClient.Builder = OkHttpClient.Builder()): OkHttpClient {
        val app = context.applicationContext
        return builder.followRedirects(false).addInterceptor { chain ->
            val request = chain.request()
            val local = request.url.scheme == "http" && request.url.host == "127.0.0.1" && request.url.port == 8767
            val authenticated = request.newBuilder().removeHeader("X-Thread-Local")
            if (local) {
                ensureStarted(app)
                authenticated.header("X-Thread-Local", localToken)
            }
            chain.proceed(authenticated.build())
        }.build()
    }

    fun ensureStarted(context: Context) {
        if (ready) return
        synchronized(runtimeLock) {
            if (ready) return
            try {
                if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
                backend = Python.getInstance().getModule("thread_agent.android_backend")
                backend!!.callAttr("start", context.filesDir.absolutePath, configuration(context).toString(), localToken)
                ready = true
            } catch (_: Exception) {
                throw IOException("The on-phone task engine could not start. Close and reopen THREAD to try again.")
            }
        }
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
        }.generateKey()
    }

    private fun store(context: Context, config: JSONObject) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.doFinal(config.toString().toByteArray(Charsets.UTF_8))
        val value = Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + "." + Base64.encodeToString(encrypted, Base64.NO_WRAP)
        check(context.getSharedPreferences("backend-credentials", 0).edit().putString("encrypted-config", value).commit())
    }

    fun configuration(context: Context): JSONObject = synchronized(credentialLock) {
        // Optional development migration over adb stdin into app-private storage.
        // No secret in intents, logcat, source, resources, BuildConfig or the APK.
        val imported = context.filesDir.resolve("phone-config-import.json")
        if (BuildConfig.DEBUG && imported.isFile) {
            try {
                require(imported.length() <= 4096)
                val supplied = JSONObject(imported.readText())
                val config = JSONObject()
                for (name in listOf("THREAD_API_KEY", "THREAD_MODEL", "THREAD_LIVE_MODEL", "THREAD_TIMEZONE", "THREAD_LIVE_SEARCH")) {
                    if (!supplied.has(name)) continue
                    val value = supplied.get(name)
                    require(value is String && value.length <= 256 && '\n' !in value && '\r' !in value)
                    config.put(name, value)
                }
                val suppliedKey = config.optString("THREAD_API_KEY")
                require(Regex("[A-Za-z0-9_.-]{20,256}").matches(suppliedKey))
                store(context, config)
            } catch (_: Exception) {
                // Invalid development imports leave the existing encrypted key intact.
            } finally { imported.delete() }
        }
        val value = context.getSharedPreferences("backend-credentials", 0).getString("encrypted-config", null) ?: return@synchronized JSONObject()
        try {
            val parts = value.split('.', limit = 2)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(parts[0], Base64.DEFAULT)))
            }
            JSONObject(String(cipher.doFinal(Base64.decode(parts[1], Base64.DEFAULT)), Charsets.UTF_8))
        } catch (_: Exception) { JSONObject() }
    }

    fun hasKey(context: Context) = configuration(context).optString("THREAD_API_KEY").isNotBlank()

    fun saveKey(context: Context, value: String) {
        val trimmed = value.trim()
        require(trimmed.isEmpty() || Regex("[A-Za-z0-9_.-]{20,256}").matches(trimmed))
        synchronized(runtimeLock) {
            val config = synchronized(credentialLock) {
                configuration(context).put("THREAD_API_KEY", trimmed).also { store(context, it) }
            }
            backend?.callAttr("configure", config.toString())
        }
    }
}
