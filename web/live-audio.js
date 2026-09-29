export class NativeVoice {
  constructor(callbacks) {
    this.callbacks = callbacks; this.generation = 0; this.sources = new Set();
    this.ready = false; this.muted = false; this.inputLevel = 0; this.outputLevel = 0;
    this.speaking = false; this.blockAudio = false; this.played = new Map();
    this.blockedMessages = new Set(); this.lastAudioId = null;
    this.barge = null; this.recoveryTimer = null; this.recovery = null;
    this.lastAcknowledgment = -Infinity; this.backchannelBuffer = null;
  }
  async connect(sessionId, voice, microphone = true) {
    if (this.ready) { if (microphone && !this.stream) await this.enableMic(); return; }
    if (this.connecting) return this.connecting;
    const generation = ++this.generation;
    // Created and resumed in the user's click/submit gesture: no autoplay workaround.
    this.context = new AudioContext({latencyHint: 'interactive'});
    await this.context.resume();
    if (generation !== this.generation) return;
    this.analyser = this.context.createAnalyser(); this.analyser.fftSize = 256;
    this.analyser.connect(this.context.destination);
    void fetch(`/static/sounds/ack-${encodeURIComponent(voice)}.wav`).then(r=>r.ok?r.arrayBuffer():null).then(async raw=>{
      if(raw && generation===this.generation){const decoded=await this.context.decodeAudioData(raw);if(generation===this.generation)this.backchannelBuffer=decoded;}
    }).catch(()=>{});
    this.nextTime = 0; this.speechEnd = null;
    this.callbacks.state('connecting');
    const ws = this.ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/live/${sessionId}?voice=${encodeURIComponent(voice)}`);
    this.connecting = new Promise((resolve, reject) => {
      this.rejectConnect = reject;
      const timeout = setTimeout(() => reject(new Error('The voice connection timed out. Try again.')), 25000);
      ws.onmessage = ({data}) => {
        if (generation !== this.generation) return;
        const event = JSON.parse(data);
        if (event.type === 'live_ready') {
          clearTimeout(timeout); this.ready = true; resolve();
          this.callbacks.state('connected');
        } else if (event.type === 'live_error') {
          clearTimeout(timeout); reject(new Error(event.text));
          this.callbacks.error(event.text); void this.stop();
        } else if (event.type === 'audio') {
          this.acceptAudio(event);
        } else if (event.type === 'interrupted') {
          if(event.recoverable && !this.blockAudio){this.pauseForBarge(event.message_id);if(this.barge)this.barge.providerInterrupted=true;this.scheduleRecovery();}
          else this.clearPlayback('interrupted');
        } else if (event.type === 'resume_after_noise') {
          this.resumeAfterNoise(event);
        } else if (event.type === 'resume_deferred') {
          if(event.continuation && this.pendingContinuation && ++this.pendingContinuation.retries<20){
            const pending=this.pendingContinuation,generation=this.generation;
            this.recoveryTimer=setTimeout(()=>{if(generation===this.generation && pending===this.pendingContinuation && !this.speaking)this.send({type:'continue_after_noise',message_id:pending.messageId});},700);
          }else if(this.barge && ++this.barge.retries<20)this.scheduleRecovery(700);
          else this.callbacks.error('Voice recovery is taking longer than expected. Your reply is paused while the voice service finishes.');
        } else if (event.type === 'resume_denied') {
          this.confirmBarge(false);
        } else if (event.type === 'silenced') {
          this.clearPlayback('interrupted'); this.blockAudio = true;
        } else if (event.type === 'turn_complete') {
          if(this.barge && !this.speaking)this.scheduleRecovery(100);
          if (!this.sources.size) this.callbacks.state(this.speaking ? 'listening' : 'connected');
        } else if (event.type === 'caption') {
          if(event.role==='user' && hasWords(event.text)){
            this.blockAudio=false;
            if(this.lastRecoveredId && [...this.sources].some(s=>s.messageId===this.lastRecoveredId))this.pauseForBarge(this.lastRecoveredId);
            this.confirmBarge(true);
          }
          if (event.role === 'user' || (!this.blockAudio && !this.speaking && !this.blockedMessages.has(event.message_id))) this.callbacks.caption(event);
        } else if (event.type === 'reconnect_needed') this.callbacks.error(event.text);
      };
      ws.onclose = event => {
        clearTimeout(timeout);
        if (generation !== this.generation) return;
        reject(new Error(event.code === 4001 ? 'Voice is already open in another tab.' : 'Voice disconnected. Reconnect to continue.'));
        if (this.ready) this.callbacks.error('Voice disconnected. Your task details are kept.');
        void this.stop();
      };
      ws.onerror = () => { clearTimeout(timeout); reject(new Error('Could not reach live voice.')); };
    });
    try {
      await this.connecting;
      if (generation !== this.generation) return;
      if (microphone) await this.enableMic();
    } catch (error) {
      if (generation === this.generation) { await this.stop(); throw error; }
    } finally { if (generation === this.generation) { this.connecting = null; this.rejectConnect = null; } }
  }
  send(data) {
    if (data.type === 'text') {this.confirmBarge(false);this.recovery=null;this.blockAudio = false;}
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(data));
  }
  async enableMic() {
    if (this.stream || this.micPending) return;
    const generation = this.generation;
    this.micPending = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}, video: false});
      if (generation !== this.generation || !this.ready) { stream.getTracks().forEach(t => t.stop()); return; }
      this.stream = stream; this.muted = false;
      await this.context.audioWorklet.addModule('/static/live-worklet.js');
      if (generation !== this.generation) return;
      this.input = this.context.createMediaStreamSource(stream);
      this.capture = new AudioWorkletNode(this.context, 'thread-live-capture');
      const silence = this.context.createGain(); silence.gain.value = 0;
      this.input.connect(this.capture); this.capture.connect(silence); silence.connect(this.context.destination);
      this.hot = 0; this.quiet = 0;
      this.capture.port.onmessage = ({data}) => {
        if (generation === this.generation) this.process(data);
      };
      this.callbacks.state('connected');
    } catch (error) {
      if (generation === this.generation) {
        this.stream?.getTracks().forEach(t => t.stop()); this.stream = null;
        this.callbacks.error('Microphone permission is unavailable. Allow it in the browser, or use the keyboard.');
      }
    } finally { if (generation === this.generation) this.micPending = false; }
  }
  process(buffer) {
    if (!this.ready || this.ws?.readyState !== WebSocket.OPEN) return;
    const pcm = new Int16Array(buffer);
    let energy = 0; for (const sample of pcm) energy += (sample / 32768) ** 2;
    const rms = this.muted ? 0 : Math.sqrt(energy / pcm.length);
    this.inputLevel = Math.min(1, rms * 8);
    const seconds = pcm.length / 16000;
    const voiced = rms > (this.callbacks.threshold?.() ?? 0.018);
    this.hot = voiced ? this.hot + seconds : 0;
    this.quiet = voiced ? 0 : this.quiet + seconds;
    if (!this.speaking && this.hot >= 0.096) {
      this.speaking = true; this.speechEnd = null;
      this.recovery=null;
      // Pause immediately, but retain the unheard PCM until actual words confirm
      // an interruption. A cough must not permanently eat the rest of a sentence.
      this.pauseForBarge();
      clearTimeout(this.recoveryTimer);
      this.send({type: 'speech_start',message_id:this.barge?.messageId}); this.callbacks.state('listening');
    }
    if (this.speaking && this.quiet >= 0.544) {
      this.speaking = false;
      // Keep last voiced time, not silence-detector firing time, for playback latency.
      this.speechEnd = performance.now() - this.quiet * 1000;
      this.send({type: 'speech_end'}); this.callbacks.state('thinking');
      this.scheduleRecovery();
    }
    if (this.ws.bufferedAmount > 128000) {
      this.callbacks.error('The connection is falling behind live audio. Reconnect when the network is stable.');
      void this.stop(); return;
    }
    this.ws.send(this.muted ? new ArrayBuffer(buffer.byteLength) : buffer);
  }
  acceptAudio(event) {
    // A completed generation may still have seconds queued in the speaker. The
    // next response has a new ID and must play even without a provider interrupt.
    if(this.barge && !this.barge.confirmed){
      if(event.message_id===this.barge.messageId && this.barge.bytes+event.data.length<4_000_000){this.barge.events.push(event);this.barge.bytes+=event.data.length;}
      return false;
    }
    if (this.blockAudio || this.speaking || this.blockedMessages.has(event.message_id)) return false;
    this.pendingContinuation=null;
    this.lastAudioId = event.message_id;
    this.enqueue(event); return true;
  }
  enqueue(event) {
    const bytes = Uint8Array.from(atob(event.data), c => c.charCodeAt(0));
    if (bytes.length % 2 || event.sample_rate !== 24000) return;
    const view = new DataView(bytes.buffer);
    const buffer = this.context.createBuffer(1, bytes.length / 2, 24000);
    const floats = buffer.getChannelData(0);
    for (let i = 0; i < floats.length; i++) floats[i] = view.getInt16(i * 2, true) / 32768;
    this.scheduleBuffer(buffer,event.message_id);
  }
  scheduleBuffer(buffer,messageId,offset=0){
    if(!this.context || offset>=buffer.duration)return;
    const node = this.context.createBufferSource(); node.buffer = buffer; node.connect(this.analyser);
    const start = Math.max(this.context.currentTime + 0.045, this.nextTime, this.ackEndTime || 0);
    const item = {node, buffer, offset, start, duration: buffer.duration-offset, messageId};
    this.sources.add(item); this.nextTime = start + item.duration;
    if (!this.played.has(messageId)) {
      this.played.set(messageId, 0);
      this.send({type: 'playback', message_id: messageId, status: 'playing'});
      if (this.speechEnd !== null) {
        const latency = Math.round(performance.now() - this.speechEnd + (start - this.context.currentTime) * 1000);
        this.callbacks.latency(latency); this.send({type:'latency',value_ms:latency});
        this.speechEnd = null;
      }
    }
    node.onended = () => {
      if (!this.sources.delete(item)) return;
      node.disconnect();
      this.played.set(item.messageId, (this.played.get(item.messageId) || 0) + item.duration * 1000);
      if (![...this.sources].some(s => s.messageId === item.messageId)) this.send({type:'playback', message_id:item.messageId, status:'played', played_ms:this.played.get(item.messageId)});
      if (!this.sources.size) {this.callbacks.state(this.speaking ? 'listening' : 'connected');this.continueRecovered();}
    };
    node.start(start,offset); this.callbacks.state('speaking');
  }
  pauseForBarge(messageId=null){
    if(this.barge)return;
    const id=messageId || [...this.sources][0]?.messageId;
    if(!id || this.blockedMessages.has(id))return;
    const held=[];
    for(const item of this.sources){
      const elapsed=Math.max(0,Math.min(item.duration,(this.context?.currentTime||0)-item.start));
      this.played.set(item.messageId,(this.played.get(item.messageId)||0)+elapsed*1000);
      if(item.messageId===id && item.duration>elapsed)held.push({buffer:item.buffer||item.node.buffer,offset:(item.offset||0)+elapsed,messageId:id});
      item.node.onended=null;item.node.stop();item.node.disconnect();
    }
    this.sources.clear();this.nextTime=0;
    this.barge={messageId:id,held,events:[],bytes:0,confirmed:false,retries:0};
    this.send({type:'playback',message_id:id,status:'paused',played_ms:this.played.get(id)||0});
  }
  scheduleRecovery(delay=1250){
    clearTimeout(this.recoveryTimer);
    if(!this.barge || this.speaking || this.barge.confirmed)return;
    const candidate=this.barge,generation=this.generation;
    this.recoveryTimer=setTimeout(()=>{
      if(generation===this.generation && this.barge===candidate && !this.speaking && !this.blockAudio)
        this.send({type:'resume_after_noise',message_id:candidate.messageId});
    },delay);
  }
  confirmBarge(acknowledge=true){
    clearTimeout(this.recoveryTimer);this.recovery=null;this.pendingContinuation=null;
    if(!this.barge)return;
    this.blockedMessages.add(this.barge.messageId);
    this.send({type:'playback',message_id:this.barge.messageId,status:'interrupted',played_ms:this.played.get(this.barge.messageId)||0});
    this.barge=null;
    if(acknowledge)this.acknowledge();
  }
  resumeAfterNoise(event){
    const held=this.barge;
    if(!held || held.messageId!==event.message_id || this.speaking || this.blockAudio)return;
    clearTimeout(this.recoveryTimer);this.barge=null;
    this.blockedMessages.delete(held.messageId);
    this.lastRecoveredId=held.messageId;
    this.recovery=event.continue_needed?{messageId:held.messageId}:null;
    for(const item of held.held)if(item.buffer)this.scheduleBuffer(item.buffer,item.messageId,item.offset);
    for(const packet of held.events)this.acceptAudio(packet);
    this.send({type:'playback',message_id:held.messageId,status:'resumed',played_ms:this.played.get(held.messageId)||0});
    if(!this.sources.size)this.continueRecovered();
  }
  continueRecovered(){
    if(!this.recovery || this.speaking || this.barge || !this.ready || this.blockAudio)return;
    const recovered=this.recovery;this.recovery=null;
    this.pendingContinuation={...recovered,retries:0};
    this.send({type:'continue_after_noise',message_id:recovered.messageId});
    this.callbacks.state('thinking');
  }
  acknowledge(){
    const now=performance.now();
    if(!this.context || !this.backchannelBuffer || now-this.lastAcknowledgment<6000 || this.callbacks.backchannel?.()===false)return;
    this.lastAcknowledgment=now;
    const sound=this.context.createBufferSource(),gain=this.context.createGain();
    sound.buffer=this.backchannelBuffer;gain.gain.value=.32;
    this.ackEndTime=this.context.currentTime+sound.buffer.duration+.035;
    sound.connect(gain);gain.connect(this.context.destination);
    sound.onended=()=>{sound.disconnect();gain.disconnect();};sound.start();
  }
  clearPlayback(status = 'interrupted') {
    this.confirmBarge(false);this.recovery=null;
    const affected = new Set();
    if (this.lastAudioId) this.blockedMessages.add(this.lastAudioId);
    for (const item of this.sources) {
      const elapsed = Math.max(0, Math.min(item.duration, (this.context?.currentTime || 0) - item.start));
      this.played.set(item.messageId, (this.played.get(item.messageId) || 0) + elapsed * 1000);
      affected.add(item.messageId); item.node.onended = null; item.node.stop(); item.node.disconnect();
      this.blockedMessages.add(item.messageId);
    }
    this.sources.clear(); this.nextTime = 0; this.outputLevel = 0;
    for (const id of affected) this.send({type:'playback', message_id:id, status, played_ms:this.played.get(id)});
  }
  toggleMute() {
    this.confirmBarge(false);
    if (!this.stream) { void this.enableMic(); return; }
    this.muted = !this.muted;
    this.stream.getAudioTracks().forEach(track => track.enabled = !this.muted);
    if (this.muted && this.speaking) { this.speaking = false; this.send({type:'speech_end'}); }
    this.callbacks.state('connected');
  }
  levels() {
    if (this.analyser && this.sources.size) {
      const data = new Uint8Array(this.analyser.fftSize); this.analyser.getByteTimeDomainData(data);
      let sum = 0; for (const v of data) sum += ((v - 128) / 128) ** 2;
      this.outputLevel = Math.min(1, Math.sqrt(sum / data.length) * 5);
    } else this.outputLevel = 0;
    return Math.max(this.inputLevel, this.outputLevel);
  }
  async stop() {
    this.generation++; this.ready = false;
    this.rejectConnect?.(new Error('Voice connection stopped.')); this.rejectConnect = null;
    this.clearPlayback();
    this.send({type:'end'});
    if (this.ws) { this.ws.onclose = null; this.ws.onmessage = null; this.ws.onerror = null; this.ws.close(); }
    this.ws = null;
    if (this.capture) { this.capture.port.onmessage = null; this.capture.disconnect(); }
    this.input?.disconnect(); this.stream?.getTracks().forEach(t => t.stop());
    const context = this.context;
    this.context = null; this.stream = null; this.capture = null; this.input = null; this.analyser = null;
    this.connecting = null; this.micPending = false; this.speaking = false; this.blockAudio = false;
    this.inputLevel = 0; this.outputLevel = 0; this.played.clear();
    this.blockedMessages.clear(); this.lastAudioId = null;
    this.backchannelBuffer=null;this.ackEndTime=0;clearTimeout(this.recoveryTimer);this.barge=null;this.recovery=null;this.pendingContinuation=null;this.lastRecoveredId=null;
    if (context && context.state !== 'closed') await context.close();
    this.callbacks.state('idle');
  }
}

export function hasWords(text){return /[\p{L}\p{N}]/u.test(String(text).replace(/\[(?:noise|silence|cough|inaudible|unintelligible|music|breathing)[^\]]*\]/gi,''));}
