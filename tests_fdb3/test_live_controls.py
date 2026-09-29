"""Provider-free harness checks only: no SAPI, Whisper, WebRTC or inference."""
import asyncio
import json
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts.fdb3_live_controls import (ScriptedPlanner, DelayedRegistry, TOOLS, checks,
                                      campaign_lock, wait_for, EmptySTTFault, EMPTY_CLARIFICATION, trace_responses,
                                      synthesized_phrase)
from thread_agent.fdb3 import ControllerBridge


def barge_evidence():
    playback = {"id": "old", "text": "", "interrupted": True, "delivered_text_unknown": True}
    return {"control": "barge", "planner_contexts": [{}, {"assistant_playback": [playback]}],
        "input_transcripts": [{"text": "violet"}, {"text": "copper"}], "received_frames": 240000,
        "errors": [], "correction_started_at": 102, "trigger_agent_state": "speaking", "trigger_received_frames": 24000,
        "output_audio_start_time": 100, "output_asr_chunks": [
            {"text": "Violet lantern", "timestamp": [0, 2], "words": [
                {"text": "Violet", "timestamp": [0, 1]}, {"text": "lantern", "timestamp": [1, 2]}]},
            {"text": "Copper lantern", "timestamp": [5, 7]}],
        "voice_events": [{"event": "user_state", "new": "speaking", "at": 102.1},
            {"event": "assistant_playback_committed", "sdk_committed_text": "Violet lantern", **playback}]}


def empty_evidence():
    return {"control": "empty_stt", "stt_control": "SCRIPTED_STT_FAULT", "natural_empty_perception_validation": False,
        "planner_contexts": [{}, {}], "input_transcripts": [{"text": text} for text in ["basalt", "stop", "amber"]], "received_frames": 24000,
        "errors": [], "correction_started_at": 2, "next_utterance_started_at": 7, "original_call_id": "call-1",
        "voice_events": [{"event": "user_state", "new": "speaking", "at": 3},
            {"event": "speech_segment_recognition", "segment_id": "second", "outcome": "success", "text": "", "empty_success": True},
            {"event": "empty_speech_resolved", "segment_id": "second", "at": 4}],
        "actual_tool_calls": [{"timestamp_start": 1, "timestamp_end": 5}], "registry_calls": [{}],
        "operations": [{"call_id": "call-1", "status": "success", "result": {"drawer": "B-73"}}],
        "stt_fault_records": [{"actual_asr_text": text, "delivered_text": "" if i == 1 else text,
                               "injected_empty": i == 1} for i, text in enumerate(["basalt", "stop", "amber"])],
        "response_waiters": [{"started_at": 1, "finished_at": 4.1, "outcome": "returned", "text": ""}],
        "tts_requests": [{"text": EMPTY_CLARIFICATION, "outcome": "success"}],
        "output_transcript": EMPTY_CLARIFICATION + " The amber lantern has an amber shade.",
        "controller_events": [{"action": "final_response", "payload": {"text": "The amber lantern has an amber shade."}}]}


class EvidenceTests(unittest.TestCase):
    def test_sdk_sentence_split_clarification_is_complete_ordered_synthesis(self):
        chunks = [{"text": "I could not make out that speech.", "outcome": "success"},
                  {"text": "Please say it again.", "outcome": "success"}]
        self.assertTrue(synthesized_phrase(chunks, EMPTY_CLARIFICATION))
        row = empty_evidence()
        row["tts_requests"] = chunks
        self.assertTrue(all(checks(row).values()))
        for invalid in [chunks[:1], chunks[1:], list(reversed(chunks)),
                        [chunks[0], {"text": "unrelated", "outcome": "success"}, chunks[1]],
                        [chunks[0], {**chunks[1], "outcome": "pending"}],
                        [chunks[0], {**chunks[1], "outcome": "error"}],
                        [chunks[0], {**chunks[1], "outcome": "cancelled"}],
                        [{"text": None, "outcome": "success"}]]:
            with self.subTest(records=invalid):
                self.assertFalse(synthesized_phrase(invalid, EMPTY_CLARIFICATION))

    def test_complete_barge_evidence_and_unsafe_or_missing_variants(self):
        self.assertTrue(all(checks(barge_evidence()).values()))
        for change, failed in [
            (lambda r: r["planner_contexts"][1]["assistant_playback"][0].update(text="Violet lantern"), "unknown_prefix_not_in_planner"),
            (lambda r: r["planner_contexts"][1].update(assistant_playback=[]), "unknown_prefix_not_in_planner"),
            (lambda r: r["output_asr_chunks"].append({"text": "violet again", "timestamp": [8, 9]}), "no_stale_audio_after_cutoff"),
            (lambda r: r["output_asr_chunks"][0]["words"][-1].update(timestamp=[1, 4]), "no_stale_audio_after_cutoff"),
            (lambda r: r.update(trigger_agent_state="listening"), "correction_during_received_tts"),
            (lambda r: r.update(received_frames=0), "received_pcm"),
            (lambda r: r["errors"].append("capture error"), "no_runtime_errors"),
        ]:
            row = barge_evidence()
            change(row)
            with self.subTest(check=failed): self.assertFalse(checks(row)[failed])

    def test_segment_silent_tail_does_not_extend_old_words_but_late_word_does(self):
        row = barge_evidence()
        row["output_asr_chunks"][0]["timestamp"][1] = 7
        self.assertTrue(checks(row)["no_stale_audio_after_cutoff"])
        # A non-marker old word crossing the unchanged 103.6 cutoff still fails.
        row["output_asr_chunks"][0]["words"][-1]["timestamp"][1] = 3.7
        self.assertFalse(checks(row)["no_stale_audio_after_cutoff"])
        row = barge_evidence()
        row["output_asr_chunks"].append({"text": "Violet returns", "timestamp": [8, 9],
            "words": [{"text": "Violet", "timestamp": [8, 8.5]}, {"text": "returns", "timestamp": [8.5, 9]}]})
        self.assertFalse(checks(row)["no_stale_audio_after_cutoff"])

    def test_missing_mixed_invalid_or_markerless_word_alignment_fails_closed(self):
        for change in [lambda r: r.pop("words"), lambda r: r.update(text="Violet then copper"),
                       lambda r: r["words"][0].update(timestamp=[0, float("nan")]),
                       lambda r: r["words"][0].update(timestamp=[2, 1]),
                       lambda r: r["words"][0].update(text="unclear")]:
            row = barge_evidence()
            change(row["output_asr_chunks"][0])
            self.assertFalse(checks(row)["no_stale_audio_after_cutoff"])

    def test_real_whisper_numpy_timestamps_match_saved_json_without_accepting_bool(self):
        import numpy as np
        row = barge_evidence()
        for word in row["output_asr_chunks"][0]["words"]:
            word["timestamp"] = [np.float64(value) for value in word["timestamp"]]
        self.assertTrue(checks(row)["no_stale_audio_after_cutoff"])
        self.assertEqual(checks(row), checks(json.loads(json.dumps(row))))
        for bad in (True, False, np.bool_(True), np.float64("nan"), np.float64("inf"), "1.0", complex(1, 0)):
            invalid = deepcopy(row)
            invalid["output_asr_chunks"][0]["words"][0]["timestamp"][0] = bad
            with self.subTest(timestamp=bad):
                self.assertFalse(checks(invalid)["no_stale_audio_after_cutoff"])

    def test_missing_evidence_cannot_pass(self):
        for control in ("barge", "pending_read", "empty_stt"):
            self.assertFalse(all(checks({"control": control}).values()))

    def test_empty_fault_requires_every_independent_receipt(self):
        self.assertTrue(all(checks(empty_evidence()).values()))
        for change, failed in [
            (lambda r: r.update(natural_empty_perception_validation=True), "explicit_fault_not_natural_perception"),
            (lambda r: r["stt_fault_records"][1].update(actual_asr_text=""), "three_real_decodes_one_empty_delivery"),
            (lambda r: r["stt_fault_records"][2].update(delivered_text="substitute"), "three_real_decodes_one_empty_delivery"),
            (lambda r: r["input_transcripts"][1].update(text="hidden real ASR"), "three_real_decodes_one_empty_delivery"),
            (lambda r: r["voice_events"][1].update(segment_id="obsolete"), "current_empty_segment_resolved"),
            (lambda r: r["response_waiters"][0].update(outcome="pending"), "stale_waiter_retired"),
            (lambda r: r["response_waiters"][0].update(text="Original drawer B-73"), "stale_waiter_retired"),
            (lambda r: r["response_waiters"][0].update(finished_at=8), "stale_waiter_retired"),
            (lambda r: r["response_waiters"][0].update(finished_at=2), "old_waiter_pending_at_interruption"),
            (lambda r: r.update(tts_requests=[]), "fixed_clarification_synthesized"),
            (lambda r: r.update(output_transcript="The amber lantern."), "fixed_clarification_in_received_audio"),
            (lambda r: r.update(output_transcript=EMPTY_CLARIFICATION), "next_current_utterance_works"),
            (lambda r: r["operations"][0].update(status="cancelled"), "original_outcome_retained"),
            (lambda r: r["operations"].append({"call_id": "call-2"}), "no_new_effect_or_read_retry"),
            (lambda r: r["registry_calls"].append({}), "exactly_one_invocation"),
        ]:
            row = empty_evidence()
            change(row)
            with self.subTest(check=failed): self.assertFalse(checks(row)[failed])

    def test_pending_read_checker_rejects_duplicate_or_lost_original(self):
        row = {"control": "pending_read", "planner_contexts": [{}, {}], "input_transcripts": [{}, {}],
            "received_frames": 24000, "errors": [], "correction_started_at": 2, "original_call_id": "call-1",
            "voice_events": [{"event": "user_state", "new": "speaking", "at": 3}],
            "actual_tool_calls": [{"timestamp_start": 1, "timestamp_end": 4}], "registry_calls": [{}],
            "operations": [{"call_id": "call-1", "status": "success", "result": {"drawer": "B-73"}},
                {"call_id": "call-2", "status": "success", "retained_from_call_id": "call-1"}],
            "output_transcript": "Brief answer drawer B 73", "controller_events": []}
        self.assertTrue(all(checks(row).values()))
        duplicate = deepcopy(row)
        duplicate["registry_calls"].append({})
        self.assertFalse(checks(duplicate)["exactly_one_invocation"])
        lost = deepcopy(row)
        lost["operations"][0].update(status="cancelled", result={})
        self.assertFalse(checks(lost)["original_outcome_retained"])
        outside = deepcopy(row)
        outside["actual_tool_calls"][0]["timestamp_end"] = 2.5
        self.assertFalse(checks(outside)["onset_during_pending_read"])

    def test_campaign_lock_refuses_overlap_without_removing_existing_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with campaign_lock(root):
                owner = (root / "campaign.lock").read_text()
                with self.assertRaises(FileExistsError):
                    with campaign_lock(root): self.fail("Entered overlapping campaign")
                self.assertEqual((root / "campaign.lock").read_text(), owner)
            self.assertFalse((root / "campaign.lock").exists())


class ControllerHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_fault_preserves_actual_records_and_injects_second_success_only(self):
        actual = []
        async def recognize(text):
            if text == "error":
                raise RuntimeError("Decoder failed")
            event = SimpleNamespace(alternatives=[SimpleNamespace(text=text)])
            actual.append(event)
            return event
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "fault.json"
            fault = EmptySTTFault(recognize, journal)
            self.assertEqual((await fault("first")).alternatives[0].text, "first")
            with self.assertRaises(RuntimeError): await fault("error")
            self.assertEqual((await fault("second")).alternatives[0].text, "")
            self.assertEqual((await fault("third")).alternatives[0].text, "third")
            self.assertEqual([row.alternatives[0].text for row in actual], ["first", "second", "third"])
            rows = json.loads(journal.read_text())
            self.assertEqual([row["successful_recognition"] for row in rows], [1, 2, 3])
            self.assertEqual([row["injected_empty"] for row in rows], [False, True, False])
            self.assertEqual(rows[1]["actual_asr_text"], "second")
            self.assertTrue(all(row["label"] == "SCRIPTED_STT_FAULT" for row in rows))

    async def test_fault_refuses_to_claim_injection_for_naturally_empty_decode(self):
        async def recognize(text): return SimpleNamespace(alternatives=[SimpleNamespace(text=text)])
        with tempfile.TemporaryDirectory() as directory:
            fault = EmptySTTFault(recognize, Path(directory) / "fault.json")
            await fault("first")
            with self.assertRaises(ValueError): await fault("")
            self.assertEqual(len(fault.records), 1)

    async def test_empty_control_retires_waiter_preserves_result_and_accepts_next_turn(self):
        planner, registry = ScriptedPlanner("empty_stt"), DelayedRegistry()
        bridge = ControllerBridge(TOOLS, registry, planner)
        waiters = []
        trace_responses(bridge, waiters)
        await bridge.start()
        old = asyncio.create_task(bridge.response("Locate the basalt drawer.", timeout=3))
        try:
            await wait_for(registry.entered.is_set, timeout=2)
            original = bridge.calls[0]["call_id"]
            sequence = bridge.speech_started("injected-test-segment")
            self.assertTrue(await bridge.resolve_empty_speech(sequence, "injected-test-segment"))
            self.assertEqual(await asyncio.wait_for(old, 2), "")
            registry.release.set()
            await wait_for(lambda: bridge.controller.operations[original]["status"] == "success", timeout=2)
            reply = await bridge.response("Describe the amber lantern.", timeout=2)
            self.assertIn("amber", reply)
            self.assertEqual(len(planner.contexts), 2)
            self.assertEqual(len(registry.calls), 1)
            self.assertEqual(len(bridge.controller.operations), 1)
            self.assertEqual(bridge.controller.operations[original]["result"]["drawer"], "B-73")
            self.assertEqual(waiters[0]["outcome"], "returned")
            self.assertEqual(waiters[0]["text"], "")
            self.assertLess(waiters[0]["finished_at"], waiters[1]["started_at"])
            finals = [row["payload"]["text"] for row in bridge.events if row["action"] == "final_response"]
            self.assertEqual(finals, ["The amber lantern has an amber shade."])
        finally:
            registry.release.set()
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
            await bridge.close()

    async def test_script_refuses_wrong_actual_transcript(self):
        planner = ScriptedPlanner("barge")
        with self.assertRaises(ValueError):
            await planner.plan({"messages": [{"event_type": "user_speech_chunk", "payload": {"text": "unrelated words"}}]})
        self.assertFalse(planner.corrected.is_set())

    async def test_scripted_barge_context_uses_sanitized_committed_receipt(self):
        planner, registry = ScriptedPlanner("barge"), DelayedRegistry()
        bridge = ControllerBridge({}, registry, planner)
        await bridge.start()
        try:
            first = await bridge.response("Describe the violet lantern.", timeout=2)
            self.assertIn("violet", first)
            item = SimpleNamespace(type="message", role="assistant", id="old", text_content=first, interrupted=True)
            bridge.record_assistant_playback(item)
            bridge.speech_started()  # Harness injection, not live speech evidence.
            second = await bridge.response("Switch to the copper lantern.", chat_items=[item], timeout=2)
            self.assertIn("copper", second)
            receipt = planner.contexts[1]["assistant_playback"][0]
            self.assertEqual(receipt["text"], "")
            self.assertTrue(receipt["delivered_text_unknown"])
            self.assertEqual(registry.calls, [])
        finally:
            await bridge.close()

    async def test_pending_original_read_retained_once_with_fresh_consumer(self):
        planner, registry = ScriptedPlanner("pending_read"), DelayedRegistry()
        bridge = ControllerBridge(TOOLS, registry, planner)
        await bridge.start()
        try:
            await bridge.submit("Locate the basalt drawer.")
            await wait_for(registry.entered.is_set, timeout=2)
            original = deepcopy(bridge.calls[0])
            bridge.speech_started()  # Harness injection, not live VAD evidence.
            await bridge.submit("Keep that search, but answer briefly.")
            await asyncio.wait_for(planner.corrected.wait(), 2)
            await wait_for(lambda: len(bridge.controller.operations) == 2, timeout=2)
            registry.release.set()
            await wait_for(lambda: all(op["status"] == "success" for op in bridge.controller.operations.values()), timeout=2)
            await bridge.synchronize()
            await asyncio.sleep(.02)
            self.assertEqual(len(registry.calls), 1)
            self.assertEqual(bridge.calls[0]["call_id"], original["call_id"])
            self.assertEqual(bridge.calls[0]["outcome"], "success")
            operations = list(bridge.controller.operations.values())
            self.assertEqual(operations[0]["revision"], original["revision"])
            self.assertEqual(operations[0]["result"]["drawer"], "B-73")
            self.assertEqual(operations[1]["retained_from_call_id"], original["call_id"])
            finals = [row["payload"]["text"] for row in bridge.events if row["action"] == "final_response"]
            self.assertEqual(finals, ["Brief answer: drawer B-73."])
        finally:
            registry.release.set()
            await bridge.close()


if __name__ == "__main__": unittest.main()
