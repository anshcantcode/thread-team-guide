"""Agent process accepts audio only; no scenario IDs, metadata or gold answers."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thread_agent.fdb3 import ControllerBridge, LocalPlanner, load_contract, load_registry, sha256, wait_until_settled
from thread_agent.fdb3_voice import (WhisperSTT, ThreadVoiceAgent, WaveOutput, FrameInput, audio_frames, create_session,
                                     input_prompt,
                                     trim_trailing_silence)


async def run(args):
    cpu_started = time.process_time()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    record = {"status": "running", "started_at": time.time(), "input_sha256": sha256(args.audio),
              "provider": "thread_local", "transport": "LiveKit AgentSession file I/O",
              "endpointing": "manual_eof" if args.manual else "vad",
              "paced_input": not args.unpaced,
              "tool_latency_profile": "instant; unmodified upstream per-API overrides apply",
              "output_asr_identity": {"engine":"faster-whisper","model_path":str(Path(args.whisper).resolve()),
                  "device":os.environ.get("THREAD_FDB3_WHISPER_DEVICE","cpu"),
                  "compute_type":"float16" if os.environ.get("THREAD_FDB3_WHISPER_DEVICE")=="cuda" else "int8",
                  "language":"en","beam_size":5,
                  "vad_filter":True,"condition_on_previous_text":False},
              "output_asr_requests":0,
              "paid_requests": 0, "llm_judge_enabled": False, "qualification": False}
    planner = bridge = recognizer = sink = session = room = None
    errors = []
    completed_input = asyncio.Event()
    input_ready = asyncio.Event()

    async def frames():
        await input_ready.wait()
        async for frame in audio_frames(args.audio, paced=not args.unpaced):
            yield frame
        completed_input.set()
        # Keep the source open until session shutdown; input EOF is not room disconnect.
        await asyncio.Event().wait()

    try:
        planner = LocalPlanner(args.endpoint, args.model)
        planner.model_journal = output/'model-requests.jsonl'
        bridge = ControllerBridge(load_contract(Path(args.contract)), load_registry(Path(args.contract)), planner)
        bridge.tool_journal = output/'tool-calls.jsonl'
        recognizer = WhisperSTT(args.whisper, prompt=input_prompt(args.contract))
        recognizer.transcription_journal = output/'stt-requests.jsonl'
        sink = WaveOutput(output / "spoken.wav")
        session = create_session(bridge, recognizer, manual=args.manual)
        session.tts.synthesis_journal = output/'tts-requests.jsonl'
        if args.room:
            from thread_agent.fdb3_room import LocalRoom
            room = LocalRoom(sink)
            record.update(transport="local LiveKit WebRTC room",room=room.name,paced_input=True)
        session.on("error", lambda event: errors.append(str(event.error)))
        await bridge.start()
        if not room:
            session.input.audio = FrameInput(frames())
            session.output.audio = sink
        if room:
            await room.start(session, bridge)
            await asyncio.wait_for(room.play(args.audio),180)
            completed_input.set()
        else:
            await session.start(agent=ThreadVoiceAgent(bridge))
            input_ready.set()
        await asyncio.wait_for(completed_input.wait(), 180)
        record["input_finished_at"] = time.time()
        if args.manual:
            session.commit_user_turn(transcript_timeout=30, stt_flush_duration=1)
        await asyncio.wait_for(sink.completed.wait(), 250)
        # An early response cannot complete a recording whose later correction
        # is still being planned/spoken. Wait for the current turn to settle.
        await wait_until_settled(session,recognizer,bridge)
        await session.aclose()
        if room:
            await asyncio.sleep(.5)  # Drain received RTP after session playout.
            await room.close()
        sink.close()
        # Evaluate actual generated speech, not the model's planned text.
        record['output_asr_requests'] = 1
        trimmed, record['output_asr_trimmed_trailing_seconds'] = await asyncio.to_thread(
            trim_trailing_silence, output / "spoken.wav")
        spoken, chunks = await asyncio.to_thread(recognizer.transcribe, trimmed, filter_silence=True)
        if not sink.frames or not spoken.strip() or errors or bridge.evidence_errors:
            raise RuntimeError("Missing spoken output or session error")
        record.update(status="completed", transcript=spoken, asr_chunks=chunks)
        if any(request.get("outcome") == "error" for request in planner.requests):
            raise RuntimeError("Planner infrastructure/protocol failure; spoken fallback retained")
    except BaseException as exc:
        record.update(status="infrastructure_error", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        for component, method in ((session, 'aclose'), (bridge, 'close'), (room, 'close'), (planner, 'close')):
            if component is not None:
                try:
                    await getattr(component, method)()
                except BaseException as exc:
                    errors.append('Cleanup: '+type(exc).__name__)
                    record['status'] = 'infrastructure_error'
        if sink is not None:
            try:
                sink.close()
            except BaseException as exc:
                errors.append('Cleanup sink: '+type(exc).__name__)
                record['status']='infrastructure_error'
        errors.extend(bridge.evidence_errors if bridge else [])
        if errors:
            record['status']='infrastructure_error'
        record.update(finished_at=time.time(), actual_tool_calls=bridge.calls if bridge else [],
                      input_transcripts=recognizer.records if recognizer else [], controller_events=bridge.events if bridge else [],
                      admitted_transcripts=[row for row in bridge.controller.messages
                          if row['event_type'] == 'user_speech_chunk'] if bridge else [],
                      stt_attempts=getattr(recognizer,'attempts',[]),
                      operations=list(bridge.controller.operations.values()) if bridge else [], model_requests=planner.requests if planner else [],
                      first_audio_at=sink.first_frame_at if sink else None, errors=errors,
                      stream_start_time=room.stream_start_time if room else None,
                      output_audio_start_time=sink.first_frame_at if sink and room else None,
                      clock_alignment={'available':bool(room and room.stream_start_time and sink.first_frame_at),
                          'input_origin':'wall clock immediately before first RTC AudioSource capture',
                          'output_origin':'wall clock at first received PCM frame callback',
                          'limitations':'Arrival-time alignment includes RTC scheduling/jitter; file output is not paced playout; not organizer latency.'},
                      voice_events=bridge.voice_events if bridge else [],
                      output_signal={'threshold_dbfs':-40,'window':'received PCM frame','official_latency':False,
                          'first_signal_at':sink.first_signal_at if sink else None,
                          'first_signal_offset_seconds':sink.first_signal_offset_seconds if sink else None},
                      worker_cpu_seconds=time.process_time()-cpu_started,
                      injected_tool_latencies=bridge.registry.injector.get_log() if bridge else [],
                      tts_requests=getattr(getattr(session,"tts",None),"records",[]))
        temporary=output/'result.json.tmp'
        temporary.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        temporary.replace(output/'result.json')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--whisper", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8097/v1")
    parser.add_argument("--model", default="local-qwen")
    parser.add_argument("--manual", action="store_true", help="Whole-recording diagnostic, not qualification")
    parser.add_argument("--unpaced", action="store_true", help="Accelerated file diagnostic; invalid for official latency or qualification")
    parser.add_argument("--room", action="store_true", help="Real WebRTC through local loopback LiveKit development server")
    args = parser.parse_args()
    if args.room and (args.manual or args.unpaced):
        parser.error("Room diagnostic requires automatic VAD and real-time input")
    asyncio.run(run(args))
