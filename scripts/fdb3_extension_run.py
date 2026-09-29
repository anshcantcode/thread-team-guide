"""Tethered emulator/audio diagnostic. Not G7 completion or a standalone APK agent.

Run only after shared model/CPU benchmark batches stop. Uses an existing local
model endpoint and local Whisper files; never downloads models or starts servers.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    cpu_started = time.process_time()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    spoken_path = output / "spoken.wav"
    room_mode = getattr(args, "room", False)
    record = {"status": "running", "started_at": time.time(), "session_id": None,
              "serial": args.serial, "input_sha256": None, "spoken_sha256": None, "qualification": False,
              "transport": "paced audio through desktop LiveKit AgentSession to adb debug Activity",
              "limitations": ["tethered emulator only", "recorded input, no live microphone or human interruption timing",
                              "no native Clock readback/cancel/update", "no standalone Android speech agent"],
              "output_audio_origin": "received WebRTC PCM" if room_mode else "direct synthesis PCM; no measured playout",
              "paid_requests": 0, "endpoint": args.endpoint, "model": args.model}
    source_root = Path(__file__).resolve().parents[1]
    source_files = [Path(__file__).resolve()] + sorted((source_root/'participant').glob('*.py')) + sorted((source_root/'thread_agent').glob('*.py'))
    def file_hash(path):
        with path.open('rb') as handle:
            return hashlib.file_digest(handle,'sha256').hexdigest()
    record['source_sha256'] = {}
    registry = planner = bridge = recognizer = sink = session = room = sha256 = None
    room_started = False
    errors = []
    failures = []
    failure = None
    sink_closed = False
    output_transcriptions = 0
    completed_input = asyncio.Event()
    input_ready = asyncio.Event()

    def failed(stage, exc):
        nonlocal failure
        failures.append({"stage": stage, "error_type": type(exc).__name__, "error": str(exc)})
        if failure is None:
            failure = exc
            record.update(error_stage=stage, error_type=type(exc).__name__, error=str(exc))
        record["status"] = "infrastructure_error"

    async def frames():
        await input_ready.wait()
        async for frame in audio_frames(args.audio, paced=True):
            yield frame
        completed_input.set()
        await asyncio.Event().wait()

    try:
        record['source_sha256'] = {str(path.relative_to(source_root)): file_hash(path) for path in source_files}
        model_file = getattr(args,'model_file',None)
        record['model_file_identity'] = ({'path':str(Path(model_file).resolve()), 'sha256':file_hash(Path(model_file))}
                                         if model_file else None)
        # Import/constructor failures must leave evidence in the fresh run directory.
        from thread_agent.fdb3 import ControllerBridge, sha256, wait_until_settled
        from thread_agent.fdb3_extension import EmulatorRegistry, ExtensionPlanner, TOOLS
        from thread_agent.fdb3_voice import (WhisperSTT, ThreadVoiceAgent, WaveOutput, FrameInput, audio_frames, create_session,
                                             input_prompt)
        record["input_sha256"] = sha256(args.audio)
        registry = EmulatorRegistry(args.serial, adb=args.adb)
        record["session_id"] = registry.session_id
        planner = ExtensionPlanner(args.endpoint, args.model)
        planner.model_journal = output/'model-requests.jsonl'
        bridge = ControllerBridge(TOOLS, registry, planner)
        bridge.tool_journal = output/'tool-calls.jsonl'
        recognizer = WhisperSTT(args.whisper, prompt=input_prompt(tools=TOOLS))
        record["whisper_prompt"] = recognizer.prompt
        recognizer.transcription_journal = output/'stt-requests.jsonl'
        sink = WaveOutput(spoken_path)
        session = create_session(bridge, recognizer)
        session.tts.synthesis_journal = output/'tts-requests.jsonl'
        if room_mode:
            from thread_agent.fdb3_room import LocalRoom
            room = LocalRoom(sink)
            record.update(transport="local LiveKit WebRTC room through desktop controller to adb debug Activity", room=room.name)
        session.on("error", lambda event: errors.append(str(event.error)))
        await bridge.start()
        if room is not None:
            await room.start(session, bridge)
            room_started = True
            await asyncio.wait_for(room.play(args.audio), 300)
            completed_input.set()
        else:
            session.input.audio = FrameInput(frames())
            session.output.audio = sink
            await session.start(agent=ThreadVoiceAgent(bridge))
            input_ready.set()
        await asyncio.wait_for(completed_input.wait(), 300)
        record["input_finished_at"] = time.time()
        await asyncio.wait_for(sink.completed.wait(), 250)
        await wait_until_settled(session, recognizer, bridge)
        record["processing_finished_at"] = time.time()
    except BaseException as exc:
        failed("runtime", exc)
    finally:
        # Each cleanup is independent; preserve the first error while retaining all
        # later cleanup/evidence errors. Never let one failed close erase the ledger.
        for name, component, method in (("session", session, "aclose"), ("bridge", bridge, "close"),
                                        ("room", room, "close"), ("planner", planner, "close")):
            if component is not None:
                if name == "room" and room_started:
                    try:
                        await asyncio.sleep(.5)  # Retain received RTP after session playout ends.
                    except BaseException as exc:
                        failed("cleanup.room_drain", exc)
                try:
                    await getattr(component, method)()
                except BaseException as exc:
                    failed("cleanup." + name, exc)
        if sink is not None:
            try:
                sink.close()
                sink_closed = True
            except BaseException as exc:
                failed("cleanup.sink", exc)
        if spoken_path.is_file() and sha256 is not None:
            try:
                record["spoken_sha256"] = sha256(spoken_path)
            except BaseException as exc:
                failed("evidence.waveform_hash", exc)
        cancelled = isinstance(failure, (asyncio.CancelledError, KeyboardInterrupt))
        if cancelled:
            record["output_transcription_skipped"] = "run_cancelled"
        if not cancelled and sink_closed and sink.frames and recognizer is not None:
            output_transcriptions += 1
            record["output_transcription_started_at"] = time.time()
            try:
                spoken, chunks = await asyncio.to_thread(recognizer.transcribe, str(spoken_path), filter_silence=True)
                record.update(transcript=spoken, asr_chunks=chunks)
                if not spoken.strip():
                    raise RuntimeError("The generated waveform has no recognized speech")
            except BaseException as exc:
                failed("evidence.output_transcription", exc)
            finally:
                record["output_transcription_finished_at"] = time.time()
        model_requests = getattr(planner, "requests", [])
        input_transcripts = getattr(recognizer, "records", [])
        tts_requests = getattr(getattr(session, "tts", None), "records", [])
        errors.extend(getattr(bridge,'evidence_errors',[]))
        if failure is None and (not sink or not sink.frames or errors
                                or any(r.get("outcome") == "error" for r in model_requests)):
            failed("validation", RuntimeError("Missing speech or runtime error; retain diagnostic evidence"))
        finished_at = time.time()
        try:
            record['source_unchanged'] = bool(record['source_sha256']) and all(file_hash(source_root/name)==digest for name,digest in record['source_sha256'].items())
            if not record['source_unchanged']:
                failed('evidence.source_identity',RuntimeError('Runtime source changed during execution'))
        except BaseException as exc:
            failed('evidence.source_identity',exc)
        cpu_seconds = time.process_time() - cpu_started
        record.update(status="infrastructure_error" if failure is not None else "diagnostic_completed",
                      finished_at=finished_at, actual_tool_calls=getattr(bridge, "calls", []),
                      controller_events=getattr(bridge, "events", []),
                      operations=list(getattr(getattr(bridge, "controller", None), "operations", {}).values()),
                      device_commands=getattr(registry, "records", []),
                      device_transport=getattr(registry, "transport_records", []), input_transcripts=input_transcripts,
                      stt_attempts=getattr(recognizer,'attempts',[]),
                      model_requests=model_requests, errors=errors, failures=failures, tts_requests=tts_requests,
                      first_audio_at=getattr(sink, "first_frame_at", None),
                      voice_events=getattr(bridge, "voice_events", []),
                      output_signal={"threshold_dbfs": -40, "window": "received PCM frame", "official_latency": False,
                          "first_signal_at": getattr(sink, "first_signal_at", None),
                          "first_signal_offset_seconds": getattr(sink, "first_signal_offset_seconds", None)},
                      output_waveform_finalized=sink_closed, worker_cpu_seconds=cpu_seconds,
                      usage={"paid_requests": 0, "local_model_requests": len(model_requests),
                             "model_reported_usage": [r.get("usage") for r in model_requests],
                             "input_stt_requests": len(input_transcripts), "output_stt_requests": output_transcriptions,
                             "tts_requests": len(tts_requests), "worker_cpu_seconds": cpu_seconds,
                             "wall_seconds": finished_at - record["started_at"]})
        try:
            temporary = output / "result.json.tmp"
            temporary.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
            temporary.replace(output / "result.json")
        except BaseException as exc:
            if failure is None:
                failure = exc
            else:
                failure.add_note("Evidence write also failed: " + type(exc).__name__ + ": " + str(exc))
    if failure is not None:
        raise failure


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="Explicit owned emulator-NNNN serial; no auto-selection")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--audio", help="Consented/authored PCM or decodable speech recording")
    parser.add_argument("--output")
    parser.add_argument("--whisper", help="Existing local Whisper model directory")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8097/v1")
    parser.add_argument("--model", default="local-qwen")
    parser.add_argument("--model-file", help="Existing local model file for artifact hashing; actual returned model remains in request evidence")
    parser.add_argument("--room", action="store_true", help="Use the existing loopback LiveKit WebRTC room; default file route captures synthesis, not heard-time")
    parser.add_argument("--cleanup-session", help="Remove only this diagnostic session's local checklist/receipts; never cancels Clock timers")
    args = parser.parse_args()
    if args.cleanup_session:
        from thread_agent.fdb3_extension import EmulatorRegistry
        result = EmulatorRegistry(args.serial, adb=args.adb, session_id=args.cleanup_session).exchange("cleanup")
        print(json.dumps(result, indent=2))
    else:
        if not all((args.audio, args.output, args.whisper)):
            parser.error("--audio, --output and --whisper are required for audio execution")
        asyncio.run(run(args))
