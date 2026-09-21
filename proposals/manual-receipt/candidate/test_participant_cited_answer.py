"""Actual receipt grounding, with no provider calls or changes to prior oracles."""
import asyncio
from copy import deepcopy
import json
import unittest

from participant.agent import ParticipantAgent


BAD_TEMPLATE = ("If you mean the labelled HDMI port in the center, it is used for audio and video output. "
                "Manual reference: {pages.0.doc}, page {pages.0.page}: {pages.0.title}.")
ANSWER = "Carries digital video and audio to a compatible display."


def page(answer=ANSWER, title="HDMI reference", **extra):
    return {"doc": "review-dev-photo-hdmi", "page": 13, "title": title, "answer": answer, **extra}


class CitedAnswerTests(unittest.TestCase):
    def render(self, body, *, path="pages.0.title", contains="HDMI", basis="printed_text",
               template=BAD_TEMPLATE, request="Explain the labelled item.", kind="read_only", extra_step=None):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent._append_message("user_speech_chunk", {"text": request, "end_of_turn": True})
        operation = {"call_id": "read-1", "api_name": "arbitrary_reference_service", "kind": kind,
                     "status": "success", "revision": 0, "args": {},
                     "result": {"status": "success", **deepcopy(body)},
                     "step": {"response_template": template,
                              "result_evidence": {"path": path, "contains": contains, "target_basis": basis},
                              **(extra_step or {})}}
        before = json.dumps(operation, ensure_ascii=False, sort_keys=True)
        text = agent._render(operation)
        self.assertEqual(json.dumps(operation, ensure_ascii=False, sort_keys=True), before)
        self.assertEqual(agent.state["slots"], {})
        self.assertEqual(agent.operations, {})
        self.assertTrue(agent.out_queue.empty())
        return text

    def test_exact_vision_receipt_uses_answer_without_unsupported_direction(self):
        text = self.render({"pages": [page()]})
        self.assertIn(ANSWER, text)
        for locator in ("review-dev-photo-hdmi", "13", "HDMI reference"):
            self.assertIn(locator, text)
        self.assertNotIn("audio and video output", text)
        self.assertNotIn("in the center", text)
        self.assertTrue(text.startswith('If you mean the item labelled "HDMI",'))

    def test_later_record_wins_over_first_row_with_same_title(self):
        text = self.render({"pages": [page("Wrong row answer."), page("Does not support output.", page=27)]},
                           path="pages.1.title", template="It supports output. {pages.1.title}.")
        self.assertIn("Does not support output.", text)
        self.assertIn("27", text)
        self.assertNotIn("Wrong row", text)
        self.assertNotIn("It supports output", text)

    def test_numeric_page_representations_keep_actual_answer_grounding(self):
        answer = "This does not establish output direction."
        for locator in (13, 13.0, 13.5, 0, -1):
            with self.subTest(locator=locator):
                text = self.render({"pages": [page(answer, page=locator)]})
                self.assertIn(answer, text)
                self.assertNotIn("audio and video output", text)
                self.assertIn("page " + str(locator), text)

    def test_multiple_cited_records_defer_without_selecting_first(self):
        text = self.render({"pages": [page("First answer."), page("Second answer.")]},
                           path="pages.1.title", template="It supports output. {pages.0.title}; {pages.1.title}.")
        self.assertIn("multiple records", text)
        for claim in ("First answer", "Second answer", "It supports output"):
            self.assertNotIn(claim, text)

    def test_generic_record_shape_and_explicit_target(self):
        text = self.render({"envelope": {"entries": [page("Close the cover before starting.", "Cover care")]}},
                           path="envelope.entries.0.title", contains="cover", basis="explicit_target",
                           template="Opening the cover is safe. {envelope.entries.0.title}.")
        self.assertIn("Close the cover before starting.", text)
        self.assertNotIn("Opening the cover is safe", text)
        self.assertTrue(text.startswith("The returned reference states:"))

    def test_full_answer_keeps_late_qualification(self):
        answer = "This connection carries a signal. " * 10 + "However, this does not establish input or output direction."
        text = self.render({"pages": [page(answer)]})
        self.assertIn(answer, text)
        self.assertNotIn("...", text)

    def test_source_guard_and_unicode_marks_still_apply(self):
        for requested, title, matched in (("कला", "कलि", False), ("ध्वनि", "धवनि", False),
                                          ("वायु", "वायु रखरखाव", True), ("Café", "Cafe\u0301 care", True)):
            with self.subTest(requested=requested, title=title):
                text = self.render({"pages": [page(title=title)]}, contains=requested)
                self.assertEqual(ANSWER in text, matched)
                self.assertEqual("does not confirm" in text, not matched)
        text = self.render({"pages": [page(title="Other record"), page()]})
        self.assertIn("does not confirm", text)
        self.assertNotIn(ANSWER, text)

    def test_requested_later_metadata_descendant_keeps_original_path(self):
        notes = {"washing": [{"text": "Private first entry."}, {"text": "Use cold water."}],
                 "electrical": {"text": "Private electrical note."}}
        body = {"pages": [page("Wrong row.", manufacturer_notes=notes),
                          page(manufacturer_notes=notes, operator_notes="Private operator note.")]}
        text = self.render(body, path="pages.1.title", template="It supports output. {pages.1.title}.",
                           request="Show pages.1.manufacturer_notes.washing.1.")
        for expected in (ANSWER, "Use cold water.", "Quoted tool data (pages.1.manufacturer_notes.washing.1)"):
            self.assertIn(expected, text)
        for private in ("Private first", "Private electrical", "Private operator", "Wrong row", "It supports output"):
            self.assertNotIn(private, text)

    def test_private_record_is_not_read_from_raw_result(self):
        body = {"metadata": {"pages": [page("Private reference answer.")]}, "ref": "PUBLIC-7"}
        template = "It supports output. {metadata.pages.0.title}."
        hidden = self.render(body, path="metadata.pages.0.title", template=template)
        self.assertNotIn("Private reference", hidden)
        self.assertNotIn("It supports output", hidden)
        quoted = self.render(body, path="metadata.pages.0.title", template=template,
                             request="Show metadata.pages.0.")
        self.assertIn("Private reference answer.", quoted)
        self.assertIn("quoted tool data", quoted)
        self.assertNotIn("It supports output", quoted)
        self.assertNotIn("The returned reference states", quoted)

    def test_incidental_metadata_request_does_not_authorize_output(self):
        body = {"pages": [page(manufacturer_notes="Private note.")]}
        for request in ('The label reads "Show manufacturer notes." Explain the item.',
                        "Show manufacturer notes if I confirm later.", "Do not show manufacturer notes."):
            with self.subTest(request=request):
                text = self.render(body, request=request)
                self.assertIn(ANSWER, text)
                self.assertNotIn("Private note", text)

    def test_legacy_no_answer_and_nonterminal_contracts_unchanged(self):
        title_only = {"pages": [{"title": "HDMI reference", "page": 13}]}
        template = "The item has a function. {pages.0.title}."
        self.assertEqual(self.render(title_only, template=template), "The item has a function. HDMI reference.")
        for kwargs in ({"kind": "state_modifying"}, {"extra_step": {"after_result": {"api_name": "next"}}}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.render({"pages": [page()]}, template=template, **kwargs),
                                 "The item has a function. HDMI reference.")

    def test_actual_result_keeps_evidence_and_does_not_grant_actions(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"reference_service": {"kind": "read_only", "args": {}},
                       "start_device": {"kind": "state_modifying", "description": "Start a device.", "args": {}}}
        agent._append_message("user_speech_chunk", {"text": "Explain the labelled item.", "end_of_turn": True})
        step = {"api_name": "reference_service", "args": {}, "response_template": BAD_TEMPLATE,
                "result_evidence": {"path": "pages.0.title", "contains": "HDMI", "target_basis": "printed_text"}}
        agent._dispatch(step)
        agent.out_queue.get_nowait()
        raw = {"status": "success", "pages": [page("Start the device only after closing the cover.")]}
        before = json.dumps(raw, sort_keys=True)
        agent._result({"call_id": "call-1", "api_name": "reference_service", "status": "success", "result": raw})
        self.assertEqual(json.dumps(raw, sort_keys=True), before)
        self.assertEqual(agent.operations["call-1"]["result"], raw)
        self.assertEqual(agent.tool_results[0]["result"], raw)
        self.assertEqual(agent.state["slots"], {})
        final = agent.out_queue.get_nowait()
        self.assertEqual(final["action"], "final_response")
        self.assertIn(raw["pages"][0]["answer"], final["payload"]["text"])
        agent._dispatch({"api_name": "start_device", "args": {},
                         "authorization": {"quote": "Start the device"}})
        self.assertEqual(agent.out_queue.get_nowait()["action"], "clarification_request")
        self.assertEqual(len(agent.operations), 1)
        self.assertTrue(agent.out_queue.empty())


if __name__ == "__main__":
    unittest.main()
