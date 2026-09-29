// Continuous 16 kHz PCM, one 32 ms network frame. Never wait for a whole utterance.
class ThreadLiveCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(512); this.offset = 0;
    this.phase = 0; this.sum = 0; this.count = 0;
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input) for (const sample of input) {
      this.sum += sample; this.count++; this.phase += 16000;
      if (this.phase >= sampleRate) {
        this.phase -= sampleRate;
        const v = Math.max(-1, Math.min(1, this.sum / this.count));
        this.frame[this.offset++] = Math.round(v * (v < 0 ? 32768 : 32767));
        this.sum = 0; this.count = 0;
        if (this.offset === this.frame.length) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
          this.frame = new Int16Array(512); this.offset = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('thread-live-capture', ThreadLiveCapture);
