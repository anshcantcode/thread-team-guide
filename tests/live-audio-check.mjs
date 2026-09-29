import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {NativeVoice,hasWords} from '../web/live-audio.js';

const frames=[];let Processor;
vm.runInNewContext(await readFile(new URL('../web/live-worklet.js',import.meta.url),'utf8'),{
  AudioWorkletProcessor:class{constructor(){this.port={postMessage:buffer=>frames.push(buffer)};}},
  sampleRate:48000,Int16Array,Math,registerProcessor:(name,type)=>Processor=type
});
const processor=new Processor();
for(let i=0;i<375;i++) processor.process([[new Float32Array(128).fill(.25)]]);
assert.equal(frames.length,31,'One second of input must stream before any end-of-utterance event');
assert.equal(frames[0].byteLength,1024,'Network frames must contain 32 ms of PCM');
assert.ok(new Int16Array(frames[0]).every(x=>x===8192));

globalThis.WebSocket={OPEN:1};
const sent=[],states=[];
const voice=new NativeVoice({state:x=>states.push(x),error:e=>{throw Error(e);},threshold:()=>.018});
voice.ready=true;voice.ws={readyState:1,bufferedAmount:0,send:x=>sent.push(x)};voice.hot=0;voice.quiet=0;
let stopped=0;
voice.context={currentTime:2};
voice.sources.add({start:1,duration:3,messageId:'old-response',buffer:{duration:3},node:{stop:()=>stopped++,disconnect:()=>{},onended:()=>{}}});
for(let i=0;i<3;i++)voice.process(new Int16Array(512).fill(4096).buffer);
assert.equal(stopped,1,'Speech onset must stop queued playback without waiting for the network');
assert.equal(voice.sources.size,0);
assert.ok(sent.some(x=>typeof x==='string'&&JSON.parse(x).type==='speech_start'));
assert.equal(sent.filter(x=>x instanceof ArrayBuffer).length,3,'Audio streams during speech');
assert.equal(states.at(-1),'listening');
voice.speaking=false;
assert.equal(voice.barge.held[0].offset,1,'Pause records exactly the heard part, not the start of the buffer');
assert.equal(voice.blockedMessages.has('old-response'),false,'A loud sound alone must not delete the answer');
assert.equal(voice.acceptAudio({message_id:'old-response',data:'AAAA'}),false,'Old audio is buffered while we verify speech');
assert.equal(voice.barge.events.length,1);
voice.confirmBarge(false);
const accepted=[];voice.enqueue=event=>accepted.push(event.message_id);
assert.equal(voice.acceptAudio({message_id:'old-response'}),false,'Late packets from interrupted playback stay discarded');
assert.equal(voice.acceptAudio({message_id:'new-response'}),true,'A new response plays even if the provider had already finished the old generation');
assert.deepEqual(accepted,['new-response']);
voice.blockAudio=true;voice.send({type:'text',text:'Continue our conversation.'});
assert.equal(voice.blockAudio,false,'New typed input restores the voice after a speech-only stop');

const resumed=[];
voice.sources.add({start:1,duration:3,messageId:'resume-me',buffer:{duration:3},node:{stop:()=>{},disconnect:()=>{}}});
voice.pauseForBarge();voice.scheduleBuffer=(buffer,id,offset)=>resumed.push({id,offset});
voice.resumeAfterNoise({message_id:'wrong',continue_needed:false});assert.equal(resumed.length,0,'Mismatched recovery is rejected');
voice.resumeAfterNoise({message_id:'resume-me',continue_needed:false});
assert.deepEqual(resumed,[{id:'resume-me',offset:1}],'False interruption resumes at the unheard audio sample');
assert.equal(voice.barge,null);
assert.ok(!sent.some(x=>typeof x==='string'&&JSON.parse(x).type==='continue_after_noise'),'Completed buffered speech needs no extra model request');
voice.recovery={messageId:'partial-answer'};voice.continueRecovered();voice.continueRecovered();
assert.equal(sent.filter(x=>typeof x==='string'&&JSON.parse(x).type==='continue_after_noise').length,1,'Only one continuation request is sent when buffered tail ends');
for(const s of ['[noise]','[silence]','[coughing]',' … '])assert.equal(hasWords(s),false);
for(const s of ['stop','no','हां','嗯','3'])assert.equal(hasWords(s),true);
voice.clearPlayback();assert.equal(voice.pendingContinuation,null);

let permissionResolve,trackStopped=false;
Object.defineProperty(globalThis,'navigator',{value:{mediaDevices:{getUserMedia:()=>new Promise(r=>permissionResolve=r)}},configurable:true});
const race=new NativeVoice({state:()=>{},error:()=>{}});race.ready=true;
const pending=race.enableMic();await race.stop();
permissionResolve({getTracks:()=>[{stop:()=>trackStopped=true}]});await pending;
assert.equal(trackStopped,true,'Late microphone permission must not revive a stopped call');
assert.equal(race.stream,null);
console.log('Live audio checks passed: continuous PCM, pause/confirm/resume from exact offset, one continuation, multilingual words, late permission cleanup.');
