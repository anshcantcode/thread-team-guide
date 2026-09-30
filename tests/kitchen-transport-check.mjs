import assert from 'node:assert/strict';
import {NativeVoice} from '../web/live-audio.js';

// Exercise the shared transport with a fake network and audio device. No model calls.
const sent = [], received = [];
globalThis.location = {protocol: 'http:', host: '127.0.0.1:8768'};
globalThis.fetch = async () => ({ok: false});
globalThis.AudioContext = class {
  currentTime = 2;
  async resume() {}
  createAnalyser() { return {connect() {}}; }
  async close() { this.state = 'closed'; }
};
globalThis.WebSocket = class {
  static OPEN = 1;
  readyState = 1;
  constructor(url) { this.url = url; }
  send(data) { sent.push(JSON.parse(data)); }
  close() {}
};
let token = 0;
const voice = new NativeVoice({
  state() {}, error(message) { assert.fail(message); }, caption() {},
  open() { voice.send({type: 'hello', client: 'browser'}); },
  message(event) { received.push(event); },
  prepareInput(event) {
    if (event.type === 'resume_after_noise') return null;
    if (['text', 'speech_start'].includes(event.type)) event.input_token = String(++token);
    return event;
  },
});
const connected = voice.connect('', 'Kore', false, '/voice');
await new Promise(resolve => setImmediate(resolve));
assert.equal(voice.ws.url, 'ws://127.0.0.1:8768/voice', 'Kitchen must not silently connect to the legacy Gemini route');
voice.ws.onopen();
assert.equal(sent.at(-1).type, 'hello', 'The host must receive session admission after the socket opens');
voice.ws.onmessage({data: JSON.stringify({type: 'live_ready'})});
await connected;
voice.ws.onmessage({data: JSON.stringify({type: 'tool_request', request_id: 'local-write'})});
assert.equal(received.at(-1).request_id, 'local-write', 'Native transport must deliver actual tool RPCs to the device store');
voice.send({type: 'text', text: 'Add basil'});
assert.equal(sent.at(-1).input_token, '1');
voice.send({type: 'speech_start'});
assert.equal(sent.at(-1).input_token, '2', 'Speech must receive fresh admission before its PCM');
const count = sent.length;
voice.send({type: 'resume_after_noise'});
assert.equal(sent.length, count, 'Kitchen can suppress unsupported legacy recovery messages');
voice.played.set('already-drained', 480);
voice.ws.onmessage({data: JSON.stringify({type: 'turn_complete', message_id: 'already-drained'})});
assert.deepEqual(sent.at(-1), {type: 'playback', message_id: 'already-drained', status: 'played', played_ms: 480});
let stopped = false;
voice.sources.add({start: 1.75, duration: 2, messageId: 'old-answer', node: {stop() { stopped = true; }, disconnect() {}}});
voice.ws.onmessage({data: JSON.stringify({type: 'interrupted', recoverable: false})});
assert.equal(stopped, true, 'A host interruption must clear audio even before local VAD pauses it');
assert.equal(voice.sources.size, 0);
assert.deepEqual(sent.at(-1), {type: 'playback', message_id: 'old-answer', status: 'interrupted', played_ms: 250});
await voice.stop();
// Storage admission can close the connection inside the speech-start callback.
// The same microphone callback must then finish without sending another frame.
const pcm = [];
const denied = new NativeVoice({state() {}, prepareInput(event) {
  if (event.type === 'speech_start') { void denied.stop(); return null; }
  return event;
}});
denied.ready = true; denied.hot = 0; denied.quiet = 0;
denied.ws = {readyState: 1, bufferedAmount: 0, send(data) { if (data instanceof ArrayBuffer) pcm.push(data); }, close() {}};
assert.doesNotThrow(() => { for (let frame = 0; frame < 3; frame++) denied.process(new Int16Array(512).fill(4096).buffer); });
assert.equal(pcm.length, 2, 'A denied speech onset cannot send its PCM after disconnection');
console.log(JSON.stringify({suite: 'Kitchen route, admission, RPC and playback integration', passed: true, assertions: 12, model_calls: 0}));
