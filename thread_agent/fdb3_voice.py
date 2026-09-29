"""LiveKit pipeline nodes for a zero-paid-spend Windows development route.

The same agent can attach to a LiveKit room or file-backed audio I/O. File I/O
is a diagnostic, not evidence of cloud transport or human interruption latency.
"""
from __future__ import annotations

import asyncio
import audioop
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import time
import threading
import uuid
import wave

from livekit import rtc
from livekit.agents import Agent, AgentSession, stt, tts, llm, vad, APIConnectOptions, StopResponse
from livekit.agents.voice import io as voice_io
from livekit.plugins import silero


def append_journal(path, lock, record):
    if path is None:
        return
    with lock:
        with Path(path).open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(record)+'\n')
            handle.flush()
            os.fsync(handle.fileno())


def input_prompt(contract_dir=None, *, tools=None):
    """Contract-vocabulary ASR prompt for user input, when THREAD_FDB3_WHISPER_PROMPT=contract.

    From the pinned contract directory, or from an already-declared tool contract
    (the extension's registry); never from scenario text.
    """
    if os.environ.get("THREAD_FDB3_WHISPER_PROMPT") != "contract":
        return None
    from thread_agent.fdb3 import contract_prompt, load_contract
    return contract_prompt(tools if tools is not None else load_contract(Path(contract_dir)))


class WhisperSTT(stt.STT):
    def __init__(self, model_path, *, prompt=None):
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        from faster_whisper import WhisperModel
        # Declared configuration: cpu/int8 (default) or cuda/float16 on a GPU host.
        self.device = os.environ.get("THREAD_FDB3_WHISPER_DEVICE", "cpu")
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        self.whisper = WhisperModel(str(model_path), device=self.device, compute_type=self.compute_type,
                                    local_files_only=True)
        # Applies to user input recognition only; direct transcribe() calls (the
        # evaluator's output ASR) never receive it.
        self.prompt = prompt
        self.records = []
        self.active_recognitions = 0
        self.last_activity_at = 0
        self.attempts = []
        self.transcription_journal = None
        self.journal_lock = threading.Lock()

    def transcribe(self, audio, *, filter_silence=False, word_timestamps=False, prompt=None):
        record={'request_id':uuid.uuid4().hex,'started_at':time.time(),
                'filter_silence':filter_silence,'word_timestamps':word_timestamps,'outcome':'pending',
                'prompt':prompt is not None}
        self.attempts.append(record)
        self._journal_transcription(record)
        try:
            segments, info = self.whisper.transcribe(audio, language="en", beam_size=5, vad_filter=filter_silence,
                                                    condition_on_previous_text=False, initial_prompt=prompt,
                                                    **({'word_timestamps':True} if word_timestamps else {}))
            segments = list(segments)
            text=" ".join(s.text.strip() for s in segments)
            chunks=[{'text':s.text,'timestamp':[s.start,s.end]} for s in segments]
            if word_timestamps:
                for chunk,segment in zip(chunks,segments):
                    chunk['words']=[{'text':word.word,'timestamp':[word.start,word.end]}
                                    for word in (segment.words or [])]
            record.update(outcome='success',text=text,chunks=chunks)
            return text,chunks
        except BaseException as exc:
            record.update(outcome='error',error_type=type(exc).__name__)
            raise
        finally:
            record['finished_at']=time.time()
            self._journal_transcription(record)

    def _journal_transcription(self, record):
        # Production calls run in the recognition executor, never the audio loop.
        append_journal(self.transcription_journal,self.journal_lock,record)

    async def _recognize_impl(self, buffer, *, language, conn_options):
        self.active_recognitions += 1
        self.last_activity_at = time.monotonic()
        try:
            return await self._recognize_audio(buffer)
        finally:
            self.active_recognitions -= 1
            self.last_activity_at = time.monotonic()

    async def _recognize_audio(self, buffer):
        frame = rtc.combine_audio_frames(buffer)
        wav = io.BytesIO()
        with wave.open(wav, "wb") as out:
            out.setnchannels(frame.num_channels)
            out.setsampwidth(2)
            out.setframerate(frame.sample_rate)
            out.writeframes(bytes(frame.data))
        wav.seek(0)
        started = time.time()
        text, chunks = await asyncio.to_thread(lambda: self.transcribe(wav, prompt=self.prompt))
        self.records.append({"text": text, "started_at": started, "finished_at": time.time(), "chunks": chunks})
        return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                               alternatives=[stt.SpeechData(language="en", text=text)])


def trim_trailing_silence(path, *, threshold_dbfs=-45.0, window_ms=20, keep_ms=300):
    """16 kHz float samples of a recording without its trailing digital silence.

    Evaluation-side only: Whisper hallucinates tokens ("//") over long silent
    tails of captured output. The recorded file is never modified; the number
    of trimmed seconds is returned so reports can disclose it.
    """
    from faster_whisper import decode_audio
    import numpy
    samples = decode_audio(str(path), sampling_rate=16000)
    window = 16 * window_ms
    threshold = 10 ** (threshold_dbfs / 20)
    end = len(samples)
    while end > 0:
        chunk = samples[max(0, end - window):end]
        if chunk.size and float(numpy.sqrt(numpy.mean(chunk.astype(numpy.float64) ** 2))) >= threshold:
            break
        end -= window
    end = min(len(samples), max(0, end) + 16 * keep_ms)
    return samples[:end], (len(samples) - end) / 16000


SAPI_SCRIPT = '''param([string]$SpeechRoot)
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $voice.SelectVoice('Microsoft David Desktop')
  $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
  $voice.SetOutputToWaveFile((Join-Path $SpeechRoot 'output.wav'), $format)
  $voice.Speak([IO.File]::ReadAllText((Join-Path $SpeechRoot 'text.txt')))
} finally { $voice.Dispose() }
'''


class CommandTTS(tts.TTS):
    """Local synthesizer invoked as a configured command that writes one WAV file.

    argv placeholders: {text_file} (UTF-8 text), {output} (WAV to write) and
    {root} (private temporary directory). Works with Linux engines such as
    espeak-ng ["espeak-ng","-w","{output}","-f","{text_file}"] or piper. Output is
    converted to 16-bit mono at the session rate; the process is killed on
    cancellation or timeout.
    """
    def __init__(self, command, *, profile="command", timeout=30, script=None):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1)
        if not isinstance(command, (list, tuple)) or not command or not all(isinstance(arg, str) for arg in command):
            raise ValueError("TTS command must be a nonempty argv list of strings")
        self.command, self.profile, self.timeout, self.script = list(command), profile, timeout, script
        self.records = []
        self.synthesis_journal = None
        self.journal_lock = threading.Lock()

    def synthesize(self, text, *, conn_options=APIConnectOptions(max_retry=0)):
        return CommandStream(tts=self, input_text=text, conn_options=conn_options)


class SapiTTS(CommandTTS):
    """Windows development profile only; not the organizer-facing route."""
    def __init__(self):
        super().__init__(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", "{root}/speak.ps1", "{root}"],
                         profile="windows-sapi-development", script=SAPI_SCRIPT)


def speech_backend():
    """THREAD_FDB3_TTS_COMMAND (JSON argv) selects a portable engine; Windows falls back to SAPI."""
    configured = os.environ.get("THREAD_FDB3_TTS_COMMAND")
    if configured:
        return CommandTTS(json.loads(configured), profile=os.environ.get("THREAD_FDB3_TTS_PROFILE", "command"))
    if os.name == "nt":
        return SapiTTS()
    raise RuntimeError("Set THREAD_FDB3_TTS_COMMAND to a local synthesizer argv, e.g. "
                       '["espeak-ng","-w","{output}","-f","{text_file}"]')


def pcm16_mono(audio, rate):
    """Raw 16-bit mono PCM at rate from an open wave reader."""
    data, width, channels, source = audio.readframes(audio.getnframes()), audio.getsampwidth(), audio.getnchannels(), audio.getframerate()
    if width != 2:
        data = audioop.lin2lin(data, width, 2)
    if channels == 2:
        data = audioop.tomono(data, 2, .5, .5)
    elif channels != 1:
        raise ValueError("Unsupported synthesized channel count")
    if source != rate:
        data, _ = audioop.ratecv(data, 2, 1, source, rate, None)
    return data


async def kill_process_tree(proc):
    """Stop an engine and any launcher children (venv shims, wrapper scripts)."""
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(proc.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await proc.wait()


class CommandStream(tts.ChunkedStream):
    async def _run(self, output_emitter):
        record = {"request_id":uuid.uuid4().hex,"started_at": time.time(), "text": self._input_text,
                  "outcome": "pending", "profile": self._tts.profile}
        self._tts.records.append(record)
        try:
            await asyncio.to_thread(append_journal,self._tts.synthesis_journal,self._tts.journal_lock,record)
            await self._speak(output_emitter)
            record["outcome"] = "success"
        except BaseException as exc:
            record.update(outcome="cancelled" if isinstance(exc,asyncio.CancelledError) else "error",
                          error_type=type(exc).__name__)
            raise
        finally:
            record["finished_at"] = time.time()
            await asyncio.to_thread(append_journal,self._tts.synthesis_journal,self._tts.journal_lock,record)

    async def _speak(self, output_emitter):
        with tempfile.TemporaryDirectory(prefix="thread-speech-") as directory:
            root = Path(directory)
            (root / "text.txt").write_text(self._input_text, encoding="utf-8")
            if self._tts.script is not None:
                (root / "speak.ps1").write_text(self._tts.script, encoding="utf-8")
            values = {"root": str(root), "text_file": str(root / "text.txt"), "output": str(root / "output.wav")}
            argv = [arg.replace("{root}", values["root"]).replace("{text_file}", values["text_file"])
                    .replace("{output}", values["output"]) for arg in self._tts.command]
            proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                        **({} if os.name == "nt" else {"start_new_session": True}))
            try:
                _, error = await asyncio.wait_for(proc.communicate(), self._tts.timeout)
                if proc.returncode:
                    raise RuntimeError(f"Local {self._tts.profile} synthesis failed: " + error.decode(errors="replace")[:300])
            finally:
                if proc.returncode is None:
                    await kill_process_tree(proc)
            with wave.open(str(root / "output.wav"), "rb") as audio:
                data = pcm16_mono(audio, self._tts.sample_rate)
            output_emitter.initialize(request_id=uuid.uuid4().hex, sample_rate=self._tts.sample_rate,
                                      num_channels=1, mime_type="audio/pcm")
            output_emitter.push(data)


SapiStream = CommandStream  # Historical name kept for existing evidence tooling.


EMPTY_SPEECH_CLARIFICATION = "I could not make out that speech. Please say it again."


class SegmentVAD(vad.VAD):
    """One SDK VAD boundary feeds both interruption and queued offline recognition.

    Unlike StreamAdapter's independent VAD consumer, this stamps identity before
    any decode can backlog. The SDK still receives the original VAD events.
    """
    def __init__(self, detector, bridge):
        super().__init__(capabilities=detector.capabilities)
        self.detector, self.bridge = detector, bridge
        self.segments = asyncio.Queue()
        self.session = self.stream_generation = self.clarification = None
        self.decoder_active = False
        self.delivered_segments = []
        bridge.speech_provenance_required = True
        detector.on("metrics_collected", lambda event: self.emit("metrics_collected", event))

    def stream(self):
        if self.stream_generation is not None:
            raise RuntimeError("The segment boundary requires exactly one SDK VAD stream")
        self.stream_generation = uuid.uuid4().hex
        return SegmentVADStream(self, self.detector.stream(), self.stream_generation)

    def cancel_clarification(self):
        if self.clarification is not None and not self.clarification.done():
            self.clarification.interrupt(force=True)
        self.clarification = None

    async def empty_success(self, sequence, segment_id, generation):
        if generation != self.stream_generation or not self.decoder_active or self.session is None:
            return
        if not await self.bridge.resolve_empty_speech(sequence, segment_id):
            return
        # An old SDK generation may still wait on the retired bridge response.
        # Finish its interruption before admitting the fixed, non-model reply.
        await asyncio.wait_for(self.session.interrupt(force=True), 5)
        if (generation == self.stream_generation and self.decoder_active
                and self.bridge.current_audio_segment(sequence, segment_id)):
            self.clarification = self.session.say(EMPTY_SPEECH_CLARIFICATION, allow_interruptions=True)


class SegmentVADStream:
    """Delegate audio/lifecycle; observe exactly the events consumed by the SDK."""
    def __init__(self, owner, stream, generation):
        self.owner, self.inner, self.generation = owner, stream, generation
        self.segment = None
        self.count = 0
        self.closed = False

    def push_frame(self, frame): self.inner.push_frame(frame)
    def flush(self): self.inner.flush()
    def end_input(self): self.inner.end_input()
    def __aiter__(self): return self

    async def __anext__(self):
        event = await anext(self.inner)
        if event.type == vad.VADEventType.START_OF_SPEECH:
            self.count += 1
            segment_id = f"{self.generation}:{self.count}"
            self.owner.cancel_clarification()
            sequence = self.owner.bridge.speech_started(segment_id)
            self.segment = (sequence, segment_id, self.generation)
            self.owner.bridge.voice_events.append({'event': 'speech_segment_started', 'at': time.time(),
                'segment_id': segment_id, 'input_sequence': sequence, 'samples_index': event.samples_index})
        elif event.type == vad.VADEventType.END_OF_SPEECH and self.segment is not None:
            if self.owner.decoder_active:
                merged = rtc.combine_audio_frames(event.frames)
                # Capture bytes now; no later producer mutation may relabel audio.
                frame = rtc.AudioFrame(bytes(merged.data), merged.sample_rate, merged.num_channels, merged.samples_per_channel)
                self.owner.segments.put_nowait((*self.segment, frame))
            self.segment = None
        return event

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        self.owner.cancel_clarification()
        if self.owner.stream_generation == self.generation:
            self.owner.stream_generation = None
            if self.owner.decoder_active:
                self.owner.segments.put_nowait(None)
            else:
                while not self.owner.segments.empty():
                    self.owner.segments.get_nowait()
        await self.inner.aclose()


class ThreadVoiceAgent(Agent):
    def __init__(self, bridge):
        super().__init__(instructions="Route current speech through THREAD's controller.")
        self.bridge = bridge

    async def on_user_turn_completed(self, turn_ctx, new_message):
        boundary = self._get_activity_or_raise().vad
        if not isinstance(boundary, SegmentVAD):
            return
        # SDK may aggregate final transcripts before endpointing. Bind only an
        # exact FIFO prefix, never look up an identity by matching text globally.
        # The bridge admits an aggregate only if its newest segment is current and
        # every earlier segment belongs to the same open logical turn.
        aggregate = ""
        for index, (sequence, segment_id, text) in enumerate(boundary.delivered_segments):
            aggregate = (aggregate + " " + text).lstrip()
            if aggregate == new_message.text_content:
                consumed = boundary.delivered_segments[:index + 1]
                del boundary.delivered_segments[:index + 1]
                sources = tuple((epoch, identity) for epoch, identity, _ in consumed)
                if self.bridge.bind_speech_message(new_message.id, aggregate, sources):
                    new_message.extra['thread_speech_segments'] = [identity for _, identity in sources]
                    return
                break
        self.bridge.voice_events.append({'event': 'speech_message_unbound', 'at': time.time(),
            'message_id': new_message.id, 'reason': 'no_exact_delivered_prefix'})
        raise StopResponse()

    async def tts_node(self, text, model_settings):
        """Speak the fixed holding line at once; everything else uses the default node.

        The default adapter for a non-streaming synthesizer holds a finished sentence
        until the next one starts, which delayed "One moment ..." until the answer.
        """
        from thread_agent.fdb3 import ACK_TEXT
        source = text.__aiter__()
        try:
            first = await source.__anext__()
        except StopAsyncIteration:
            return
        activity = self._get_activity_or_raise()
        if first.strip() == ACK_TEXT and activity.tts is not None and not activity.tts.capabilities.streaming:
            stream = activity.tts.synthesize(ACK_TEXT, conn_options=activity.session.conn_options.tts_conn_options)
            try:
                async for event in stream:
                    yield event.frame
            finally:
                await stream.aclose()
            async def remaining():
                async for chunk in source:
                    yield chunk
        else:
            async def remaining():
                yield first
                async for chunk in source:
                    yield chunk
        async for frame in Agent.default.tts_node(self, remaining(), model_settings):
            yield frame

    async def stt_node(self, audio, model_settings):
        activity = self._get_activity_or_raise()
        boundary = activity.vad
        if not isinstance(boundary, SegmentVAD):
            async for event in Agent.default.stt_node(self, audio, model_settings):
                yield event
            return
        # SDK fans audio into STT and VAD channels. Consume the STT copy without
        # another detector; the actual recognition buffers come from that VAD.
        async def drain_audio():
            async for _ in audio:
                pass
        drain = asyncio.create_task(drain_audio())
        boundary.decoder_active = True
        try:
            while True:
                segment = await boundary.segments.get()
                if segment is None:
                    return
                sequence, segment_id, generation, frame = segment
                if generation != boundary.stream_generation:
                    continue
                row = {'event': 'speech_segment_recognition', 'at': time.time(), 'segment_id': segment_id,
                       'input_sequence': sequence, 'outcome': 'pending'}
                self.bridge.voice_events.append(row)
                try:
                    event = await activity.stt.recognize(frame, conn_options=activity.session.conn_options.stt_conn_options)
                except BaseException as exc:
                    row.update(outcome='cancelled' if isinstance(exc, asyncio.CancelledError) else 'error',
                               error_type=type(exc).__name__, finished_at=time.time())
                    raise
                text = event.alternatives[0].text if event.alternatives else None
                row.update(outcome='success', text=text, finished_at=time.time())
                if isinstance(text, str) and not text.strip():
                    row['empty_success'] = True
                    await boundary.empty_success(sequence, segment_id, generation)
                elif text:
                    if (generation != boundary.stream_generation
                            or not self.bridge.current_speech_source(sequence, segment_id)):
                        # A newer onset superseded this segment. Same-turn words stay as
                        # context for the next fresh decision; they never mint authority.
                        retained = (generation == boundary.stream_generation
                                    and self.bridge.retain_context(sequence, segment_id, text))
                        row['delivery'] = 'stale_context' if retained else 'stale_dropped'
                        continue
                    boundary.delivered_segments.append((sequence, segment_id, text))
                    row['delivery'] = 'sdk_final'
                    yield stt.SpeechEvent(stt.SpeechEventType.FINAL_TRANSCRIPT,
                        request_id=event.request_id, alternatives=[event.alternatives[0]])
        finally:
            boundary.decoder_active = False
            drain.cancel()
            await asyncio.gather(drain, return_exceptions=True)
            while not boundary.segments.empty():
                boundary.segments.get_nowait()


class ControllerLLM(llm.LLM):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

    def chat(self, *, chat_ctx, tools=None, conn_options=APIConnectOptions(max_retry=0), **kwargs):
        return ControllerStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class ControllerStream(llm.LLMStream):
    async def _run(self):
        latest = next((item for item in reversed(self._chat_ctx.items)
                       if getattr(item, "role", None) == "user"), None)
        if latest is None or not latest.text_content:
            return
        bridge = self._llm.bridge
        def ack(text):
            self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex,
                delta=llm.ChoiceDelta(role="assistant", content=text + " ")))
        extra = {"ack": ack} if getattr(bridge, "ack_after", None) else {}
        response = await bridge.response(latest.text_content, chat_items=self._chat_ctx.items,
            speech_message_id=latest.id if bridge.speech_provenance_required else None, **extra)
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex,
            delta=llm.ChoiceDelta(role="assistant", content=response)))


def create_session(bridge, recognizer, *, manual=False, speech=None):
    boundary = SegmentVAD(silero.VAD.load(), bridge)
    session = AgentSession(stt=recognizer, tts=speech or speech_backend(), llm=ControllerLLM(bridge), vad=boundary,
                           turn_detection="manual" if manual else "vad",
                           preemptive_generation=False, min_endpointing_delay=0.8,
                           max_endpointing_delay=5.0, resume_false_interruption=False)
    boundary.session = session

    @session.on("user_state_changed")
    def changed(event):
        bridge.voice_events.append({'event':'user_state','old':event.old_state,'new':event.new_state,'at':time.time()})

    @session.on("agent_state_changed")
    def agent_changed(event):
        bridge.voice_events.append({'event':'agent_state','old':event.old_state,'new':event.new_state,'at':time.time()})

    @session.on("conversation_item_added")
    def conversation_item_added(event):
        # A committed interrupted item may still contain full generated text.
        # The bridge records it raw but omits uncertain wording from model context.
        bridge.record_assistant_playback(event.item)

    return session


class WaveOutput(voice_io.AudioOutput):
    def __init__(self, path):
        super().__init__(label="recorded PCM", sample_rate=24000,
                         capabilities=voice_io.AudioOutputCapabilities(pause=False))
        self.audio = wave.open(str(path), "wb")
        self.audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        self.frames = 0
        self.segment_seconds = 0
        self.completed = asyncio.Event()
        self.first_frame_at = None
        self.first_signal_at = None
        self.first_signal_offset_seconds = None

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        if self.first_frame_at is None:
            self.first_frame_at = time.time()
        # Diagnostic signal threshold, not semantic speech detection. Record
        # PCM offset separately from wall time; RTP can include leading silence.
        if self.first_signal_at is None and audioop.rms(bytes(frame.data),2)>327.67:
            self.first_signal_at=time.time()
            self.first_signal_offset_seconds=self.frames/24000
        self.audio.writeframes(bytes(frame.data))
        self.frames += frame.samples_per_channel
        self.segment_seconds += frame.samples_per_channel / frame.sample_rate

    def flush(self):
        super().flush()
        self.on_playback_finished(playback_position=self.segment_seconds, interrupted=False)
        self.segment_seconds = 0
        self.completed.set()

    def clear_buffer(self):
        super().flush()
        self.on_playback_finished(playback_position=self.segment_seconds, interrupted=True)
        self.segment_seconds = 0

    def close(self):
        self.audio.close()


class FrameInput(voice_io.AudioInput):
    def __init__(self, frames):
        super().__init__(label="paced recording")
        self.frames = frames

    async def __anext__(self):
        return await anext(self.frames)


async def audio_frames(path, *, paced=True):
    # Same public ffmpeg PCM conversion as pinned upstream livekit_inference.py.
    # Source recording is never modified. This is decoding, not re-recording.
    conversion = await asyncio.to_thread(subprocess.run, ["ffmpeg", "-v", "error", "-i", str(path),
        "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1", "pipe:1"],
        capture_output=True, check=True)
    rate = 48000
    for offset in range(0, len(conversion.stdout), 1920):
        data = conversion.stdout[offset:offset + 1920]
        yield rtc.AudioFrame(data, rate, 1, len(data) // 2)
        if paced:
            await asyncio.sleep(len(data) / (rate * 2))
