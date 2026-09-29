"""Independent mocked-pipeline controls for current audio agreement.

Tiny MP3s exercise transport/attachment only. All speech observations are scripted;
these checks make no claim about acoustic understanding or provider performance.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from participant import planner as planner_module
from participant.planner import Planner
from evaluation.submission_delivery.test_flight_chain import TOOLS


def observation(index, text, uncertain=False):
    return {"message_index": index, "type": "audio", "transcript": text, "uncertain": uncertain}


def search(destination="Porto"):
    return {"api_name": "flight_search", "args": {"destination": destination},
            "response_template": "Flight {flights.0.flight_id}, departure {flights.0.depart}."}


class AudioAgreementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        # Use this independent checkout's old public transport fixtures.
        fixtures = Path(__file__).resolve().parents[2] / "tests/fixtures/mp3"
        for index, name in enumerate(("tone-cbr.mp3", "tone-vbr.mp3")):
            (self.root / f"{index}.mp3").write_bytes((fixtures / name).read_bytes())
        env = patch.dict(os.environ, {"SECRET_GEMINI_API_KEY": "offline-nonsecret-audio-sentinel",
                        "PARTICIPANT_PREWARM": "0", "PARTICIPANT_IMAGE_EMBEDDING": "0",
                        "PARTICIPANT_MEDIA_ROOT": str(self.root)}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def context(self, count):
        return {"revision": count, "current_turn_start": count - 1,
                "messages": [{"message_index": index, "revision": index + 1,
                              "event_type": "user_audio_chunk", "payload": {
                                  "audio_ref": f"{index}.mp3", "end_of_turn": True}}
                             for index in range(count)],
                "state": {"intent": "", "slots": {}}, "tools": deepcopy(TOOLS),
                "observations": [], "actions": [], "tool_results": [], "latest_frame_index": None,
                "planning_error": None, "tail_remaining_ms": None}

    async def two_turn(self, main, acoustic, *, uncertain=False, fail_current=False, proposal=None,
                       prior_main="Book a flight to [cough] Boston.",
                       prior_acoustic="Book of Flight 2 [cough] [throat-clearing] First", prior_uncertain=False):
        exchanges, self.native_decisions = [], []

        def handler(request):
            body = json.loads(request.content)
            native = "perception only" in body["systemInstruction"]["parts"][0]["text"]
            targets = [variant["properties"]["message_index"]["enum"][0] for variant in
                       body["generationConfig"]["responseJsonSchema"]["properties"]["observations"]["items"]["anyOf"]]
            exchanges.append({"acoustic": native, "targets": targets})
            if native and 1 in targets and fail_current:
                return httpx.Response(503, json={"error": "offline forced acoustic failure"})
            texts = (prior_acoustic, acoustic) if native else (prior_main, main)
            result = {"observations": [observation(i, texts[i], native and (
                       i == 1 and uncertain or i == 0 and prior_uncertain)) for i in targets]}
            if not native:
                destination = "Porto" if 1 in targets else "Boston"
                result.update(intent="search_flights", slots={"destination": destination}, clarification=None,
                              response=None, tool_calls=[search(destination)])
                if proposal is not None and 1 in targets:
                    result.update(deepcopy(proposal))
                self.native_decisions.append(deepcopy(result))
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
                                  "content": {"parts": [{"text": json.dumps(result)}]}}]})

        planner = Planner(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(planner.close)
        await planner.setup()
        initial = await planner.plan(self.context(1))
        self.assertEqual(initial["tool_calls"], [], "The retained wrong-native first clip must still be blocked")
        self.assertTrue(initial["clarification"])
        self.assertTrue(initial["observations"][0]["uncertain"])
        previous_cache = deepcopy(planner._audio_cache)
        self.assertEqual(len(previous_cache), 1)
        current = self.context(2)
        current["observations"] = deepcopy(initial["observations"])
        original = deepcopy(current)
        result = await planner.plan(current)
        self.assertEqual(current, original, "Raw history/context must not be rewritten")
        for key, value in previous_cache.items():
            self.assertEqual(planner._audio_cache[key], value, "Failed historical evidence was recertified")
        self.assertIn(len(exchanges), (3, 4), "Only the expected native requests may run; uncertainty can cancel MAIN")
        return result, planner

    async def test_exact_confirmation_after_failed_clip_is_existing_read_behavior(self):
        result, _ = await self.two_turn("I said Porto.", "I said Porto.")
        self.assertEqual(result["tool_calls"], [search()])
        self.assertEqual(result["observations"], [observation(1, "I said Porto.")])

    async def test_uncertain_or_failed_current_confirmation_still_blocks(self):
        for change in ({"uncertain": True}, {"fail_current": True}):
            with self.subTest(change=change):
                result, _ = await self.two_turn("I said Porto", "I said Porto.", **change)
                self.assertEqual(result["tool_calls"], [])
                self.assertTrue(result["clarification"])

    async def test_material_current_confirmation_words_still_block(self):
        for main, acoustic, name in (("I said Porto.", "I said Kyoto.", "Porto"),
                                     ("I said 42.", "I said 4.2.", "42"),
                                     ("I said St. Ives.", "I said St Ives.", "St Ives")):
            with self.subTest(main=main, acoustic=acoustic):
                proposal = {"slots": {"destination": name},
                            "tool_calls": [search(name)]}
                result, _ = await self.two_turn(main, acoustic, proposal=proposal)
                self.assertEqual(result["tool_calls"], [])
                self.assertTrue(result["clarification"])

    async def test_approved_current_period_equivalence_preserves_failed_history_and_raw_text(self):
        # Root explicitly approved this bounded read-domain assumption. The old
        # period-veto expectation and its baseline receipt remain archived.
        result, planner = await self.two_turn("I said Porto", "I said Porto.")
        self.assertEqual(result["tool_calls"], [search()])
        self.assertEqual(result["observations"], [observation(1, "I said Porto.")])
        self.assertEqual([row for row in planner._audio_cache.values() if row["message_index"] == 1],
                         [observation(1, "I said Porto.")])
        self.assertEqual(self.native_decisions[-1]["observations"], [observation(1, "I said Porto")])
        admitted = planner.evidence[-1]["audio_format_equivalence"]
        self.assertEqual(len(admitted), 1)
        self.assertEqual((admitted[0]["message_index"], admitted[0]["role"], admitted[0]["rules"]),
                         (1, "confirmation", ["terminal_period"]))
        self.assertEqual(admitted[0]["main_sha256"], hashlib.sha256(b"I said Porto").hexdigest())
        self.assertEqual(admitted[0]["acoustic_sha256"], hashlib.sha256(b"I said Porto.").hexdigest())

    async def test_exact_confirmation_with_uncertain_other_goal_exposes_baseline_limit(self):
        # This deliberately records the existing semantic goal-selection limit;
        # acceptance of this injected read is not a claim that it was appropriate.
        result, _ = await self.two_turn("I said Porto.", "I said Porto.",
            prior_main="Repeat my next utterance.", prior_acoustic="Repeat my next utterance.", prior_uncertain=True)
        self.assertEqual(result["tool_calls"], [search()])

    async def test_format_exception_cannot_cover_effects_extra_fields_or_wrong_entity(self):
        read = search()
        write = {"api_name": "book_flight", "args": {"flight_id": "OLD-ID", "passenger_name": "Asha"},
                 "authorization": {"quote": "Book a flight to Boston"}, "response_template": "Booking {booking_id}."}
        proposals = {
            "dependent_write": {"tool_calls": [{**read, "response_template": "", "after_result": write}]},
            "direct_write": {"tool_calls": [write]},
            "extra_read": {"tool_calls": [read, deepcopy(read)]},
            "read_authorization": {"tool_calls": [{**read, "authorization": {"quote": "I said Porto"}}]},
            "changed_destination": {"tool_calls": [{**read, "args": {"destination": "Kobe"}}]},
            "extra_argument": {"tool_calls": [{**read, "args": {"destination": "Porto", "date": "Friday"}}]},
            "changed_argument_case": {"tool_calls": [{**read, "args": {"destination": "porto"}}]},
        }
        for label, proposal in proposals.items():
            with self.subTest(proposal=label):
                result, _ = await self.two_turn("I said Porto", "I said Porto.", proposal=proposal)
                self.assertEqual(result["tool_calls"], [], "Formatting agreement exceeded the approved terminal read")
                self.assertTrue(result["clarification"])

    async def test_existing_slot_sync_precedes_the_comparison(self):
        # _decide already synchronizes duplicate slots with dispatch arguments.
        # This is a baseline behavior control, not a new formatting permission.
        result, planner = await self.two_turn("I said Porto.", "I said Porto.",
                                             proposal={"slots": {"destination": "porto"}})
        self.assertEqual(result["slots"], {"destination": "Porto"})
        self.assertEqual(result["tool_calls"], [search()])
        self.assertEqual(planner.evidence[-1].get("normalized_slots"), 1)
        self.assertNotIn("audio_format_equivalence", planner.evidence[-1])
        self.assertEqual(self.native_decisions[-1]["slots"], {"destination": "porto"})
        self.evidence = {"raw_main_slots": self.native_decisions[-1]["slots"],
                         "effective_slots": result["slots"], "call_args": result["tool_calls"][0]["args"],
                         "normalized_slots": planner.evidence[-1]["normalized_slots"],
                         "format_exception_used": False}

    async def test_exposed_literal_history_does_not_gain_a_format_exception(self):
        for prior in ("Repeat my next utterance.", "Use the exact identifier including punctuation."):
            with self.subTest(prior=prior):
                result, _ = await self.two_turn("I said Porto", "I said Porto.",
                    prior_main=prior, prior_acoustic=prior, prior_uncertain=True)
                self.assertEqual(result["tool_calls"], [])
                self.assertTrue(result["clarification"])

    async def test_filler_and_fresh_repair_formatting_remain_bounded(self):
        # Pure-helper edge checks complement the full two-turn planner tests.
        current = self.context(2)
        current.update(revision=1, current_turn_start=0)
        current["messages"][1]["revision"] = 1
        current["messages"][0]["payload"]["end_of_turn"] = False
        decision = {"intent": "search_flights", "slots": {"destination": "Porto"},
                    "tool_calls": [search()],
                    "observations": [observation(0, "Uh, book a flight to Nakuru."),
                                     observation(1, "Actually make that Porto.")],
                    "clarification": None, "response": None}
        heard = {0: observation(0, "Uh book a flight to Nakuru."), 1: deepcopy(decision["observations"][1])}
        variations = [
            ("same_filler_comma", {0}, None),
            ("later_period_difference", {0, 1}, lambda c, d, h: h[1].update(transcript="Actually make that Porto")),
            ("later_initial_case", {0, 1}, lambda c, d, h: h[1].update(transcript="actually make that Porto.")),
            ("later_discourse_comma", {0, 1}, lambda c, d, h: h[1].update(transcript="Actually, make that Porto.")),
            ("later_combined_format", {0, 1}, lambda c, d, h: h[1].update(transcript="actually, make that Porto")),
            ("first_request_filler_omitted", {0}, lambda c, d, h: h[0].update(transcript="Book a flight to Nakuru.")),
            ("filler_substituted", set(), lambda c, d, h: h[0].update(transcript="Um, book a flight to Nakuru.")),
            ("filler_repeated", set(), lambda c, d, h: h[0].update(transcript="Uh uh book a flight to Nakuru.")),
            ("unsupported_filler", set(), lambda c, d, h: h[0].update(transcript="Erm, book a flight to Nakuru.")),
            ("extra_word_omitted", set(), lambda c, d, h: h[0].update(transcript="Uh, please book a flight to Nakuru.")),
            ("later_repair_filler", set(), lambda c, d, h: h[1].update(transcript="Uh, actually make that Porto.")),
            ("fresh_confirmation_filler", set(), lambda c, d, h: (
                d["observations"][0].update(transcript="I said Nakuru."), h[0].update(transcript="Uh, I said Nakuru."))),
            ("entity_case_changed", set(), lambda c, d, h: h[0].update(transcript="Uh book a flight to nakuru.")),
            ("interior_space_changed", set(), lambda c, d, h: h[0].update(transcript="Uh book a flight to  Nakuru.")),
            ("main_uncertain", set(), lambda c, d, h: d["observations"][0].update(uncertain=True)),
            ("stale_revision", set(), lambda c, d, h: c["messages"][1].update(revision=2)),
            ("identifier_schema", set(), lambda c, d, h: c["tools"]["flight_search"]["args"]["destination"].update(
                description="Exact identifier including punctuation.")),
            ("raw_slot_mismatch_at_comparator", set(), lambda c, d, h: d["slots"].update(destination="porto")),
            ("repair_word_deleted", set(), lambda c, d, h: h[1].update(transcript="Make that Porto.")),
            ("repair_negated", set(), lambda c, d, h: h[1].update(transcript="Actually, do not make that Porto.")),
            ("repair_entity_changed", set(), lambda c, d, h: h[1].update(transcript="Actually, make that Kobe.")),
            ("repair_entity_case_changed", set(), lambda c, d, h: h[1].update(transcript="Actually, make that porto.")),
            ("repair_interior_case", set(), lambda c, d, h: h[1].update(transcript="Actually, Make that Porto.")),
            ("repair_non_ascii_prose", set(), lambda c, d, h: h[1].update(transcript="\u0391ctually, make that Porto.")),
            ("repair_misplaced_comma", set(), lambda c, d, h: h[1].update(transcript="Actually make, that Porto.")),
            ("repair_double_period", set(), lambda c, d, h: h[1].update(transcript="Actually, make that Porto..")),
            ("repair_main_uncertain", set(), lambda c, d, h: d["observations"][1].update(uncertain=True)),
            ("repair_acoustic_uncertain", set(), lambda c, d, h: h[1].update(uncertain=True)),
            ("repair_wrong_source", set(), lambda c, d, h: h[1].update(message_index=0)),
            ("wrong_final_argument", set(), lambda c, d, h: d["tool_calls"][0]["args"].update(destination="Nakuru")),
            ("repair_authorization", set(), lambda c, d, h: d["tool_calls"][0].update(authorization={"quote": "Book it"})),
            ("repair_after_result", set(), lambda c, d, h: d["tool_calls"][0].update(after_result={})),
            ("repair_direct_write", set(), lambda c, d, h: d["tool_calls"][0].update(api_name="book_flight")),
        ]
        for label, expected, mutate in variations:
            with self.subTest(boundary=label):
                c, d, h = deepcopy((current, decision, heard))
                if mutate:
                    mutate(c, d, h)
                original = deepcopy((c, d, h))
                admitted = planner_module._flight_read_audio_format_agreement(c, d, h)
                self.assertEqual(set(admitted), expected)
                self.assertEqual((c, d, h), original, "Comparison changed raw evidence or proposal")

    async def test_fresh_formatted_repairs_keep_exact_nfc_entities_and_raw_hashes(self):
        for name, main, acoustic, rules in (
            ("San José", "actually make that San Jose\u0301", "Actually, make that San José.",
             ["terminal_period", "discourse_comma", "initial_prose_case"]),
            ("Novi Sad", "make that Novi Sad", "Make that Novi Sad.", ["terminal_period", "initial_prose_case"]),
        ):
            with self.subTest(name=name):
                current = self.context(2)
                current.update(revision=1, current_turn_start=0)
                current["messages"][1]["revision"] = 1
                current["messages"][0]["payload"]["end_of_turn"] = False
                decision = {"slots": {"destination": name}, "tool_calls": [search(name)],
                            "observations": [observation(0, "Find flights to Sucre."), observation(1, main)]}
                heard = {0: deepcopy(decision["observations"][0]), 1: observation(1, acoustic)}
                original = deepcopy((current, decision, heard))
                admitted = planner_module._flight_read_audio_format_agreement(current, decision, heard)
                self.assertEqual(set(admitted), {1})
                self.assertEqual((admitted[1]["role"], admitted[1]["rules"]), ("repair", rules))
                self.assertEqual(admitted[1]["main_sha256"], hashlib.sha256(main.encode()).hexdigest())
                self.assertEqual(admitted[1]["acoustic_sha256"], hashlib.sha256(acoustic.encode()).hexdigest())
                self.assertEqual((current, decision, heard), original)

    async def test_inherited_uncertain_history_does_not_relax_later_repairs(self):
        current = self.context(3)
        current.update(revision=2, current_turn_start=1)
        current["messages"][1]["payload"]["end_of_turn"] = False
        current["messages"][2]["revision"] = 2
        current["observations"] = [observation(0, "An earlier unclear request.", True)]
        decision = {"slots": {"destination": "Sucre"}, "tool_calls": [search("Sucre")],
                    "observations": [observation(1, "I said Novi Sad"), observation(2, "Actually make that Sucre.")]}
        heard = {1: observation(1, "I said Novi Sad."), 2: deepcopy(decision["observations"][1])}
        for label, text, both in (("exact_repair", "Actually make that Sucre.", False),
                                  ("initial_case", "actually make that Sucre.", False),
                                  ("period", "Actually make that Sucre", False),
                                  ("comma", "Actually, make that Sucre.", False),
                                  ("identical_comma", "Actually, make that Sucre.", True)):
            with self.subTest(boundary=label):
                c, d, h = deepcopy((current, decision, heard))
                h[2]["transcript"] = text
                if both:
                    d["observations"][1]["transcript"] = text
                original = deepcopy((c, d, h))
                admitted = planner_module._flight_read_audio_format_agreement(c, d, h)
                self.assertEqual(set(admitted), {1} if label == "exact_repair" else set())
                self.assertEqual((c, d, h), original)

    async def test_first_request_filler_omission_has_separate_native_audit(self):
        pairs = (("Uh, book a flight to Osorno.", "Book a flight to Osorno", "Osorno"),
                 ("Um find flights to E\u0301vora.", "find flights to Évora.", "Évora"),
                 ("um, search flights to Puerto Varas", "Search flights to Puerto Varas.", "Puerto Varas"))
        for supplied, plain, name in pairs:
            for omitted_by in ("main", "acoustic"):
                with self.subTest(name=name, omitted_by=omitted_by):
                    main, acoustic = (plain, supplied) if omitted_by == "main" else (supplied, plain)
                    native, exchanges = {}, []
                    def handler(request):
                        body = json.loads(request.content)
                        listening = "perception only" in body["systemInstruction"]["parts"][0]["text"]
                        targets = [v["properties"]["message_index"]["enum"][0] for v in
                            body["generationConfig"]["responseJsonSchema"]["properties"]["observations"]["items"]["anyOf"]]
                        exchanges.append((listening, targets))
                        reply = {"observations": [observation(0, acoustic if listening else main)]}
                        if not listening:
                            reply.update(intent="search_flights", slots={"destination": name},
                                         tool_calls=[search(name)], clarification=None, response=None)
                        native[listening] = deepcopy(reply)
                        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
                            "content": {"parts": [{"text": json.dumps(reply)}]}}]})
                    planner = Planner(transport=httpx.MockTransport(handler))
                    self.addAsyncCleanup(planner.close)
                    await planner.setup()
                    current = self.context(1)
                    original = deepcopy(current)
                    result = await planner.plan(current)
                    self.assertEqual(result["tool_calls"], [search(name)])
                    self.assertEqual(result["slots"], {"destination": name})
                    self.assertEqual(result["observations"], [observation(0, acoustic)])
                    self.assertEqual(native[False]["observations"], [observation(0, main)])
                    self.assertEqual(native[True]["observations"], [observation(0, acoustic)])
                    self.assertEqual(current, original)
                    self.assertEqual(sorted(exchanges), [(False, [0]), (True, [0])])
                    audit = planner.evidence[-1]
                    self.assertNotIn("audio_transcript_conflicts", audit)
                    self.assertNotIn("audio_format_equivalence", audit)
                    self.assertNotIn("audio_confirmation_role_equivalence", audit)
                    admitted = audit["audio_filler_omission_equivalence"]
                    self.assertEqual(len(admitted), 1)
                    row = admitted[0]
                    self.assertEqual((row["message_index"], row["role"], row["basis"], row["rules"]),
                        (0, "request", "leading_discourse_filler_omission", ["leading_discourse_filler_omission"]))
                    self.assertEqual(row["omitted_by"], omitted_by)
                    self.assertEqual(row["omitted_prefix"], supplied.split(" ", 1)[0])
                    self.assertEqual(row["main_sha256"], hashlib.sha256(main.encode()).hexdigest())
                    self.assertEqual(row["acoustic_sha256"], hashlib.sha256(acoustic.encode()).hexdigest())
                    self.assertEqual(list(planner._audio_cache.values()), [observation(0, acoustic)])
                    await planner.close()
                    self.assertIsNone(planner.client)
                    self.assertFalse(planner._pending_tasks)

    async def test_inherited_request_or_confirmation_filler_omission_still_blocks(self):
        pairs = (("Book a flight to Porto.", "Uh, book a flight to Porto."),
                 ("Um, find flights to Porto.", "Find flights to Porto."),
                 ("I said Porto.", "Uh, I said Porto."),
                 ("Um, I said Porto.", "I said Porto."))
        for main, acoustic in pairs:
            with self.subTest(main=main, acoustic=acoustic):
                result, planner = await self.two_turn(main, acoustic)
                self.assertEqual(result["tool_calls"], [])
                self.assertTrue(result["clarification"])
                self.assertNotIn("audio_filler_omission_equivalence", planner.evidence[-1])


class AudioConfirmationRoleTests(unittest.IsolatedAsyncioTestCase):
    """Only the new bare-name role policy; do not collect the earlier broad suite."""
    asyncSetUp = AudioAgreementTests.asyncSetUp
    context = AudioAgreementTests.context
    two_turn = AudioAgreementTests.two_turn

    async def test_fresh_names_have_separate_role_evidence_and_preserve_native_text(self):
        for name in ("Udaipur", "Reykjavík", "Banda Aceh"):
            with self.subTest(name=name):
                # The last row retains the known pre-comparison slot sync control.
                raw_slot = "Elsewhere" if name == "Banda Aceh" else name
                result, planner = await self.two_turn(name, "I said " + name + ".", proposal={
                    "slots": {"destination": raw_slot}, "tool_calls": [search(name)]})
                self.assertEqual(result["tool_calls"], [search(name)])
                self.assertEqual(result["slots"], {"destination": name})
                self.assertEqual(self.native_decisions[-1]["slots"], {"destination": raw_slot})
                self.assertEqual(self.native_decisions[-1]["observations"], [observation(1, name)])
                self.assertEqual(result["observations"], [observation(1, "I said " + name + ".")])
                record = planner.evidence[-1]
                admitted = record["audio_confirmation_role_equivalence"]
                self.assertNotIn("audio_format_equivalence", record)
                self.assertNotIn("audio_transcript_conflicts", record)
                self.assertEqual(len(admitted), 1)
                self.assertEqual((admitted[0]["basis"], admitted[0]["role"], admitted[0]["rules"]),
                                 ("acoustic_confirmation_role", "confirmation", ["main_bare_destination"]))
                self.assertEqual(admitted[0]["main_sha256"], hashlib.sha256(name.encode()).hexdigest())
                self.assertEqual(admitted[0]["acoustic_sha256"], hashlib.sha256(("I said " + name + ".").encode()).hexdigest())
                if raw_slot != name:
                    self.assertEqual(record["normalized_slots"], 1)
                await planner.close()
                self.assertIsNone(planner.client)
                self.assertFalse(planner._pending_tasks)

    async def test_current_failure_uncertainty_or_changed_name_still_vetoes(self):
        for label, acoustic, change in (("failed", "I said Porto.", {"fail_current": True}),
                                       ("uncertain", "I said Porto.", {"uncertain": True}),
                                       ("changed_name", "I said Kigali.", {})):
            with self.subTest(boundary=label):
                result, planner = await self.two_turn("Porto", acoustic, **change)
                self.assertEqual(result["tool_calls"], [])
                self.assertTrue(result["clarification"])
                self.assertNotIn("audio_confirmation_role_equivalence", planner.evidence[-1])

    async def test_role_omission_retains_terminal_read_and_history_boundaries(self):
        current = self.context(2)
        current["observations"] = [observation(0, "An unclear earlier request.", True)]
        decision = {"intent": "search_flights", "slots": {"destination": "Udaipur"},
                    "tool_calls": [search("Udaipur")], "observations": [observation(1, "Udaipur")],
                    "clarification": None, "response": None}
        heard = {1: observation(1, "I said Udaipur.")}
        def fresh(c, d, h):
            c.update(self.context(1))
            d["observations"][0]["message_index"] = 0
            h[0] = h.pop(1)
            h[0]["message_index"] = 0
        def later_repair(c, d, h):
            c["messages"][1]["payload"]["end_of_turn"] = False
            c["messages"].append({**deepcopy(c["messages"][1]), "message_index": 2,
                                  "payload": {"audio_ref": "1.mp3", "end_of_turn": True}})
            d["observations"] = [observation(1, "Find flights to Merida."), observation(2, "Udaipur")]
            h.update({1: observation(1, "Find flights to Merida."), 2: observation(2, "Actually make that Udaipur.")})
        variants = [
            ("no_blocked_history", fresh),
            ("clear_prior_history", lambda c, d, h: c["observations"][0].update(uncertain=False)),
            ("quoted_history", lambda c, d, h: c["observations"][0].update(transcript="Read the quoted label.")),
            ("dictation_history", lambda c, d, h: c["observations"][0].update(transcript="Take dictation.")),
            ("main_period", lambda c, d, h: d["observations"][0].update(transcript="Udaipur.")),
            ("main_quoted", lambda c, d, h: d["observations"][0].update(transcript='"Udaipur"')),
            ("main_extra_words", lambda c, d, h: d["observations"][0].update(transcript="Udaipur and book it")),
            ("main_uncertain", lambda c, d, h: d["observations"][0].update(uncertain=True)),
            ("acoustic_bare", lambda c, d, h: h[1].update(transcript="Udaipur")),
            ("reverse_direction", lambda c, d, h: (d["observations"][0].update(transcript="I said Udaipur."), h[1].update(transcript="Udaipur"))),
            ("acoustic_extra_words", lambda c, d, h: h[1].update(transcript="I said Udaipur and book it.")),
            ("wrong_argument", lambda c, d, h: d["tool_calls"][0]["args"].update(destination="Kigali")),
            ("raw_slot_mismatch", lambda c, d, h: d["slots"].update(destination="Kigali")),
            ("extra_argument", lambda c, d, h: d["tool_calls"][0]["args"].update(date="Tuesday")),
            ("after_result", lambda c, d, h: d["tool_calls"][0].update(after_result={})),
            ("authorization", lambda c, d, h: d["tool_calls"][0].update(authorization={"quote": "Book it"})),
            ("write", lambda c, d, h: d["tool_calls"][0].update(api_name="book_flight")),
            ("extra_call", lambda c, d, h: d["tool_calls"].append(deepcopy(d["tool_calls"][0]))),
            ("later_repair", later_repair),
        ]
        for label, mutate in variants:
            with self.subTest(boundary=label):
                c, d, h = deepcopy((current, decision, heard))
                mutate(c, d, h)
                original = deepcopy((c, d, h))
                self.assertFalse(planner_module._flight_read_audio_format_agreement(c, d, h))
                self.assertEqual((c, d, h), original)

    async def test_unknown_prior_goal_remains_an_explicit_policy_limit(self):
        result, planner = await self.two_turn("Porto", "I said Porto.", prior_uncertain=True,
            prior_main="Is the weather mild today?", prior_acoustic="Is the weather mild today?")
        self.assertEqual(result["tool_calls"], [search()])
        self.assertTrue(any(o["uncertain"] for o in planner._audio_cache.values() if o["message_index"] == 0))
        self.evidence = {"generic_unrelated_uncertain_history_can_still_admit_injected_terminal_read": True,
                         "verified_inherited_goal": False, "write_authority": False,
                         "model_or_acoustic_understanding_claim": False}
