import {NativeVoice} from './live-audio.js';
import {KitchenStore} from './fdb3-store.js';
const $ = id => document.getElementById(id);
let store, connected = false;
function status(text) { $('status').textContent = text; }
function render() {
  const saved = store.read(); $('items').replaceChildren();
  for (const row of saved.items) {
    const item = document.createElement('li'); item.textContent = `${row.checked ? '✓' : '○'} ${row.text}`;
    if (row.checked) item.className = 'done'; $('items').append(item);
  }
  if (!saved.items.length) { const item = document.createElement('li'); item.textContent = 'No saved steps yet.'; $('items').append(item); }
  $('receipt').textContent = saved.last_receipt?.detail || 'No action receipt yet.';
}
function controls(ready) {
  connected = ready; $('talk').disabled = ready; $('type').disabled = ready; $('end').disabled = !ready; $('send').disabled = !ready;
}
const voice = new NativeVoice({
  state(value) { if (value === 'connected') controls(true); if (value === 'idle') controls(false); status({connecting:'Connecting to the host…', connected:'Connected', listening:'Listening', thinking:'Working on your request', speaking:'THREAD is speaking', idle:'Disconnected. Saved checklist retained.'}[value] || value); },
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
  caption(event) { $('captions').textContent = `${event.role === 'user' ? 'You' : 'THREAD'}: ${event.text}`; },
  message(event) {
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
function animate() { $('level').style.transform = `scaleX(${voice.levels()})`; requestAnimationFrame(animate); }
try {
  store = new KitchenStore(); render(); animate();
  const response = await fetch('/api/status'); const info = await response.json();
  if (!response.ok || info.available === false) { $('talk').disabled = true; $('type').disabled = true; status(info.detail || info.details || 'Host is not ready. Complete its local model setup first.'); }
  else status('Host ready. Connect to start.');
} catch (error) { $('talk').disabled = true; $('type').disabled = true; status(error.message); }
