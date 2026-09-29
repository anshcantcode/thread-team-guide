"""Independent mocked-transport checks for the explicit single-call read mode.

Generic transcripts and old transport fixtures only. These checks do not measure
speech recognition, provider performance, or rate-limit compliance.
"""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from participant.agent import ParticipantAgent
from participant.planner import Planner
from evaluation.submission_delivery.test_audio_agreement import AudioAgreementTests, observation, search
from evaluation.submission_delivery.test_flight_chain import TOOLS
from tests import test_participant_controller as queues


FLAG = "_audio_joint_only"
NOTE = "Create a note with text lantern audit."
NOTE_TOOL = {"kind": "state_modifying", "description": "Create a note.",
             "args": {"text": {"type": "string", "required": True}}, "delay_range_ms": [0, 8000]}


class AudioSingleCallReadTests(unittest.IsolatedAsyncioTestCase):
    event, speak, output, result, drain = (queues.ControllerTests.event, queues.ControllerTests.speak,
        queues.ControllerTests.output, queues.ControllerTests.result, queues.ControllerTests.drain)

    async def asyncSetUp(self):
        await AudioAgreementTests.asyncSetUp(self)
        (self.root / "2.mp3").write_bytes((self.root / "0.mp3").read_bytes())
        self.evidence = {"sessions": [], "external_provider_calls": 0}

    async def start(self, label, *, mode="single_call_reads", route="read", uncertain=False):
        script = SimpleNamespace(route=route, uncertain=uncertain, defect=None, forge=False,
            delay=0, hold=False, main_fault=None, main_gate=None,
            entered=asyncio.Event(), release=asyncio.Event(), returned=asyncio.Event())
        transcripts = {0: "Book a flight to Dunedin.", 1: "Actually make that Hobart.", 2: NOTE}
        calls = []

        async def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertTrue(request.url.path.endswith(":generateContent"))
            body = json.loads(request.content)
            acoustic = "perception only" in body["systemInstruction"]["parts"][0]["text"]
            targets = [v["properties"]["message_index"]["enum"][0] for v in
                body["generationConfig"]["responseJsonSchema"]["properties"]["observations"]["items"].get("anyOf", [])]
            parts = body["contents"][0]["parts"]
            sources = [hashlib.sha256(base64.b64decode(p["inlineData"]["data"])).hexdigest()
                       for p in parts if "inlineData" in p]
            calls.append({"route": "acoustic" if acoustic else "main", "targets": targets,
                          "media_sha256": sources,
                          "body_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()})
            self.assertNotIn(FLAG, json.dumps(body), "Private provenance leaked into the native prompt")
            rows = [observation(i, transcripts[i], script.uncertain and i == targets[-1]) for i in targets]
            if acoustic:
                if script.hold:
                    script.entered.set()
                    try:
                        await script.release.wait()
                    except asyncio.CancelledError:
                        await script.release.wait()  # Simulate an uncooperative late transport.
                if script.defect == "missing":
                    rows = [row for row in rows if row["message_index"] != 0]
                elif script.defect == "uncertain":
                    next(row for row in rows if row["message_index"] == 1)["uncertain"] = True
                elif script.defect == "conflicting":
                    rows[0]["transcript"] = "Book a flight to Gaborone."
                reply = {"observations": rows}
            else:
                if script.main_gate is not None:
                    entered, release = script.main_gate
                    script.main_gate = None
                    entered.set()
                    await release.wait()
                if script.main_fault:
                    fault, script.main_fault = script.main_fault, None
                    calls[-1]["fault"] = fault
                    if fault == "transport_timeout":
                        raise httpx.ReadTimeout("Offline first-MAIN timeout")
                    if fault == "missing_rows":
                        rows = []
                if script.delay:
                    await asyncio.sleep(script.delay)
                if script.forge:
                    for row in rows:
                        row[FLAG] = False
                reply = {"observations": rows, "intent": "search_flights", "slots": {"destination": "Hobart"},
                         "tool_calls": [search("Hobart")], "response": None, "clarification": None}
                if script.route == "clarify":
                    reply.update(tool_calls=[], clarification="Which destination did you mean?")
                elif script.route == "write":
                    reply.update(intent="note", slots={"text": "lantern audit"}, tool_calls=[{
                        "api_name": "create_note", "args": {"text": "lantern audit"},
                        "authorization": {"quote": NOTE}, "response_template": "Note {note_id}."}])
            if acoustic:
                script.returned.set()
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
                "content": {"parts": [{"text": json.dumps(reply)}]}}]})

        planner = Planner(transport=httpx.MockTransport(handler))
        with patch.dict(os.environ, {} if mode is None else {"PARTICIPANT_AUDIO_MODE": mode}):
            await planner.setup()
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        session = SimpleNamespace(agent=agent, planner=planner, script=script, calls=calls,
                                  task=asyncio.create_task(agent.run()))
        self.addAsyncCleanup(self.stop, session)
        self.evidence["sessions"].append({"label": label, "mocked_generation_starts": calls})
        await self.event(agent, "tool_manifest", {"tools": {**deepcopy(TOOLS), "create_note": deepcopy(NOTE_TOOL)}})
        return session

    async def stop(self, session):
        session.script.release.set()
        session.task.cancel()
        await asyncio.gather(session.task, return_exceptions=True)

    async def first_turn(self, session):
        await self.event(session.agent, "user_audio_chunk", {"audio_ref": "0.mp3", "end_of_turn": False})
        await self.event(session.agent, "user_audio_chunk", {"audio_ref": "1.mp3", "end_of_turn": True})

    async def finish_read(self, session):
        call = await self.output(session.agent, "tool_call", timeout=2)
        self.assertEqual(call["payload"]["api_name"], "flight_search")
        self.assertFalse([row for row in self.drain(session.agent)
                          if row["action"] in {"tool_call", "final_response", "clarification_request"}],
                         "Booking follow-through must wait for an actual read result")
        await self.result(session.agent, call, {"flights": [{"flight_id": "QA-782", "depart": "07:40", "price_usd": 219}]})
        final = await self.output(session.agent, "final_response", timeout=2)
        self.assertIn("QA-782", final["payload"]["text"])
        return self.drain(session.agent)

    def source_key(self, session, index):
        return [index, session.agent.messages[index]["revision"], "audio/mpeg",
                hashlib.sha256((self.root / f"{index}.mp3").read_bytes()).hexdigest()]

    def assert_joint_history(self, session, keys=None):
        for index in (0, 1):
            marker = session.agent.observations[index][FLAG]
            self.assertIsInstance(marker, (list, tuple))
            self.assertEqual(list(marker), keys[index] if keys else self.source_key(session, index))
        self.assertEqual(session.planner._audio_cache, {})

    async def test_read_clarification_uncertainty_and_default_routes(self):
        default_bodies = None
        for label, mode, route, uncertain in (("joint_read", "single_call_reads", "read", False),
                ("joint_clarification", "single_call_reads", "clarify", False),
                ("joint_uncertain", "single_call_reads", "read", True),
                ("default_independent", None, "read", False),
                ("explicit_independent", "independent", "read", False)):
            with self.subTest(route=label):
                s = await self.start(label, mode=mode, route=route, uncertain=uncertain)
                await self.first_turn(s)
                await self.output(s.agent, "clarification_request" if uncertain or route == "clarify" else "tool_call", timeout=2)
                independent = mode in (None, "independent")
                self.assertEqual(sorted(row["route"] for row in s.calls), ["acoustic", "main"] if independent else ["main"])
                self.assertTrue(all(row["targets"] == [0, 1] for row in s.calls))
                record = next(row for row in reversed(s.planner.evidence) if row.get("phase") == "planning")
                self.assertEqual(s.planner.audio_mode, mode or "independent")
                self.assertEqual(record["audio_mode"], mode or "independent")
                if independent:
                    self.assertEqual(len(s.planner._audio_cache), 2)
                    self.assertFalse(any(FLAG in row for row in s.agent.observations.values()))
                    self.assertEqual(record["audio_admission"], "independent")
                    bodies = sorted((row["route"], row["body_sha256"]) for row in s.calls)
                    if mode is None:
                        default_bodies = bodies
                    else:
                        self.assertEqual(bodies, default_bodies)
                else:
                    self.assert_joint_history(s)
                    self.assertEqual(s.agent._user_texts(), [])
                    if uncertain:
                        self.assertIn(record["audio_admission"], {"blocked", "joint_no_effect"})
                    else:
                        self.assertEqual(record["audio_admission"], "joint_read" if route == "read" else "joint_no_effect")
                if uncertain or route == "clarify":
                    self.assertEqual(s.agent.operations, {})
                await self.stop(s)

    async def test_actual_read_result_can_ask_booking_details_without_authority(self):
        s = await self.start("actual_result_booking_followup")
        await self.first_turn(s)
        following = await self.finish_read(s)
        questions = [row["payload"]["text"] for row in following if row["action"] == "clarification_request"]
        self.assertTrue(any("passenger" in text.lower() and "flight" in text.lower() for text in questions))
        self.assertEqual(len(s.calls), 1)
        self.assert_joint_history(s)
        self.assertEqual(s.agent._user_texts(), [])
        self.assertEqual([row["transcript"] for row in s.agent.observations.values()],
                         ["Book a flight to Dunedin.", "Actually make that Hobart."])
        self.assertTrue(all(op["kind"] == "read_only" for op in s.agent.operations.values()))
        expected = [hashlib.sha256((self.root / f"{i}.mp3").read_bytes()).hexdigest() for i in (0, 1)]
        self.assertEqual(s.calls[0]["media_sha256"], expected)
        record = next(row for row in reversed(s.planner.evidence) if row.get("phase") == "planning")
        self.assertEqual([row["sha256"] for row in record["input_media"]], expected)
        self.assertEqual(record["native_audio_observations"],
                         [observation(0, "Book a flight to Dunedin."), observation(1, "Actually make that Hobart.")])
        self.assertEqual(record["native_audio_sha256"], {index: hashlib.sha256(text.encode()).hexdigest()
            for index, text in enumerate(("Book a flight to Dunedin.", "Actually make that Hobart."))})

    async def test_untrusted_markers_cannot_promote_old_rows(self):
        variants = (("native_missing", None), ("native_false", False), ("stored_missing", None),
                    ("stored_row_missing", None),
                    ("stored_false", False), ("stored_none", None), ("stored_empty", []),
                    ("stored_true", True), ("stored_bad_key", [0, 999, "audio/mpeg", "0" * 64]))
        for label, value in variants:
            with self.subTest(marker=label):
                s = await self.start(label)
                await self.first_turn(s)
                await self.finish_read(s)
                stored = label.startswith("stored_")
                if label == "stored_row_missing":
                    del s.agent.observations[0]
                elif label == "stored_missing":
                    s.agent.observations[0].pop(FLAG)
                elif stored:
                    s.agent.observations[0][FLAG] = deepcopy(value)
                s.script.forge = label == "native_false"
                self.assertEqual(s.agent._user_texts(), [])
                await self.speak(s.agent, "Show the flight options again.")
                await self.output(s.agent, "clarification_request" if stored else "tool_call", timeout=2)
                self.assertEqual([row["route"] for row in s.calls], ["main"] if stored else ["main", "main"])
                self.assertTrue(all(row["targets"] == [0, 1] for row in s.calls))
                self.assertEqual(s.planner._audio_cache, {})
                self.assertFalse(any(index in (0, 1) for index, _ in s.agent._user_texts()))
                if stored:
                    self.assertEqual(len(s.agent.operations), 1, "Invalid history must not dispatch another tool")
                else:
                    self.assert_joint_history(s)
                await self.stop(s)

    async def test_later_text_and_audio_writes_require_complete_old_sources(self):
        for current in ("text", "audio"):
            for defect in (None, "missing", "uncertain", "conflicting", "out_of_budget"):
                with self.subTest(current=current, defect=defect):
                    s = await self.start(f"later_{current}_{defect or 'complete'}")
                    await self.first_turn(s)
                    await self.finish_read(s)
                    s.script.route, s.script.defect = "write", defect
                    if defect == "out_of_budget":
                        s.script.delay = s.planner.acoustic_timeout + .05
                    if current == "text":
                        await self.speak(s.agent, NOTE)
                    else:
                        await self.event(s.agent, "user_audio_chunk", {"audio_ref": "2.mp3", "end_of_turn": True})
                    action = await self.output(s.agent, "tool_call" if defect is None else "clarification_request", timeout=6)
                    expected = [0, 1] if current == "text" else [0, 1, 2]
                    self.assertEqual(s.calls[1]["targets"], expected)
                    self.assertEqual([row["route"] for row in s.calls],
                                     ["main", "main"] if defect == "out_of_budget" else ["main", "main", "acoustic"])
                    if defect != "out_of_budget":
                        self.assertEqual(s.calls[2]["targets"], expected)
                    if defect is None:
                        self.assertEqual(action["payload"]["api_name"], "create_note")
                        self.assertFalse(any(FLAG in s.agent.observations[i] for i in expected))
                        self.assertEqual({key[0] for key in s.planner._audio_cache}, set(expected))
                        for key in s.planner._audio_cache:
                            index, revision, mime, digest = key
                            self.assertEqual(revision, s.agent.messages[index]["revision"])
                            self.assertEqual(mime, "audio/mpeg")
                            self.assertEqual(digest, hashlib.sha256((self.root / f"{index}.mp3").read_bytes()).hexdigest())
                    else:
                        self.assert_joint_history(s)
                        self.assertFalse(any(index in expected for index, _ in s.agent._user_texts()))
                        self.assertEqual(len(s.agent.operations), 1, "Incomplete evidence must not dispatch another tool")
                    await self.stop(s)

    async def test_fresh_typed_write_recovers_after_main_never_produced_observations(self):
        for fault, changed in (("missing_rows", False), ("transport_timeout", False), ("missing_rows", True)):
            with self.subTest(first_main_fault=fault, pending_source_changed=changed):
                s = await self.start(f"recovery_{fault}" + ("_source_changed" if changed else ""))
                s.script.main_fault = fault
                await self.first_turn(s)
                await self.output(s.agent, "clarification_request", timeout=2)
                self.assertEqual(s.agent.observations, {})
                self.assertEqual(s.planner._audio_cache, {})
                self.assertEqual(s.agent.operations, {})
                self.assertEqual([row["route"] for row in s.calls], ["main"])

                s.script.route, s.script.hold = "write", True
                if changed:
                    (self.root / "0.mp3").write_bytes((self.root / "1.mp3").read_bytes())
                await self.speak(s.agent, NOTE)
                if changed:
                    await self.output(s.agent, "clarification_request", timeout=2)
                    self.assertEqual([row["route"] for row in s.calls], ["main"])
                    self.assertEqual(s.agent.observations, {})
                    self.assertEqual(s.planner._audio_cache, {})
                    self.assertEqual(s.agent.operations, {}, "A pending source identity cannot be replaced")
                    await self.stop(s)
                    continue
                await asyncio.wait_for(s.script.entered.wait(), 2)
                self.assertEqual([row["route"] for row in s.calls], ["main", "main", "acoustic"])
                self.assertTrue(all(row["targets"] == [0, 1] for row in s.calls))
                expected = [self.source_key(s, index)[3] for index in (0, 1)]
                self.assertTrue(all(row["media_sha256"] == expected for row in s.calls))
                self.assertEqual(s.planner._audio_cache, {})
                self.assertEqual(s.agent.observations, {})
                self.assertEqual(s.agent.operations, {}, "Fresh text cannot substitute for an acoustic witness")
                s.script.release.set()
                call = await self.output(s.agent, "tool_call", timeout=2)
                self.assertTrue(s.script.returned.is_set())
                self.assertEqual(call["payload"]["api_name"], "create_note")
                self.assertEqual(call["payload"]["args"], {"text": "lantern audit"})
                self.assertEqual(set(s.planner._audio_cache), {tuple(self.source_key(s, index)) for index in (0, 1)})
                self.assertFalse(any(FLAG in row for row in s.agent.observations.values()))
                self.assertEqual(len(s.agent.operations), 1)
                await self.result(s.agent, call, {"note_id": "QA-919"})
                final = await self.output(s.agent, "final_response", timeout=2)
                self.assertIn("QA-919", final["payload"]["text"])
                self.assertEqual(len(s.calls), 3)
                await self.stop(s)

    async def test_queued_input_discards_ready_joint_plan_without_losing_source_identity(self):
        s = await self.start("ready_joint_plan_discarded")
        entered, release = asyncio.Event(), asyncio.Event()
        s.script.main_gate = (entered, release)
        await self.first_turn(s)
        await asyncio.wait_for(entered.wait(), 2)
        ready = s.agent._plan_task
        self.assertIsNotNone(ready)
        self.assertFalse(ready.done())
        discarded = []

        def queue_correction(task):
            if not task.cancelled():
                discarded.append((task.result(), deepcopy(s.agent.observations), deepcopy(s.planner._audio_cache)))
                s.agent.in_queue.put_nowait({"timestamp_ms": 0, "event_type": "user_speech_chunk",
                    "payload": {"text": "Show the flight options again.", "end_of_turn": True}})

        ready.add_done_callback(queue_correction)
        release.set()
        await self.finish_read(s)
        self.assertEqual(len(discarded), 1)
        (old_revision, decision), stored, cached = discarded[0]
        self.assertEqual(stored, {})
        self.assertEqual(cached, {})
        self.assertEqual(len(decision["observations"]), 2)
        self.assertTrue(all(FLAG in row for row in decision["observations"]))
        self.assertLess(old_revision, s.agent.revision)
        self.assertEqual([op["revision"] for op in s.agent.operations.values()], [s.agent.revision])
        self.assertEqual([row["route"] for row in s.calls], ["main", "main"])
        self.assertTrue(all(row["targets"] == [0, 1] for row in s.calls))
        self.assert_joint_history(s)
        self.evidence["ready_plan_discard"] = {"discarded_revision": old_revision,
            "accepted_revision": s.agent.revision, "stored_rows_at_discard": len(stored), "cache_rows_at_discard": len(cached)}

        # Actual storage must retire the pending binding; it cannot rescue later row loss.
        del s.agent.observations[0]
        s.script.route = "write"
        await self.speak(s.agent, NOTE)
        await self.output(s.agent, "clarification_request", timeout=2)
        self.assertEqual(len(s.calls), 2)
        self.assertEqual(len(s.agent.operations), 1)
        self.assertEqual(s.planner._audio_cache, {})

    async def test_cancelled_superseded_or_changed_source_cannot_publish_history(self):
        for invalidation in ("cancelled", "superseded", "changed_source"):
            with self.subTest(invalidation=invalidation):
                s = await self.start(invalidation)
                await self.first_turn(s)
                await self.finish_read(s)
                original_keys = {index: self.source_key(s, index) for index in (0, 1)}
                s.script.route, s.script.hold = "write", True
                await self.speak(s.agent, NOTE)
                await asyncio.wait_for(s.script.entered.wait(), 2)
                revision = s.agent.revision
                s.script.route = "clarify"
                if invalidation == "superseded":
                    await self.speak(s.agent, "Please clarify the options.")
                elif invalidation == "changed_source":
                    (self.root / "0.mp3").write_bytes((self.root / "1.mp3").read_bytes())
                else:
                    await self.event(s.agent, "interruption")
                async def revised():
                    while s.agent.revision == revision:
                        await asyncio.sleep(0)
                if invalidation != "changed_source":
                    await asyncio.wait_for(revised(), 2)
                s.script.release.set()
                await asyncio.wait_for(s.script.returned.wait(), 2)
                if invalidation != "cancelled":
                    await self.output(s.agent, "clarification_request", timeout=2)
                await asyncio.wait_for(asyncio.gather(*list(s.planner._pending_tasks), return_exceptions=True), 2)
                await self.stop(s)
                self.assert_joint_history(s, original_keys)
                self.assertEqual(len(s.agent.operations), 1, "Stale verification must not dispatch another tool")
                self.assertEqual([row["route"] for row in s.calls],
                                 ["main", "main", "acoustic", "main"] if invalidation == "superseded" else ["main", "main", "acoustic"])

    async def test_changed_missing_or_invalid_retained_source_blocks_before_generation(self):
        original = (self.root / "0.mp3").read_bytes()
        for defect in ("changed", "missing", "invalid_media"):
            with self.subTest(source=defect):
                (self.root / "0.mp3").write_bytes(original)
                s = await self.start(f"retained_source_{defect}")
                await self.first_turn(s)
                await self.finish_read(s)
                original_keys = {index: self.source_key(s, index) for index in (0, 1)}
                if defect == "missing":
                    (self.root / "0.mp3").unlink()
                else:
                    replacement = (self.root / "1.mp3").read_bytes() if defect == "changed" else b"not an MP3"
                    (self.root / "0.mp3").write_bytes(replacement)
                await self.speak(s.agent, "Show the flight options again.")
                await self.output(s.agent, "clarification_request", timeout=2)
                s.script.route = "write"
                await self.speak(s.agent, NOTE)
                await self.output(s.agent, "clarification_request", timeout=2)
                self.assertEqual([row["route"] for row in s.calls], ["main"])
                self.assert_joint_history(s, original_keys)
                self.assertEqual(len(s.agent.operations), 1, "Invalid source must not dispatch another tool")
                await self.stop(s)
