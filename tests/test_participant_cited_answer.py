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

    def test_title_only_cannot_support_template_explanation(self):
        title_only = {"pages": [{"title": "HDMI reference", "page": 13}]}
        template = "The item has a function. {pages.0.title}."
        text = self.render(title_only, template=template)
        self.assertIn("no answer text", text)
        self.assertIn("HDMI reference", text)
        self.assertIn("page 13", text)
        self.assertNotIn("The item has a function", text)

    def test_write_receipts_remain_unchanged_and_continuation_fallback_is_grounded(self):
        template = "The item has a function. {pages.0.title}."
        self.assertEqual(self.render({"pages": [page(page="appendix")]}, template=template, kind="state_modifying"),
                         "The item has a function. HDMI reference.")
        # A numeric receipt now requires a fully field-bound template. Keep the
        # actual successful write and source content instead of free template prose.
        numeric = self.render({"pages": [page()]}, template=template, kind="state_modifying")
        self.assertTrue(numeric.startswith("Done."))
        self.assertIn("page: 13", numeric)
        self.assertIn(ANSWER, numeric)
        self.assertNotIn("The item has a function", numeric)
        text = self.render({"pages": [page()]}, template=template,
                           extra_step={"after_result": {"api_name": "next"}})
        self.assertIn(ANSWER, text)
        self.assertNotIn("The item has a function", text)

    def test_missing_evidence_object_does_not_enable_title_only_claim(self):
        for template in ("Invented capability. {pages.0.title}.",
                         "Invented capability. {pages.0.doc}, page {pages.0.page}."):
            with self.subTest(template=template):
                text = self.render({"pages": [{"doc": "guide-92", "page": 6, "title": "Sensor care"}]},
                                   template=template, extra_step={"result_evidence": None})
                self.assertIn("no answer text", text)
                self.assertIn("guide-92", text)
                self.assertNotIn("Invented capability", text)

    def test_nested_answer_preserves_full_text_and_citation(self):
        answer = "Always isolate the inlet. " * 12 + "Do not energize until the guard is secured."
        for wrapped in (answer, {"text": answer}, {"content": {"paragraphs": [answer]}}, [answer]):
            with self.subTest(wrapped=wrapped):
                text = self.render({"envelope": {"records": [page(answer=wrapped, title="Inlet care")]}},
                                   path="envelope.records.0.title", contains="Inlet",
                                   template="Open while running. {envelope.records.0.title}.")
                self.assertIn(answer, text)
                self.assertIn("page 13", text)
                self.assertIn("Inlet care", text)
                self.assertNotIn("Open while running", text)

    def test_single_sibling_source_binds_wrapped_answer(self):
        for source_field in ("sources", "references", "citations"):
            with self.subTest(source_field=source_field):
                text = self.render({"payload": {"answer": {"text": ANSWER}, source_field: [
                    {"doc": "guide-current", "page": 42, "title": "HDMI care"}]}},
                    path=f"payload.{source_field}.0.title", template=f"Invented. {{payload.{source_field}.0.title}}.")
                self.assertIn(ANSWER, text)
                self.assertIn("guide-current", text)
                self.assertIn("page 42", text)
                self.assertNotIn("Invented", text)

    def test_answer_only_template_keeps_the_result_citation(self):
        for template in ("{answer}", "Invented capability. {answer.text}"):
            with self.subTest(template=template):
                text = self.render({"answer": {"text": ANSWER}, "sources": [
                    {"doc": "actual-guide", "page": 17, "title": "Connection care"}]},
                    template=template, extra_step={"result_evidence": None})
                self.assertIn(ANSWER, text)
                self.assertIn("actual-guide", text)
                self.assertIn("17", text)
                self.assertNotIn("Invented capability", text)

    def test_answer_only_template_preserves_selected_row_and_its_sources(self):
        rows = [
            {"answer": "FIRST ROW ONLY.", "sources": [{"doc": "guide-A", "page": 2, "title": "First component"}]},
            {"answer": "SECOND ROW REQUESTED.", "sources": [{"doc": "guide-B", "page": 3, "title": "Second component"}]}]
        for collection in ("results", "pages"):
            for index in (0, 1):
                with self.subTest(collection=collection, index=index):
                    text = self.render({collection: rows}, template=f"Unsupported claim. {{{collection}.{index}.answer}}",
                                       extra_step={"result_evidence": None})
                    selected, other = rows[index], rows[1 - index]
                    self.assertIn(selected["answer"], text)
                    self.assertIn(selected["sources"][0]["doc"], text)
                    self.assertIn(selected["sources"][0]["title"], text)
                    self.assertNotIn(other["answer"], text)
                    self.assertNotIn(other["sources"][0]["doc"], text)
                    self.assertNotIn("Unsupported claim", text)

    def test_nested_selected_answer_keeps_qualifications_and_scoped_quoted_data(self):
        qualification = "Wait until the rotor stops. " * 12 + "Never bypass the interlock."
        selected = {"body": {"answer": {"text": "Selected answer.", "qualification": qualification}},
                    "citations": [{"doc": "selected-guide", "page": 19, "title": "Guard care"}],
                    "manufacturer_notes": {"care": "Use cold water.", "other": "Private sibling."}}
        body = {"envelope": {"results": [{"answer": "Unselected answer.", "sources": [
            {"doc": "wrong-guide", "page": 7, "title": "Wrong component"}]}, selected]}}
        for request in ("Explain the item.", "Show envelope.results.1.manufacturer_notes.care."):
            with self.subTest(request=request):
                text = self.render(body, template="Unsupported claim. {envelope.results.1.body.answer.text}",
                                   request=request, extra_step={"result_evidence": None})
                for value in ("Selected answer.", qualification, "selected-guide", "Guard care"):
                    self.assertIn(value, text)
                for value in ("Unselected answer", "wrong-guide", "Private sibling", "Unsupported claim"):
                    self.assertNotIn(value, text)
                if request.startswith("Show"):
                    self.assertIn("Use cold water.", text)
                    self.assertIn("quoted tool data", text)
                else:
                    self.assertNotIn("Use cold water.", text)

    def test_static_or_status_only_template_cannot_bypass_returned_sources(self):
        for template in ("Invented capability.", "Invented capability. {status}.",
                         "Invented capability. {search_mode}."):
            with self.subTest(template=template):
                text = self.render({"pages": [page()], "search_mode": "text_only"},
                                   template=template, extra_step={"result_evidence": None})
                self.assertIn(ANSWER, text)
                self.assertIn("HDMI reference", text)
                self.assertNotIn("Invented capability", text)

    def test_fallback_keeps_wrapped_answer_qualifications_and_source(self):
        answer = "Allow the rotor to stop. " * 12 + "Never bypass the interlock."
        for body in ({"answer": answer, "sources": [{"doc": "guard-guide", "page": 5}]},
                     {"envelope": {"answer": {"text": answer}, "sources": [{"doc": "guard-guide", "page": 5}]}},
                     {"data": {"answer": {"steps": [{"text": answer}, {"text": "Keep the guard closed."}]},
                               "sources": [{"doc": "guard-guide", "page": 5}]}}):
            with self.subTest(body=body):
                text = self.render(body, template=None, extra_step={"result_evidence": None})
                self.assertIn(answer, text)
                self.assertIn("guard-guide", text)
                if "data" in body:
                    self.assertIn("Keep the guard closed.", text)

    def test_actual_title_wording_is_retained_as_a_reference(self):
        text = self.render({"pages": [{"doc": "signal-guide", "page": 44, "title": "HDMI Output"}]})
        self.assertIn("HDMI Output", text)
        self.assertIn("signal-guide", text)
        self.assertIn("44", text)
        self.assertIn("no answer text", text)
        self.assertNotIn("audio and video output", text)

    def test_wrapped_record_answer_and_unrelated_archived_answer_stay_separate(self):
        text = self.render({"pages": [{"doc": "current-guide", "page": 35, "title": "HDMI care",
                                      "payload": {"answer": ANSWER}, "archived": {"answer": "Outdated answer."}}]})
        self.assertIn(ANSWER, text)
        self.assertNotIn("Outdated answer", text)

    def test_answer_is_not_borrowed_from_a_sibling_record(self):
        text = self.render({"pages": [page("Wrong row answer."), {"title": "HDMI care", "page": 22}]},
                           path="pages.1.title", template="Invented. {pages.1.title}.")
        self.assertIn("no answer text", text)
        self.assertNotIn("Wrong row", text)
        self.assertNotIn("Invented", text)

    def test_ambiguous_sibling_sources_do_not_bind_an_unselected_answer(self):
        first = {"title": "Guard care", "doc": "guide-one", "page": 2}
        selected = {"title": "Guard care", "doc": "guide-two", "page": 3}
        cases = [("sources.1.title", {"sources": [first, selected]})]
        for field in ("sources", "references", "citations"):
            for other in ("sources", "references", "citations", "pages"):
                if field != other:
                    cases.append((field + ".0.title", {field: [selected], other: [first]}))
        for path, sources in cases:
            with self.subTest(path=path, sources=sources):
                text = self.render({"answer": "Unassociated answer.", **sources}, path=path, contains="Guard",
                                   template="Invented. {" + path + "}.")
                self.assertIn("no answer text", text)
                self.assertIn("guide-two", text)
                self.assertNotIn("Unassociated answer", text)
                self.assertNotIn("guide-one", text)

    def test_empty_sibling_source_containers_do_not_block_unique_association(self):
        text = self.render({"answer": ANSWER, "sources": [
            {"title": "HDMI care", "doc": "only-guide", "page": 2}],
            "references": [], "citations": [], "pages": []},
            path="sources.0.title", template="Invented. {sources.0.title}.")
        self.assertIn(ANSWER, text)
        self.assertIn("only-guide", text)
        self.assertNotIn("Invented", text)

    def test_unrelated_nested_answers_are_not_blended_into_selected_record(self):
        text = self.render({"pages": [page("Current answer.", archived={"answer": "Outdated answer."})]})
        self.assertIn("Current answer.", text)
        self.assertNotIn("Outdated answer", text)

    def test_wrapped_primary_answer_does_not_lose_numeric_values(self):
        text = self.render({"pages": [page(answer={"text": "Maximum setting", "value": 37, "unit": "Hz"})]})
        self.assertIn("Maximum setting", text)
        self.assertIn("37", text)
        self.assertIn("Hz", text)

    def test_structured_answer_keeps_relationships_and_labels(self):
        text = self.render({"pages": [page(answer={"allowed": {"mode": "standby"},
                                                   "prohibited": {"mode": "active"}})]})
        self.assertIn("allowed: {mode: standby}", text)
        self.assertIn("prohibited: {mode: active}", text)
        self.assertIn("page 13", text)

    def test_unicode_source_paths_preserve_answer_and_same_citation(self):
        text = self.render({"résultats": [{"doc": "手引き", "page": "四", "title": "風量", "answer": "動作中は開けない。"}]},
                           path="résultats.0.title", contains="風量", template="Unsupported. {résultats.0.title}.")
        for value in ("動作中は開けない。", "手引き", "四", "風量"):
            self.assertIn(value, text)
        self.assertNotIn("Unsupported", text)

    def test_old_success_does_not_supply_missing_current_answer(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.revision = 5
        agent.operations["old"] = {"call_id": "old", "api_name": "reference_service", "kind": "read_only",
            "revision": 4, "status": "success", "args": {}, "step": {},
            "result": {"pages": [page("Old unsupported capability.")]}}
        current = {"call_id": "now", "api_name": "reference_service", "kind": "read_only",
            "revision": 5, "status": "success", "args": {},
            "step": {"response_template": BAD_TEMPLATE,
                     "result_evidence": {"path": "pages.0.title", "contains": "HDMI"}},
            "result": {"pages": [{"doc": "current-guide", "page": 35, "title": "HDMI care"}]}}
        before = deepcopy(agent.operations)
        text = agent._render(current)
        self.assertIn("no answer text", text)
        self.assertIn("current-guide", text)
        self.assertNotIn("Old unsupported capability", text)
        self.assertNotIn("audio and video output", text)
        self.assertEqual(agent.operations, before)

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
