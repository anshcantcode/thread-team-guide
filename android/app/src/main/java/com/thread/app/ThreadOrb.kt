package com.thread.app

import android.graphics.RuntimeShader
import android.os.Build
import android.provider.Settings
import androidx.annotation.RequiresApi
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ShaderBrush
import androidx.compose.ui.platform.LocalContext
import androidx.compose.runtime.withFrameNanos

/** THREAD's acoustic sphere, alive. Every phase and pulse is reported by real controller/audio events. */
enum class OrbPhase { Idle, Connecting, Listening, Hesitating, Thinking, Working, Speaking, Held, Error, Muted }
enum class OrbMood { Neutral, Curious, Focused, Pleased, Apologetic }

private class OrbPreset(val amp: Float, val speed: Float, val twist: Float, val energy: Float, val col: Color, val rim: Color)

private val PRESETS = mapOf(
    OrbPhase.Idle to OrbPreset(.10f, .30f, 0f, .48f, Color(.36f, .62f, 1f), Color(.15f, .45f, .98f)),
    OrbPhase.Connecting to OrbPreset(.18f, .55f, .3f, .58f, Color(.42f, .66f, 1f), Color(.18f, .48f, .98f)),
    OrbPhase.Listening to OrbPreset(.22f, .75f, 0f, .86f, Color(.50f, .80f, 1f), Color(.20f, .56f, 1f)),
    OrbPhase.Hesitating to OrbPreset(.15f, .42f, 0f, .72f, Color(.62f, .85f, 1f), Color(.22f, .58f, 1f)),
    OrbPhase.Thinking to OrbPreset(.34f, 1.15f, 1f, .92f, Color(.68f, .62f, 1f), Color(.34f, .43f, 1f)),
    OrbPhase.Working to OrbPreset(.28f, .95f, .45f, .92f, Color(.52f, .73f, 1f), Color(.22f, .50f, 1f)),
    OrbPhase.Speaking to OrbPreset(.36f, 1.35f, 0f, 1.1f, Color(.58f, .86f, 1f), Color(.26f, .62f, 1f)),
    OrbPhase.Held to OrbPreset(.22f, .60f, 0f, .92f, Color(1f, .76f, .36f), Color(.96f, .62f, .22f)),
    OrbPhase.Error to OrbPreset(.10f, .25f, 0f, .60f, Color(1f, .52f, .50f), Color(.86f, .32f, .30f)),
    OrbPhase.Muted to OrbPreset(.06f, .18f, 0f, .36f, Color(.56f, .61f, .71f), Color(.36f, .42f, .52f)),
)

/** Look (highlight drift), lookY, warmth, energy and amplitude multipliers for each mood. */
private val MOODS = mapOf(
    OrbMood.Neutral to floatArrayOf(0f, 0f, 0f, 1f, 1f),
    OrbMood.Curious to floatArrayOf(.32f, .04f, 0f, 1.04f, 1.05f),
    OrbMood.Focused to floatArrayOf(0f, 0f, 0f, 1.1f, .82f),
    OrbMood.Pleased to floatArrayOf(.08f, .03f, .55f, 1.08f, 1.05f),
    OrbMood.Apologetic to floatArrayOf(-.1f, -.12f, 0f, .76f, .8f),
)

/** Pure mapping from the app's observable state to an orb phase (unit-tested). */
fun orbPhaseFor(connected: Boolean, connecting: Boolean, muted: Boolean, error: Boolean, mode: String, acting: Boolean): OrbPhase = when {
    error -> OrbPhase.Error
    !connected -> if (connecting) OrbPhase.Connecting else OrbPhase.Idle
    mode.startsWith("Speaking") -> OrbPhase.Speaking
    mode.startsWith("Paused") -> OrbPhase.Held
    muted || mode == "Muted" -> OrbPhase.Muted
    acting || mode.startsWith("Working") -> OrbPhase.Working
    mode.startsWith("Thinking") -> OrbPhase.Thinking
    else -> OrbPhase.Listening
}

private const val ORB_AGSL = """
uniform float2 uRes;
uniform float uTime;
uniform float uLevel;
uniform float uAmp;
uniform float uSpeed;
uniform float uTwist;
uniform float uEnergy;
uniform float uRipple;
uniform float uFlash;
uniform float uDuck;
uniform float uWarm;
uniform float uDark;
uniform float uScale;
uniform float3 uCol;
uniform float3 uRim;
uniform float3 uFlashCol;
uniform float2 uLook;
float ribbon(float2 q, float A, float f, float ph, float w, float bend) {
  float env = pow(max(cos(q.x * 1.5707963), 0.0), 0.9);
  float y = A * env * sin(f * q.x + ph) + bend * env * q.x * 0.15;
  float d = abs(q.y - y);
  return exp(-(d * d) / (w * w)) + exp(-d / (w * 5.0)) * 0.22;
}
half4 main(float2 fragCoord) {
  float m = min(uRes.x, uRes.y);
  float2 uv = (float2(fragCoord.x, uRes.y - fragCoord.y) - 0.5 * uRes) / (0.5 * m) / uScale;
  float R = 0.78 * (1.0 - 0.07 * uDuck);
  float r = length(uv);
  float px = 3.0 / (m * uScale);
  float inside = 1.0 - smoothstep(R - px, R + px, r);
  float n = clamp(r / R, 0.0, 1.0);
  float3 body = float3(0.012, 0.034, 0.105);
  body += uRim * 0.62 * pow(n, 2.6);
  body += uRim * 0.30 * smoothstep(0.25, -0.95, uv.y) * (1.0 - n * 0.25);
  float neb = sin(uv.x * 2.6 + uTime * 0.17) * sin(uv.y * 3.4 - uTime * 0.13) + sin((uv.x + uv.y) * 4.1 + uTime * 0.11);
  body += uRim * 0.045 * (neb + 1.5) * (1.0 - n * 0.5);
  float2 q = uv / R;
  float tw = uTwist * 0.55 * sin(uTime * 0.9);
  float c = cos(tw); float s = sin(tw);
  q = float2(c * q.x - s * q.y, s * q.x + c * q.y);
  float A = (0.20 + 0.30 * uAmp + 0.55 * uLevel) * (1.0 - 0.85 * uDuck);
  float t = uTime * uSpeed;
  float th = ribbon(q + float2(0.0, 0.04), A, 2.8, t, 0.016, 0.0);
  th += ribbon(q + float2(0.0, -0.06), A * 0.85, 2.1, -t * 0.72 + 1.9, 0.012, 0.5) * 0.85;
  th += ribbon(q, A * 0.70, 3.9, t * 1.27 + 3.3 + uTwist * 1.6 * sin(t * 0.6), 0.011, -0.4) * 0.75;
  th += ribbon(q + float2(0.0, 0.22 - uLook.y), A * 1.45, 1.25, -t * 0.38 + 4.6, 0.018, 0.9) * 0.55;
  th *= inside * (0.62 + 0.7 * uEnergy) * smoothstep(1.0, 0.80, length(q));
  float3 thread = mix(uCol, float3(1.0), 0.38) * th;
  float rim1 = exp(-pow((r - R) / (px * 1.5), 2.0));
  float rim2 = exp(-pow((r - (R - 0.03)) / (px * 2.0), 2.0)) * 0.30;
  float ang = atan(uv.y, uv.x);
  float da = ang - (0.80 + uLook.x);
  da = mod(da + 3.14159265, 6.2831853) - 3.14159265;
  float hl = exp(-da * da / 0.13) * exp(-pow((r - (R - 0.02)) / 0.045, 2.0)) * 1.15;
  float ring = 0.0;
  if (uRipple < 1.0) { float rr = R * (0.15 + uRipple * 1.05); ring = exp(-pow((r - rr) / 0.025, 2.0)) * (1.0 - uRipple) * inside; }
  float fring = 0.0;
  if (uFlash < 1.3) { float fr = R * (0.2 + uFlash * 0.95); fring = exp(-pow((r - fr) / 0.04, 2.0)) * (1.0 - uFlash / 1.3); }
  float3 color = body * inside + thread;
  color += uRim * rim1 * 1.25 * (0.7 + 0.5 * uEnergy) + uRim * rim2;
  color += float3(0.86, 0.94, 1.0) * hl * (0.85 + 0.3 * uEnergy);
  color += float3(0.95, 0.98, 1.0) * ring * 0.9;
  color += uFlashCol * fring * 1.1 * inside;
  color = mix(color, color * float3(1.18, 1.0, 0.82) + float3(0.04, 0.02, 0.0), uWarm * inside);
  float a = max(inside, rim1);
  float out_ = max(r - R, 0.0);
  float halo = exp(-out_ * mix(11.0, 7.5, uDark)) * (1.0 - inside) * (0.30 + 0.35 * uEnergy + 0.4 * uLevel);
  float2 sp = uv - float2(0.0, -R * 0.10);
  float sh = exp(-max(length(sp * float2(1.0, 1.35)) - R * 0.88, 0.0) * 5.0) * (1.0 - inside) * 0.22;
  color += uRim * halo * mix(0.45, 1.0, uDark) + uFlashCol * fring * (1.0 - inside) * 0.6;
  a = clamp(a + halo * mix(0.38, 0.9, uDark) + fring * (1.0 - inside) * 0.6 + sh * (1.0 - uDark), 0.0, 1.0);
  return half4(half3(color), half(a));
}
"""

private val RECEIPT = Color(.36f, .94f, .55f)
private val FAILURE = Color(1f, .42f, .40f)
private val CORRECTION = Color(1f, .74f, .30f)

/**
 * The living sphere. [interruptions], [receipts], [failures] and [corrections] are monotonically increasing counts
 * of real events; each increase plays its pulse once (barge-in ripple, receipt ring, failure ring, correction ring).
 * Android 13+ renders the shader; Android 12 falls back to the original sphere artwork.
 * [motionEnabled] lets non-activity surfaces react to changed system animation settings; false freezes time/pulses.
 */
@Composable
fun ThreadOrb(
    phase: OrbPhase, level: Float, modifier: Modifier = Modifier, mood: OrbMood = OrbMood.Neutral,
    interruptions: Int = 0, receipts: Int = 0, failures: Int = 0, corrections: Int = 0, dark: Boolean = true,
    scale: Float = .94f, motionEnabled: Boolean = true,
) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
        AcousticSphere(modifier, if (motionEnabled) level else 0f, motionEnabled && phase != OrbPhase.Idle)
        return
    }
    ShaderOrb(phase, level, modifier, mood, interruptions, receipts, failures, corrections, dark, scale, motionEnabled)
}

@RequiresApi(Build.VERSION_CODES.TIRAMISU)
@Composable
private fun ShaderOrb(
    phase: OrbPhase, level: Float, modifier: Modifier, mood: OrbMood, interruptions: Int, receipts: Int,
    failures: Int, corrections: Int, dark: Boolean, scale: Float, motionEnabled: Boolean,
) {
    val context = LocalContext.current
    val still = !motionEnabled || remember { Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }
    val shader = remember { runCatching { RuntimeShader(ORB_AGSL) }.getOrNull() }
    if (shader == null) { AcousticSphere(modifier, if (still) 0f else level, !still && phase != OrbPhase.Idle); return }
    val preset = PRESETS.getValue(phase)
    val m = MOODS.getValue(mood)
    val slow = tween<Float>(450); val quick = tween<Float>(220)
    val amp by animateFloatAsState(preset.amp * m[4], quick, label = "amp")
    val speed by animateFloatAsState(if (still) 0f else preset.speed, slow, label = "speed")
    val twist by animateFloatAsState(if (still) 0f else preset.twist, slow, label = "twist")
    val energy by animateFloatAsState(preset.energy * m[3], slow, label = "energy")
    val warm by animateFloatAsState(m[2], slow, label = "warm")
    val lookY by animateFloatAsState(m[1], slow, label = "lookY")
    // Fast attack, slower release: the threads follow speech without jitter.
    val voice by animateFloatAsState(if (still) level * .25f else level.coerceIn(0f, 1f), tween(90), label = "level")
    val col by animateColorAsState(preset.col, tween(450), label = "col")
    val rim by animateColorAsState(preset.rim, tween(450), label = "rim")
    val time by produceState(0f, still) {
        if (still) { value = 0f; return@produceState }
        var start = 0L
        while (true) withFrameNanos { now -> if (start == 0L) start = now; value = (now - start) / 1_000_000_000f }
    }
    var rippleAt by remember { mutableFloatStateOf(-10f) }
    var flashAt by remember { mutableFloatStateOf(-10f) }
    var flashColor by remember { androidx.compose.runtime.mutableStateOf(RECEIPT) }
    LaunchedEffect(interruptions) { if (interruptions > 0) rippleAt = time }
    LaunchedEffect(receipts) { if (receipts > 0) { flashAt = time; flashColor = RECEIPT } }
    LaunchedEffect(failures) { if (failures > 0) { flashAt = time; flashColor = FAILURE } }
    LaunchedEffect(corrections) { if (corrections > 0) { flashAt = time; flashColor = CORRECTION } }
    val ripple = if (still) 9f else (time - rippleAt) * 1.6f
    val duck = if (still) 0f else (1f - (time - rippleAt) * 2.6f).coerceIn(0f, 1f)
    val look = if (mood == OrbMood.Curious && !still) m[0] * kotlin.math.sin(time * .7f) else m[0]
    Canvas(modifier) {
        shader.setFloatUniform("uRes", size.width, size.height)
        shader.setFloatUniform("uTime", time)
        shader.setFloatUniform("uLevel", voice)
        shader.setFloatUniform("uAmp", amp)
        shader.setFloatUniform("uSpeed", speed)
        shader.setFloatUniform("uTwist", twist)
        shader.setFloatUniform("uEnergy", energy)
        shader.setFloatUniform("uRipple", ripple)
        shader.setFloatUniform("uFlash", if (still) 9f else time - flashAt)
        shader.setFloatUniform("uDuck", duck)
        shader.setFloatUniform("uWarm", warm)
        shader.setFloatUniform("uDark", if (dark) 1f else 0f)
        shader.setFloatUniform("uScale", scale)
        shader.setFloatUniform("uCol", col.red, col.green, col.blue)
        shader.setFloatUniform("uRim", rim.red, rim.green, rim.blue)
        shader.setFloatUniform("uFlashCol", flashColor.red, flashColor.green, flashColor.blue)
        shader.setFloatUniform("uLook", look, lookY)
        drawRect(ShaderBrush(shader))
    }
}
