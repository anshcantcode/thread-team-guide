"""Authored WebRTC timing controls with SCRIPTED decisions after real STT.

Not model validation, FDB scoring, human-hearing measurement, or a full G2 gate.
Run only after the campaign lock is released; never starts/downloads services.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
from importlib.metadata import version
import json
import math
from numbers import Real
from pathlib import Path
import sys
import threading
import time
import traceback
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.fdb3_run import atomic_json, campaign_lock
from thread_agent.fdb3 import ControllerBridge, wait_until_settled

TOOLS = {"locate_drawer": {"kind": "read_only", "description": "Locate a specimen drawer.",
    "args": {"material": {"type": "string", "required": True}}}}
FIXTURES = {
    "barge": ["Describe the violet lantern.", "Switch to the copper lantern."],
    "pending_read": ["Locate the basalt drawer.", "Keep that search, but answer briefly."],
    "empty_stt": ["Locate the basalt drawer.", "Stop and listen to this correction.", "Describe the amber lantern."],
}
OLD_REPLY = " ".join(["The violet lantern has a violet shade and a violet handle."] * 14)
NEW_REPLY = "The copper lantern has a copper shade. The description is updated."
EMPTY_CLARIFICATION = "I could not make out that speech. Please say it again."


class EmptySTTFault:
    """One declared fault after a real successful decode, never a fake ASR record."""
    def __init__(self, recognize_audio, journal):
        self.recognize_audio, self.journal, self.records = recognize_audio, journal, []

    async def __call__(self, buffer):
        event = await self.recognize_audio(buffer)  # Errors propagate; do not count as successes.
        delivered = deepcopy(event)
        ordinal = len(self.records) + 1
        actual = event.alternatives[0].text if event.alternatives else None
        injected = ordinal == 2
        if injected:
            if not isinstance(actual, str) or not actual.strip():
                raise ValueError("Fault control requires a real nonempty second decode before injecting empty")
            delivered.alternatives[0].text = ""
        self.records.append({"label": "SCRIPTED_STT_FAULT", "at": time.time(),
            "successful_recognition": ordinal, "actual_asr_text": actual,
            "delivered_text": "" if injected else actual, "injected_empty": injected})
        atomic_json(self.journal, self.records)
        return delivered


def trace_responses(bridge, records):
    response = bridge.response
    async def traced(*args, **kwargs):
        row = {"started_at": time.time(), "outcome": "pending"}
        records.append(row)
        try:
            text = await response(*args, **kwargs)
            row.update(outcome="returned", text=text)
            return text
        except BaseException as exc:
            row.update(outcome="cancelled" if isinstance(exc, asyncio.CancelledError) else "error",
                       error_type=type(exc).__name__)
            raise
        finally:
            row["finished_at"] = time.time()
    bridge.response = traced


class ScriptedPlanner:
    """Fixture decision injection; no language-model endpoint or gold data."""
    def __init__(self, control):
        self.control, self.contexts, self.assistant_playback = control, [], []
        self.corrected = asyncio.Event()

    async def setup(self): pass
    async def close(self): pass

    async def plan(self, context):
        row = {**deepcopy(context), "assistant_playback": deepcopy(self.assistant_playback), "at": time.time()}
        self.contexts.append(row)
        turn = len(self.contexts)
        text = next(message["payload"]["text"] for message in reversed(context["messages"])
                    if message["event_type"] == "user_speech_chunk").casefold()
        required = (("violet", "copper") if self.control == "barge" else
                    ("basalt", "amber") if self.control == "empty_stt" else ("basalt", "brief"))
        if turn > 2 or required[turn - 1] not in text:
            raise ValueError("Actual STT did not match the authored control turn; no substitute transcript injected")
        decision = {"intent": "authored_timing_control", "slots": {}, "tool_calls": []}
        if self.control == "barge":
            decision["response"] = OLD_REPLY if turn == 1 else NEW_REPLY
        elif self.control == "empty_stt" and turn == 2:
            decision["response"] = "The amber lantern has an amber shade."
        else:
            step = {"api_name": "locate_drawer", "args": {"material": "basalt"},
                    "response_template": "Original drawer {drawer}." if turn == 1 else "Brief answer: drawer {drawer}."}
            if turn == 2:
                pending = [action for action in context["actions"] if action.get("can_retain_read")
                           and action["api_name"] == "locate_drawer" and action["args"] == step["args"]]
                if len(pending) != 1:
                    raise ValueError("Expected exactly one retainable admitted read at correction")
                step["retain_call_id"] = pending[0]["call_id"]
            decision["tool_calls"] = [step]
        if turn == 2:
            self.corrected.set()
        return decision


class DelayedRegistry:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = []

    def call(self, name, **args):
        self.calls.append({"api_name": name, "args": deepcopy(args), "started_at": time.time()})
        self.entered.set()
        if not self.release.wait(90):
            raise TimeoutError("Controlled read release was not received")
        self.calls[-1]["finished_at"] = time.time()
        return {"status": "success", "drawer": "B-73"}


async def wait_for(predicate, timeout=60):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.025)


def old_reply_word_ends(chunks):
    """Require aligned words for every old-response span; never use segment tail.

    A mixed old/new span is ambiguous, so it cannot establish a stop time. This
    authored-marker diagnostic cannot prove absence of speech omitted by ASR.
    """
    old = [row for row in chunks if "violet" in row.get("text", "").lower()]
    ends = []
    for row in old:
        words = row.get("words", [])
        if "copper" in row["text"].lower() or not words or not any("violet" in word.get("text", "").lower() for word in words):
            return []
        for word in words:
            times = word.get("timestamp")
            if not isinstance(times, list) or len(times) != 2:
                return []
            start, end = times
            if (not isinstance(start, Real) or isinstance(start, bool)
                    or not isinstance(end, Real) or isinstance(end, bool)
                    or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end):
                return []
            ends.append(end)
    return ends


def synthesized_phrase(records, text):
    """Match complete ordered successful chunks; SDK may split at sentences."""
    for start in range(len(records)):
        parts = []
        for row in records[start:]:
            if row.get("outcome") != "success" or not isinstance(row.get("text"), str):
                break
            parts.append(row["text"].strip())
            joined = " ".join(parts)
            if joined == text:
                return True
            if not text.startswith(joined):
                break
    return False


def checks(record):
    """Fail closed on missing evidence; ASR timing is diagnostic, not heard truth."""
    contexts, voice = record.get("planner_contexts", []), record.get("voice_events", [])
    trigger = record.get("correction_started_at", float("inf"))
    onsets = [row["at"] for row in voice if row.get("event") == "user_state"
              and row.get("new") == "speaking" and row["at"] >= trigger]
    result = {"two_actual_stt_turns": len(contexts) == 2 and len(record.get("input_transcripts", [])) >= 2,
              "correction_speech_onset_observed": bool(onsets),
              "received_pcm": record.get("received_frames", 0) > 0,
              "no_runtime_errors": not record.get("errors")}
    if record["control"] == "barge":
        commits = [row for row in voice if row.get("event") == "assistant_playback_committed"]
        interrupted = [row for row in commits if row.get("interrupted") and "violet" in row.get("sdk_committed_text", "").lower()]
        playback = contexts[1].get("assistant_playback", []) if len(contexts) == 2 else []
        known_ids = {row.get("id") for row in interrupted}
        unknown = [row for row in playback if row.get("id") in known_ids]
        result.update(
            correction_during_received_tts=record.get("trigger_agent_state") == "speaking" and record.get("trigger_received_frames", 0) > 0,
            interrupted_old_commit=bool(interrupted),
            unknown_prefix_not_in_planner=bool(unknown) and all(row.get("text") == "" and row.get("delivered_text_unknown") is True for row in unknown),
            no_old_completed_commit=not any(not row.get("interrupted") and "violet" in row.get("sdk_committed_text", "").lower() for row in commits),
        )
        # Segment ends can include a silent gap up to the next reply. Aligned
        # words bound the whole old span, including its possibly clipped tail.
        # Retain the same 1.5s cutoff and fail closed without aligned old words.
        cutoff = (onsets[0] + 1.5) if onsets else float("inf")
        chunks, origin = record.get("output_asr_chunks", []), record.get("output_audio_start_time")
        result["new_reply_in_received_audio"] = any("copper" in row["text"].lower() for row in chunks)
        old_ends = old_reply_word_ends(chunks)
        result["no_stale_audio_after_cutoff"] = bool(old_ends and origin and onsets) and all(
            origin + end <= cutoff for end in old_ends)
    else:
        calls = record.get("actual_tool_calls", [])
        original = [row for row in record.get("operations", []) if row.get("call_id") == record.get("original_call_id")]
        consumers = [row for row in record.get("operations", []) if row.get("retained_from_call_id") == record.get("original_call_id")]
        result.update(
            onset_during_pending_read=bool(onsets and len(calls) == 1 and calls[0].get("timestamp_end")
                and calls[0]["timestamp_start"] < onsets[0] < calls[0]["timestamp_end"]),
            exactly_one_invocation=len(calls) == 1 and len(record.get("registry_calls", [])) == 1,
            original_outcome_retained=bool(len(original) == 1 and original[0].get("status") == "success"
                and original[0].get("result", {}).get("drawer") == "B-73"),
            fresh_consumer_completed=bool(len(consumers) == 1 and consumers[0].get("status") == "success"),
            no_stale_controller_reply=not any(row.get("action") == "final_response" and "Original drawer" in row.get("payload", {}).get("text", "")
                                            for row in record.get("controller_events", [])),
            fresh_reply_in_received_audio="brief" in record.get("output_transcript", "").lower(),
        )
        if record["control"] == "empty_stt":
            result.pop("fresh_consumer_completed")
            result.pop("fresh_reply_in_received_audio")
            fault = record.get("stt_fault_records", [])
            actual = record.get("input_transcripts", [])
            resolved = [row for row in voice if row.get("event") == "empty_speech_resolved"]
            decodes = [row for row in voice if row.get("event") == "speech_segment_recognition"]
            waiters = record.get("response_waiters", [])
            output = " ".join(record.get("output_transcript", "").lower().split())
            result.update(
                explicit_fault_not_natural_perception=record.get("stt_control") == "SCRIPTED_STT_FAULT"
                    and record.get("natural_empty_perception_validation") is False,
                three_real_decodes_one_empty_delivery=len(fault) == 3
                    and len(actual) == 3 and [row.get("text") for row in actual] == [row.get("actual_asr_text") for row in fault]
                    and [row.get("injected_empty") for row in fault] == [False, True, False]
                    and all(isinstance(row.get("actual_asr_text"), str) and row["actual_asr_text"].strip() for row in fault)
                    and fault[1].get("delivered_text") == ""
                    and all(fault[i].get("delivered_text") == fault[i].get("actual_asr_text") for i in (0, 2)),
                current_empty_segment_resolved=len(resolved) == 1 and any(
                    row.get("outcome") == "success" and row.get("empty_success") is True and row.get("text") == ""
                    and row.get("segment_id") == resolved[0].get("segment_id") for row in decodes),
                stale_waiter_retired=bool(waiters and waiters[0].get("finished_at")
                    and (waiters[0].get("outcome") == "cancelled" or
                         (waiters[0].get("outcome") == "returned" and waiters[0].get("text") == ""))
                    and waiters[0]["finished_at"] < record.get("next_utterance_started_at", 0)),
                old_waiter_pending_at_interruption=bool(waiters and onsets
                    and waiters[0].get("started_at", float("inf")) < onsets[0]
                    and waiters[0].get("finished_at", 0) >= onsets[0]),
                fixed_clarification_synthesized=synthesized_phrase(record.get("tts_requests", []), EMPTY_CLARIFICATION),
                fixed_clarification_in_received_audio="could not make out that speech" in output and "please say it again" in output,
                next_current_utterance_works="amber" in output and len(contexts) == 2
                    and any(row.get("action") == "final_response" and "amber" in row.get("payload", {}).get("text", "").lower()
                            for row in record.get("controller_events", [])),
                no_new_effect_or_read_retry=len(record.get("operations", [])) == 1 and not consumers,
                no_stale_reply_in_received_audio="original drawer" not in output,
            )
    return result


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


async def synthesize_fixture(text, path, tts):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        async with tts.synthesize(text) as stream:
            async for chunk in stream:
                audio.writeframes(bytes(chunk.frame.data))


async def run_control(control, output, whisper):
    output.mkdir(parents=True, exist_ok=False)
    record = {"control": control, "status": "running", "started_at": time.time(),
        "planner": "SCRIPTED fixture injection after actual STT", "qualification": False,
        "end_to_end_model_validation": False, "paid_requests": 0, "model_requests": 0,
        "transport": "existing loopback LiveKit WebRTC; actual Whisper STT and SAPI TTS",
        "fixture_texts": FIXTURES[control], "config": {"whisper": str(whisper), "vad": "silero",
            "endpointing_seconds": [.8, 5], "resume_false_interruption": False,
            "stale_audio_cutoff_after_onset_seconds": 1.5, "control_timeout_seconds": 180},
        "limitations": ["Scripted decisions do not validate model comprehension", "SDK committed history is an estimate, not measured human hearing",
            "Word ASR and arrival-clock timing are estimates; missing/mixed old spans fail; omitted speech is not ruled out",
            "Authored race controls do not complete G2"],
        "source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in
            [Path(__file__), ROOT/'scripts/fdb3_run.py'] +
            sorted((ROOT/'participant').glob('*.py')) + sorted((ROOT/'thread_agent').glob('*.py'))}}
    planner, registry = ScriptedPlanner(control), DelayedRegistry()
    bridge = ControllerBridge(TOOLS if control != "barge" else {}, registry, planner)
    bridge.tool_journal = output / "tool-calls.jsonl"
    session = room = sink = recognizer = fixture_tts = None
    errors, pcm_timeline, committed_history, response_waiters = [], [], [], []
    fault = None
    if control == "empty_stt":
        record.update(stt_control="SCRIPTED_STT_FAULT", natural_empty_perception_validation=False,
            fault_preregistration="Replace only completed successful recognition #2 with empty; preserve actual ASR; third decode unchanged")
        record["limitations"].append("Successful-empty STT is explicitly injected; natural empty perception is not validated")
        trace_responses(bridge, response_waiters)
    try:
        atomic_json(output / "result.json", record)
        # Imports deliberately occur only within the lock-protected live runner.
        from thread_agent.fdb3_voice import WhisperSTT, SapiTTS, WaveOutput, create_session
        from thread_agent.fdb3_room import LocalRoom
        record["versions"] = {name: version(name) for name in ["livekit", "livekit-agents", "faster-whisper"]}
        record["whisper_files_sha256"] = {path.name: digest(path) for path in whisper.iterdir() if path.is_file()}
        async with asyncio.timeout(180):
            fixture_tts = SapiTTS()
            fixture_tts.synthesis_journal = output / "fixture-synthesis.jsonl"
            for index, text in enumerate(FIXTURES[control]):
                await synthesize_fixture(text, output / f"input-{index}.wav", fixture_tts)
            recognizer = WhisperSTT(whisper)
            recognizer.transcription_journal = output / "stt-requests.jsonl"
            if control == "empty_stt":
                fault = EmptySTTFault(recognizer._recognize_audio, output / "stt-fault-deliveries.json")
                recognizer._recognize_audio = fault
            sink = WaveOutput(output / "received.wav")
            capture_frame = sink.capture_frame
            async def capture(frame):
                pcm_timeline.append({"received_at": time.time(), "offset_seconds": sink.frames / 24000,
                                     "samples": frame.samples_per_channel, "rate": frame.sample_rate})
                await capture_frame(frame)
            sink.capture_frame = capture
            session = create_session(bridge, recognizer)
            session.tts.synthesis_journal = output / "tts-requests.jsonl"
            session.on("error", lambda event: errors.append(str(event.error)))
            @session.on("conversation_item_added")
            def committed(event):
                item = event.item
                committed_history.append({"at": time.time(), "id": item.id, "role": getattr(item, "role", None),
                    "text": getattr(item, "text_content", None), "interrupted": getattr(item, "interrupted", None)})
            room = LocalRoom(sink)
            record["room"] = room.name
            await bridge.start()
            await room.start(session, bridge)
            await room.play(output / "input-0.wav")
            if control == "barge":
                await wait_for(lambda: session.agent_state == "speaking" and sink.first_signal_at is not None)
                await asyncio.sleep(.3)
            else:
                await wait_for(registry.entered.is_set)
                record["original_call_id"] = bridge.calls[0]["call_id"]
            record.update(correction_started_at=time.time(), trigger_agent_state=session.agent_state,
                          trigger_received_frames=sink.frames)
            await room.play(output / "input-1.wav")
            if control == "empty_stt":
                await wait_for(lambda: any(row.get("event") == "empty_speech_resolved" for row in bridge.voice_events))
                # Preserve the admitted result after empty speech retires its continuation.
                registry.release.set()
                await wait_for(lambda: bridge.controller.operations[record["original_call_id"]]["status"] == "success")
                await wait_for(lambda: synthesized_phrase(session.tts.records, EMPTY_CLARIFICATION))
                await wait_for(lambda: session.agent_state == "listening" and response_waiters
                               and response_waiters[0].get("finished_at"))
                await asyncio.sleep(.5)
                record["next_utterance_started_at"] = time.time()
                await room.play(output / "input-2.wav")
            await asyncio.wait_for(planner.corrected.wait(), 60)
            # The actor must install the fresh consumer before the original read
            # completes. Event-loop polling observes that commit, not planner intent.
            if control == "pending_read":
                await wait_for(lambda: any(op.get("retained_from_call_id") == record["original_call_id"]
                                          for op in bridge.controller.operations.values()))
                registry.release.set()
            await wait_until_settled(session, recognizer, bridge, timeout=80)
            await session.aclose()
            await asyncio.sleep(.5)
            await room.close()
            sink.close()
            if control == "barge":
                record["output_asr_timing"] = "word alignment of received PCM; one offline ASR request"
                record["output_transcript"], record["output_asr_chunks"] = await asyncio.to_thread(
                    recognizer.transcribe, str(output / "received.wav"), filter_silence=True, word_timestamps=True)
            else:
                record["output_transcript"], record["output_asr_chunks"] = await asyncio.to_thread(
                    recognizer.transcribe, str(output / "received.wav"), filter_silence=True)
    except BaseException as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
        record["failure_traceback"] = traceback.format_exc()
        if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
            raise
    finally:
        registry.release.set()
        for component, method in [(session, "aclose"), (bridge, "close"), (room, "close"), (fixture_tts, "aclose")]:
            if component is not None:
                try:
                    await asyncio.wait_for(getattr(component, method)(), 15)
                except BaseException as exc:
                    errors.append("Cleanup " + type(exc).__name__ + ": " + str(exc))
        if sink:
            try:
                sink.close()
            except BaseException as exc:
                errors.append("Cleanup sink " + type(exc).__name__ + ": " + str(exc))
        errors.extend(bridge.evidence_errors)
        record.update(finished_at=time.time(), errors=errors, planner_contexts=planner.contexts,
            controller_events=bridge.events, voice_events=bridge.voice_events, actual_tool_calls=bridge.calls,
            registry_calls=registry.calls, operations=list(bridge.controller.operations.values()),
            input_transcripts=recognizer.records if recognizer else [], stt_attempts=recognizer.attempts if recognizer else [],
            pcm_timeline=pcm_timeline, committed_history=committed_history,
            received_frames=sink.frames if sink else 0, output_audio_start_time=sink.first_frame_at if sink else None,
            tts_requests=session.tts.records if session else [], fixture_tts_requests=fixture_tts.records if fixture_tts else [])
        if control == "empty_stt":
            record.update(stt_fault_records=fault.records if fault else [], response_waiters=response_waiters)
        record["checks"] = checks(record)
        record["checks"]["source_unchanged"] = all(digest(ROOT/name) == expected
            for name, expected in record["source_sha256"].items())
        record["status"] = "passed_local_scripted_control" if all(record["checks"].values()) else "failed_local_scripted_control"
        record["artifact_sha256"] = {path.name: digest(path) for path in output.iterdir() if path.is_file() and path.name != "result.json"}
        atomic_json(output / "result.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--whisper", required=True, type=Path, help="Existing local model directory; no downloads")
    parser.add_argument("--control", choices=["barge", "pending_read", "empty_stt", "both"], default="both")
    args = parser.parse_args()
    # The same exclusive lock covers preparation/synthesis and live execution.
    with campaign_lock(ROOT / ".thread-run"):
        args.output.mkdir(parents=True, exist_ok=False)
        controls = ["barge", "pending_read"] if args.control == "both" else [args.control]
        records = [asyncio.run(run_control(control, args.output / control, args.whisper)) for control in controls]
        atomic_json(args.output / "summary.json", {"qualification": False, "planner": "SCRIPTED", "results": records})
        if any(row["status"] != "passed_local_scripted_control" for row in records):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
