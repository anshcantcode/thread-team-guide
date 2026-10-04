import { renderWorkspace } from './workspace.js';
import { NativeVoice } from './live-audio.js';
import { asBase64 } from './audio.js';
import { createOrb } from './orb.js';
import { mountWatches } from './watches.js';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let socket, sessionId, state, config, events = [], toastTimer, callStarted = null, callState = 'idle';
let lastCaptionId = null, lastCaptionText = '', liveCaptions = new Map();
let orb = null, orbMoodUntil = 0, lastResultsId = null;
const WATCH_ACTIONS = new Set(['create_watch', 'stop_watch', 'check_watch_now', 'list_watches']);
let watches = null;
function toast(text) { $('toast-text').textContent = text; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 11000); }
$('toast-close').onclick = () => $('toast').hidden = true;
function send(type, text='', data={}) {
  if (socket?.readyState !== WebSocket.OPEN) { toast('The local session disconnected. Reload to reconnect.'); return; }
  socket.send(JSON.stringify({id:crypto.randomUUID(),type,text,data,seen_results:state?.results?.id || null}));
}
function control(action, data={}) { send('control','',{action,...data}); }
const voice = new NativeVoice({
  state: showVoiceState,
  error: toast,
  threshold: () => Number($('vad-threshold').value),
  backchannel: () => $('backchannel').checked,
  latency: ms => { $('latency').textContent = `${(ms/1000).toFixed(2)} s`; },
  interrupted: () => orb?.pulse('interrupt'),
  caption: event => {
    const {message_id:id,role,text} = event;
    liveCaptions.set(id,{id,role,text,source:'native_audio'});
    if (id !== lastCaptionId && lastCaptionText) $('previous-caption').textContent = lastCaptionText;
    lastCaptionId = id; lastCaptionText = text;
    $('caption-speaker').textContent = role === 'user' ? 'YOU' : 'THREAD';
    if (role !== 'user' && /\?\s*$/.test(text)) orbMood('curious', 6000);
    $('caption-text').textContent = text.length > 250 ? '…' + text.slice(-235).replace(/^\S*\s/,'') : text;
    renderTranscript();
  }
});
function showVoiceState(next) {
  callState = next;
  const connected = voice.ready;
  orb?.setPhase(orbPhase(next));
  document.body.dataset.voiceState = next;
  document.body.dataset.connected = String(connected);
  if (connected && !callStarted) callStarted = performance.now();
  if (next === 'idle') callStarted = null;
  $('control-dock').classList.toggle('connected',connected);
  $('mic').classList.toggle('muted',voice.muted);
  $('mic').disabled = next === 'connecting';
  $('end-call').hidden = !(connected || next === 'connecting');
  document.querySelector('.end-rule').hidden = $('end-call').hidden;
  $('status-dot').className = 'status-dot' + (connected ? ' live' : next === 'connecting' ? ' connecting' : '');
  $('mic-icon').firstElementChild.setAttribute('href',voice.muted ? '#i-mute' : '#i-mic');
  const micLabel = !connected ? 'Start voice conversation' : !voice.stream ? 'Enable microphone' : voice.muted ? 'Unmute microphone' : 'Mute microphone';
  $('mic').setAttribute('aria-label',micLabel); $('mic').title = micLabel;
  $('live-health').textContent = connected ? 'Connected' : next === 'connecting' ? 'Connecting…' : 'Not connected';
  const copy = {
    idle:['Go on.','Your day, in conversation.','Ready when you are',''],
    connecting:['One moment.','Opening your conversation.','Connecting voice','LET’S PICK UP THE THREAD'],
    connected: voice.muted || !voice.stream ? ['I’m here.','Unmute your microphone, or say it in writing.','Microphone off','YOUR CONVERSATION, YOUR PACE'] : ['Go on.<br>I’m listening.','Change your mind. Keep the thread.','Live conversation','YOUR CONVERSATION, YOUR PACE'],
    listening:['Take your time.','I’m listening.','Hearing you','YOUR CONVERSATION, YOUR PACE'],
    thinking:['Still with you.','A little room for your next thought.','Following your thought','YOUR CONVERSATION, YOUR PACE'],
    speaking:['I’m with you.',voice.stream && !voice.muted ? 'You can jump in whenever you like.' : 'Say it in writing, or turn on your microphone.',voice.stream && !voice.muted ? 'Speaking · mic still open' : 'Speaking · microphone off','YOUR CONVERSATION, YOUR PACE']
  }[next] || [];
  if (copy.length) { $('voice-title').innerHTML = copy[0]; $('voice-subtitle').textContent = copy[1]; $('connection').textContent = copy[2]; $('stage-kicker').textContent = copy[3]; }
  $('call-note').classList.toggle('timer',connected);
  if (!connected) $('call-note').textContent = next === 'connecting' ? 'Connecting to native audio…' : 'Your microphone turns on when you start.';
}
async function ensureVoice(microphone = true) {
  if (!config?.live?.configured) { toast('Set THREAD_API_KEY in the .env file beside run.ps1, then reload this page. Settings has a link to create a Gemini key.'); $('settings-dialog').showModal(); return false; }
  if (!sessionId || socket?.readyState !== WebSocket.OPEN) { toast('The local session is still connecting. Try again in a moment.'); return false; }
  if (state?.ended) await startSession(true);
  await voice.connect(sessionId,$('voice-choice').value,microphone);
  return voice.ready;
}
async function startSession(fresh=false) {
  if (socket) { socket.onclose = null; socket.close(); }
  events = []; liveCaptions.clear();
  let saved = fresh ? null : sessionStorage.getItem('thread-session');
  if (saved) { const response = await fetch(`/api/sessions/${saved}`); if (!response.ok || (await response.json()).ended) saved = null; }
  if (!saved) {
    const response = await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({experience:'voice'})});
    if (!response.ok) throw new Error('Could not start a session. Restart THREAD if its session limit is reached.');
    saved = (await response.json()).session_id;
  }
  sessionId = saved; sessionStorage.setItem('thread-session',saved);
  socket = new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${saved}`);
  const current = socket;
  socket.onmessage = ({data}) => {
    if (socket !== current) return;
    const event = JSON.parse(data);
    if (event.type === 'history') { events = event.events; render(event.state); return; }
    if (event.type === 'snapshot') { render(event.state); return; }
    if (event.id) events.push(event);
    if (event.type === 'error' || event.type === 'provider_error') { toast(event.text); orb?.pulse('error'); orbMood('apologetic', 5000); }
    if (event.type === 'phone_action_result' && WATCH_ACTIONS.has(event.action)) watches?.refresh();
    if ($('inspector').open) renderTimeline();
  };
  socket.onclose = event => { if (socket !== current) return; void voice.stop(); toast(event.code===4001 ? 'This session is open in another tab.' : 'The local server disconnected. Reload to reconnect.'); };
  await new Promise((resolve,reject) => { socket.onopen=resolve; socket.onerror=()=>reject(new Error('Could not open the local session.')); });
}
function render(next) {
  state = next;
  // A new result set is a real, returned outcome: acknowledge it once.
  const resultsId = next?.results?.id ?? null;
  if (resultsId && lastResultsId && resultsId !== lastResultsId) { orb?.pulse('done'); orbMood('pleased', 4000); }
  lastResultsId = resultsId ?? lastResultsId;
  renderWorkspace(state);
  $('media-preview').hidden = !state.media?.id;
  if (state.media?.id && $('preview-image').dataset.mediaId !== state.media.id) { $('preview-image').src=`/api/sessions/${sessionId}/frame?v=${encodeURIComponent(state.media.id)}`; $('preview-image').dataset.mediaId=state.media.id; }
  $('media-label').textContent = state.media?.label || 'Shared image';
  $('read-delay').value=state.challenge.read_delay; $('delay-label').textContent=`${state.challenge.read_delay} s`;
  $('late-reads').checked=state.challenge.late_reads; $('duplicate-outcomes').checked=state.challenge.duplicate_result; $('action-mode').value=state.challenge.action_mode;
  $('metrics').innerHTML=`<div><span>Actions submitted</span><b>${state.metrics.submitted_creates}</b></div><div><span>Saved / demo records</span><b>${state.metrics.actual_creations}</b></div><div><span>Obsolete results excluded</span><b>${state.metrics.excluded_read_results}</b></div>`;
  renderTranscript();
}
function renderTranscript() {
  const messages = new Map((state?.transcript || []).filter(m=>m.source==='native_audio' || m.role==='user' || !m.text.startsWith('Tell me what you need.')).map(m=>[m.id,m]));
  for (const [id,m] of liveCaptions) if (!messages.has(id) || messages.get(id).text.length<m.text.length) messages.set(id,m);
  $('transcript-count').textContent=String(messages.size);
  $('messages').innerHTML=messages.size ? [...messages.values()].map(m=>`<article class="transcript-message ${esc(m.role)}"><div class="message-meta">${m.role==='user'?'YOU':'THREAD'}${m.delivery==='interrupted'?'<span class="delivery">· interrupted</span>':''}</div><div class="message-body">${esc(m.text)}</div></article>`).join('') : '<p class="empty-copy">The conversation will find its way here.</p>';
  if ($('transcript-dialog').open) $('messages').scrollTop=$('messages').scrollHeight;
}
function renderTimeline() {
  $('timeline').innerHTML=events.slice(-160).reverse().map(event=>{const {text,...details}=event;return `<div class="event"><span class="event-type">${esc(event.type.replaceAll('_',' ').toUpperCase())}</span><span class="event-time">${Number(event.at_ms).toLocaleString()} ms</span><p>${esc(text)}</p><details><summary>Event details</summary><pre>${esc(JSON.stringify(details,null,2))}</pre></details></div>`;}).join('');
}
async function submitText(text) {
  if (!text.trim()) return;
  try { if (await ensureVoice(false)) { voice.clearPlayback(); voice.send({type:'text',text:text.trim()}); $('message').value=''; } } catch(error) { toast(error.message); }
}
$('mic').onclick=async()=>{try { if (voice.ready) voice.toggleMute(); else await ensureVoice(); } catch(error) {toast(error.message);} };
$('end-call').onclick=()=>void voice.stop();
$('keyboard').onclick=()=>{const open=$('composer').hidden; $('composer').hidden=!open; $('keyboard').setAttribute('aria-expanded',String(open)); if(open)$('message').focus();};
$('composer').onsubmit=event=>{event.preventDefault();void submitText($('message').value);};
$('message').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();void submitText($('message').value);}};
$('settings-toggle').onclick=()=>$('settings-dialog').showModal();
$('transcript-toggle').onclick=()=>{renderTranscript();$('transcript-dialog').showModal();$('messages').scrollTop=$('messages').scrollHeight;};
$('inspect-toggle').onclick=()=>{$('transcript-dialog').close();renderTimeline();$('inspector').showModal();};
document.addEventListener('click',event=>{
  const closer=event.target.closest('[data-close]'); if(closer)$(closer.dataset.close).close();
  const prompt=event.target.closest('[data-prompt]'); if(prompt)void submitText(prompt.dataset.prompt);
  const select=event.target.closest('[data-select]'); if(select)control('select',{option_id:select.dataset.select,results_id:state.results.id});
  if(event.target.closest('[data-retry]'))control('resume');
});
$('voice-choice').onchange=()=>localStorage.setItem('thread-voice',$('voice-choice').value);
$('backchannel').checked=localStorage.getItem('thread-backchannel')!=='off';
$('backchannel').onchange=()=>localStorage.setItem('thread-backchannel',$('backchannel').checked?'on':'off');
$('pause').onclick=()=>{voice.clearPlayback();control('pause');};
$('resume').onclick=()=>control('resume');
$('cancel-task').onclick=()=>{voice.clearPlayback();control('cancel');};
$('status').onclick=()=>control('status');
$('book').onclick=()=>control('book',{results_id:state.results?.id});
$('new-session').onclick=async()=>{try {control('end');await voice.stop();lastCaptionId=null;lastCaptionText='';$('caption-speaker').textContent='';$('caption-text').textContent='';$('previous-caption').textContent='';await startSession(true);}catch(error){toast(error.message);}};
$('export').onclick=()=>{if(sessionId){const a=document.createElement('a');a.href=`/api/sessions/${sessionId}/export`;a.download=`${sessionId}.json`;a.click();}};
$('read-delay').oninput=()=>$('delay-label').textContent=`${$('read-delay').value} s`;
$('read-delay').onchange=()=>control('challenge',{config:{read_delay:Number($('read-delay').value)}});
$('late-reads').onchange=()=>control('challenge',{config:{late_reads:$('late-reads').checked}});
$('duplicate-outcomes').onchange=()=>control('challenge',{config:{duplicate_result:$('duplicate-outcomes').checked}});
$('action-mode').onchange=()=>control('challenge',{config:{action_mode:$('action-mode').value}});
$('fail-read').onclick=()=>control('challenge',{config:{fail_next_read:true}});
$('repeat-result').onclick=()=>control('duplicate_result');
$('attach').onclick=()=>$('file').click();
async function attach(blob,label) {
  if(blob.size>6_000_000){toast('Choose an image smaller than 6 MB.');return;}
  const originatingSession=sessionId;
  try {const base64=await asBase64(blob);if(originatingSession!==sessionId)return;if(await ensureVoice(false))voice.send({type:'image',data:{base64,mime:blob.type,label}});}catch(error){toast(error.message);}
}
$('file').onchange=async()=>{const file=$('file').files[0];if(file)await attach(file,file.name);$('file').value='';};
$('device-demo').onclick=async()=>{const r=await fetch('/static/device-fixture.png');if(r.ok)await attach(await r.blob(),'THREAD R1 · demo image');};
window.addEventListener('pagehide',()=>{void voice.stop();});
setInterval(()=>{if(callStarted && voice.ready){const s=Math.floor((performance.now()-callStarted)/1000);$('call-note').textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}${voice.muted?' · MIC MUTED':!voice.stream?' · KEYBOARD':''}`;}},500);
// The acoustic sphere, alive. Every phase, pulse and mood comes from the voice layer or the session
// (measured level, voice state, real interruption, returned results, errors), never from a timer.
function orbPhase(next) {
  if (!voice.ready) return next === 'connecting' ? 'connecting' : 'idle';
  if (next === 'speaking') return 'speaking';
  if (voice.muted || !voice.stream) return 'muted';
  return {connected:'listening', listening:'listening', thinking:'hesitating'}[next] || 'listening';
}
function orbMood(name, ms) { orb?.setMood(name); orbMoodUntil = performance.now() + ms; }
orb = createOrb($('thread-canvas'), {theme:'auto', image:'/static/images/thread-sphere.png', scale:.94});
// Standing Watches sit at the top of the workspace when the host has any; hidden otherwise (and on Android hosts).
watches = mountWatches(document.querySelector('.context-scroll'));
orb.setPhase(orbPhase(callState));
(function feedOrb() {
  requestAnimationFrame(feedOrb);
  if (document.hidden) return;
  orb.setLevel(voice.levels());
  if (orbMoodUntil && performance.now() > orbMoodUntil) { orb.setMood('neutral'); orbMoodUntil = 0; }
})();
try{
 config=await(await fetch('/api/config')).json();$('privacy').textContent=config.privacy;$('live-model').textContent=`Gemini Live · ${config.live.model}`;
 $('gemini-setup').hidden=Boolean(config.live.configured);
 const chosen=localStorage.getItem('thread-voice') || config.live.voice;if([...$('voice-choice').options].some(o=>o.value===chosen))$('voice-choice').value=chosen;
 await startSession();
 if(!config.live.configured)toast('Voice needs a Gemini key. Open Settings for setup instructions.');
}catch(error){toast(error.message || 'The local server is unavailable.');}
