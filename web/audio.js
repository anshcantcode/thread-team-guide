export function wavBlob(chunks, sampleRate) {
  const count = chunks.reduce((n, x) => n + x.length, 0);
  const data = new ArrayBuffer(44 + count * 2), view = new DataView(data);
  const text = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  text(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, count * 2, true);
  let offset = 44;
  for (const chunk of chunks) for (const sample of chunk) {
    const v = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, v < 0 ? v * 32768 : v * 32767, true); offset += 2;
  }
  return new Blob([data], { type: 'audio/wav' });
}

export function asBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject; reader.readAsDataURL(blob);
  });
}

export class VoiceCapture {
  constructor({ onStart, onAudio, onLevel, onState, threshold }) {
    Object.assign(this, { onStart, onAudio, onLevel, onState, threshold });
    this.stream = null; this.context = null; this.generation = 0;
  }
  async start() {
    const generation = ++this.generation;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 }, video: false });
      if (generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return; }
      this.stream = stream;
      this.context = new AudioContext({ sampleRate: 16000 });
      await this.context.audioWorklet.addModule('/static/audio-worklet.js');
      if (generation !== this.generation) return;
      this.source = this.context.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.context, 'thread-capture');
      const silence = this.context.createGain(); silence.gain.value = 0;
      this.source.connect(this.node); this.node.connect(silence); silence.connect(this.context.destination);
      this.rate = this.context.sampleRate; this.pre = []; this.chunks = []; this.active = false; this.hot = 0; this.quiet = 0; this.length = 0;
      this.node.port.onmessage = ({ data }) => this.process(data);
      await this.context.resume(); if (generation === this.generation) this.onState('Listening');
    } catch (error) { if (generation !== this.generation) return; await this.stop(); throw error; }
  }
  process(samples) {
    const rms = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
    const seconds = samples.length / this.rate;
    this.onLevel(Math.min(1, rms * 12));
    const voiced = rms > this.threshold();
    if (!this.active) {
      this.pre.push(samples); if (this.pre.length > Math.ceil(this.rate * 0.35 / 2048)) this.pre.shift();
      this.hot = voiced ? this.hot + seconds : 0;
      if (this.hot >= 0.16) {
        this.active = true; this.chunks = [...this.pre]; this.pre = []; this.length = this.hot; this.quiet = 0;
        this.onStart(); this.onState('Hearing you');
      }
    } else {
      this.chunks.push(samples); this.length += seconds; this.quiet = voiced ? 0 : this.quiet + seconds;
      if (this.quiet >= 0.65 || this.length >= 15) this.flush();
    }
  }
  flush() {
    if (this.active && this.chunks.length && this.length >= 0.25) this.onAudio(wavBlob(this.chunks, this.rate));
    this.active = false; this.chunks = []; this.hot = 0; this.quiet = 0; this.length = 0;
    this.onState('Listening');
  }
  async stop() {
    this.generation++;
    if (this.active) this.flush();
    if (this.node) { this.node.port.onmessage = null; this.node.disconnect(); }
    if (this.source) this.source.disconnect();
    this.stream?.getTracks().forEach(track => track.stop());
    if (this.context && this.context.state !== 'closed') await this.context.close();
    this.stream = null; this.context = null; this.active = false;
    this.onState('Mic off'); this.onLevel(0);
  }
}
