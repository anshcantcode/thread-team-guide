import {NativeVoice} from './live-audio.js';
import {KitchenStore} from './fdb3-store.js';
import {createOrb} from './orb.js';
import {intentView, renderIntentCard} from './fdb3-intent.js';
const $ = id => document.getElementById(id);
let store, connected = false, voiceState = 'idle', moodUntil = 0;
// The orb and the "what THREAD is doing" card show only real events: voice state, the controller's own decisions
// (forwarded by the host), and receipts the browser itself produced when it executed a checklist change.
const orb = createOrb($('orb'), {theme: 'auto', image: '/static/images/thread-sphere.png', scale: .92});
const intent = intentView();
function mood(name, ms) { orb.setMood(name); moodUntil = performance.now() + ms; }
function orbPhase() {
  if (!connected) return voiceState === 'connecting' ? 'connecting' : 'idle';
  const now = intent.state();
  if (voiceState === 'speaking') return 'speaking';
  if (voiceState === 'listening') return 'listening';
  if (voiceState === 'thinking') return 'hesitating';
  if (now?.stage === 'held') return 'held';
  if (now?.stage === 'sending') return 'working';
  return 'listening';
}
function renderIntent() { renderIntentCard(intent, document); orb.setPhase(orbPhase()); }
function status(text) { $('status').textContent = text; }
// Item id -> checked, as last shown. Only items the store really added or toggled since then animate.
const CORRECTION_CUE = /\b(?:actually|no,? wait|i mean|instead|scratch that|make (?:it|that)|change (?:it|that) to)\b/gi;
let shown = null;
function render() {
  const saved = store.read(); $('items').replaceChildren();
  const next = new Map();
  for (const row of saved.items) {
    const item = document.createElement('li'); item.textContent = `${row.checked ? '✓' : '○'} ${row.text}`;
    const moved = !shown ? '' : !shown.has(row.item_id) ? 'arrived' : shown.get(row.item_id) !== row.checked ? 'toggled' : '';
    item.className = [row.checked ? 'done' : '', moved].filter(Boolean).join(' ');
    next.set(row.item_id, row.checked); $('items').append(item);
  }
  shown = next;
  if (!saved.items.length) { const item = document.createElement('li'); item.textContent = 'No saved steps yet.'; $('items').append(item); }
  $('receipt').textContent = saved.last_receipt?.detail || 'No action receipt yet.';
}
function controls(ready) {
  connected = ready; $('talk').disabled = ready; $('type').disabled = ready; $('end').disabled = !ready; $('send').disabled = !ready;
}
const voice = new NativeVoice({
  state(value) { voiceState = value; if (value === 'connected') controls(true); if (value === 'idle') controls(false); orb.setPhase(orbPhase()); status({connecting:'Connecting to the host…', connected:'Connected', listening:'Listening', thinking:'Working on your request', speaking:'THREAD is speaking', idle:'Disconnected. Saved checklist retained.'}[value] || value); },
  error: status, backchannel: () => false, latency: () => {},
  open() { voice.send({type:'hello',client:'browser',session_id:store.sessionId,input_token:store.inputToken}); },
  prepareInput(event) {
    if (['latency','resume_after_noise','continue_after_noise'].includes(event.type)) return null;
    if (event.type === 'text' || event.type === 'speech_start') {
      try { event.input_token = store.newInput(); }
      catch (error) { void voice.stop().then(() => status(error.message)); return null; }
    }
    if (event.type === 'playback') { event.seconds = (event.played_ms || 0) / 1000; event.interrupted = event.status === 'interrupted'; }
    return event;
  },
  caption(event) {
    // Your own correction wording is marked as you say it; text is inserted as text nodes, never parsed as HTML.
    const box = $('captions'), text = String(event.text ?? ''); box.replaceChildren(`${event.role === 'user' ? 'You' : 'THREAD'}: `);
    let last = 0;
    if (event.role === 'user') for (const hit of text.matchAll(CORRECTION_CUE)) {
      const mark = document.createElement('mark'); mark.className = 'cue'; mark.textContent = hit[0];
      box.append(text.slice(last, hit.index), mark); last = hit.index + hit[0].length;
    }
    box.append(text.slice(last));
  },
  interrupted: () => orb.pulse('interrupt'),
  message(event) {
    if (event.type === 'controller') {
      const change = intent.controller(event);
      if (change === 'withdrawn') orb.pulse('correction');
      if (change === 'asked') mood('curious', 6000);
      renderIntent();
    }
    if (event.type === 'receipt') {
      const ok = intent.receipt(event);
      if (ok === true) { orb.pulse('done'); mood('pleased', 4000); }
      if (ok === false) { orb.pulse('error'); mood('apologetic', 5000); }
      renderIntent();
    }
    if (event.type === 'live_error') { orb.pulse('error'); mood('apologetic', 5000); }
    if (event.type === 'tool_request') {
      const result = store.execute(event);
      voice.send({type:'tool_result',request_id:event.request_id,session_id:store.sessionId,input_token:event.input_token,result}); render();
    }
  }
});
async function connect(microphone) {
  $('talk').disabled = true; $('type').disabled = true; $('end').disabled = false;
  try { store.newInput(); await voice.connect('', 'Kore', microphone, '/voice'); }
  catch (error) { controls(false); status(error.message); }
}
$('talk').onclick = () => connect(true); $('type').onclick = () => connect(false);
$('end').onclick = async () => { try { store.newInput(); } finally { await voice.stop(); controls(false); } };
$('request').onsubmit = event => {
  event.preventDefault(); const text = $('message').value.trim();
  if (!connected || !text) return; voice.send({type:'text',text}); $('message').value = ''; status('Working on your request…');
};
$('export').onclick = () => {
  const exported = store.read(); delete exported.input_token;
  const url = URL.createObjectURL(new Blob([JSON.stringify(exported,null,2)],{type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'THREAD-kitchen-checklist.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
};
addEventListener('pagehide', () => { try { if (store) store.newInput(); } finally { void voice.stop(); } });
addEventListener('storage', () => { if (store) { void voice.stop(); controls(false); render(); status('Another tab changed the checklist session. Reconnect to continue.'); } });
function animate() {
  const level = voice.levels(); $('level').style.transform = `scaleX(${level})`; orb.setLevel(level);
  if (moodUntil && performance.now() > moodUntil) { orb.setMood('neutral'); moodUntil = 0; }
  requestAnimationFrame(animate);
}
try {
  store = new KitchenStore(); render(); animate();
  const response = await fetch('/api/status'); const info = await response.json();
  if (!response.ok || info.available === false) { $('talk').disabled = true; $('type').disabled = true; status(info.detail || info.details || 'Host is not ready. Complete its local model setup first.'); }
  else status('Host ready. Connect to start.');
} catch (error) { $('talk').disabled = true; $('type').disabled = true; status(error.message); }
