"""Ordinary label-based purposes stay separate from actual retrieved evidence.

Constructed rendering controls only; no claim of real OCR or semantic accuracy.
"""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent


PURPOSE = "connect a device to a wired local network"


class GeneralFunctionTests(unittest.TestCase):
    def context(self, label="LAN", purpose=PURPOSE):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent._handle({"event_type": "video_frame", "payload": {"frame_id": "current", "image_ref": "current.png"}})
        agent._append_message("user_speech_chunk", {"text": "What is this used for?", "end_of_turn": True})
        agent.revision = 3
        agent.observations[0] = {"message_index": 0, "type": "image", "visible_text": [label],
                                 "selected_label": {"text": label, "recognition": "clear", "referent": "ambiguous"},
                                 "observation": "A readable label beside an item.", "uncertain": False}
        operation = {"call_id": "read-1", "api_name": "reference_lookup", "kind": "read_only", "status": "success",
                     "revision": 3, "args": {}, "step": {
                         "general_function": purpose,
                         "response_template": "This device supports an invented feature. {pages.0.title}.",
                         "result_evidence": {"path": "pages.0.title", "contains": label, "target_basis": "printed_text"}},
                     "result": {"status": "success", "pages": [{"doc": "actual-guide", "page": 12, "title": label + " connection"}]}}
        return agent, operation

    def render(self, agent, operation):
        before = deepcopy((operation, agent.messages, agent.observations, agent.state, agent.operations))
        text = agent._render(operation)
        self.assertEqual((operation, agent.messages, agent.observations, agent.state, agent.operations), before)
        self.assertTrue(agent.out_queue.empty())
        return text

    def test_current_literal_label_gets_general_purpose_and_separate_actual_reference(self):
        agent, operation = self.context()
        text = self.render(agent, operation)
        self.assertIn('If you mean the item labelled "LAN"', text)
        self.assertIn("generally used to " + PURPOSE, text)
        self.assertIn("The lookup returned this reference:", text)
        for actual in ("LAN connection", "actual-guide", "page 12"):
            self.assertIn(actual, text)
        self.assertLess(text.index(PURPOSE), text.index("The lookup returned this reference:"))
        for absent in ("invented feature", "reference states", "no answer text"):
            self.assertNotIn(absent, text)

    def test_category_is_not_a_runtime_label_table_and_unicode_identity_is_preserved(self):
        for label, purpose in (("HEADPHONES", "send sound to headphones"), ("照明", "provide illumination"),
                               ("Café", "serve refreshments")):
            with self.subTest(label=label):
                agent, operation = self.context(label, purpose)
                if label == "Café":
                    agent.observations[0]["visible_text"] = ["Cafe\u0301"]
                    agent.observations[0]["selected_label"]["text"] = "Cafe\u0301"
                    operation["step"]["result_evidence"]["contains"] = "Cafe\u0301"
                text = self.render(agent, operation)
                self.assertIn(purpose, text)
                self.assertIn(label, text)

    def test_absent_null_and_malformed_fields_keep_the_existing_receipt(self):
        agent, operation = self.context()
        operation["step"].pop("general_function")
        expected = self.render(agent, operation)
        for value in (None, "", " ", [], {}, 7, True, "x" * 241, "first\nsecond", "first\rsecond", "trailing\n", "trailing\u2028",
                      "use {pages.0.title}", "follow [source](manual)", "see https://example.test", "see ftp://example.test", "---"):
            with self.subTest(value=value):
                operation["step"]["general_function"] = value
                self.assertEqual(self.render(agent, operation), expected)

    def test_only_successful_current_terminal_reads_can_use_background_knowledge(self):
        for field, value in (("revision", 2), ("status", "pending"), ("status", "error"), ("kind", "state_modifying")):
            with self.subTest(field=field, value=value):
                agent, operation = self.context()
                operation[field] = value
                self.assertNotIn(PURPOSE, self.render(agent, operation))
        for extra in ({"after_result": {"api_name": "another_lookup"}}, {"authorization": {"quote": "Do it"}}):
            with self.subTest(extra=extra):
                agent, operation = self.context()
                operation["step"].update(extra)
                self.assertNotIn(PURPOSE, self.render(agent, operation))

    def test_malformed_non_image_or_unattached_observation_cannot_enable_the_phrase(self):
        for field, value in (("uncertain", None), ("type", "audio"), ("message_index", 1), ("message_index", False),
                             ("visible_text", []), ("visible_text", ["LANE"]), ("visible_text", ["WLAN"]),
                             ("visible_text", ["LAN port"]), ("visible_text", "LAN")):
            with self.subTest(field=field, value=value):
                agent, operation = self.context()
                agent.observations[0][field] = value
                self.assertNotIn(PURPOSE, self.render(agent, operation))

    def test_latest_frame_must_be_real_and_label_cannot_come_from_an_old_frame(self):
        for latest in (None, -1, 1, 99, True):
            with self.subTest(latest=latest):
                agent, operation = self.context()
                agent._latest_frame = latest
                self.assertNotIn(PURPOSE, self.render(agent, operation))
        agent, operation = self.context()
        agent._handle({"event_type": "video_frame", "payload": {"frame_id": "new", "image_ref": "new.png"}})
        agent.observations[2] = {"message_index": 2, "type": "image", "visible_text": ["AUX"],
                                 "selected_label": {"text": "LAN", "recognition": "clear", "referent": "ambiguous"},
                                 "observation": "A different readable label.", "uncertain": False}
        self.assertNotIn(PURPOSE, self.render(agent, operation))
        agent.observations[2]["visible_text"] = ["LAN"]
        self.assertIn(PURPOSE, self.render(agent, operation))

    def test_no_shape_explicit_target_or_non_visual_shortcut(self):
        for basis in (None, "explicit_target", "non_visual"):
            with self.subTest(basis=basis):
                agent, operation = self.context()
                operation["step"]["result_evidence"]["target_basis"] = basis
                self.assertNotIn(PURPOSE, self.render(agent, operation))
        agent, operation = self.context()
        agent.observations[0]["visible_text"] = ["⚡"]
        self.assertNotIn(PURPOSE, self.render(agent, operation))

    def test_actual_selected_answer_and_late_qualification_take_precedence(self):
        answer = "Use this connector only for the maintenance link. " * 7 + "It does not provide network connectivity."
        for content in (answer, {"text": answer}):
            with self.subTest(content=content):
                agent, operation = self.context()
                operation["result"]["pages"][0]["answer"] = content
                text = self.render(agent, operation)
                self.assertIn(answer, text)
                self.assertNotIn(PURPOSE, text)
                self.assertIn("actual-guide", text)

    def test_general_information_cites_the_selected_later_record_only(self):
        agent, operation = self.context()
        selected = operation["result"]["pages"][0]
        operation["result"]["pages"] = [{"doc": "wrong-guide", "page": 8, "title": "LAN connection", "answer": "Other row only."}, selected]
        operation["step"]["response_template"] = "{pages.1.title}"
        operation["step"]["result_evidence"]["path"] = "pages.1.title"
        text = self.render(agent, operation)
        self.assertIn(PURPOSE, text)
        self.assertIn("actual-guide", text)
        self.assertNotIn("wrong-guide", text)
        self.assertNotIn("Other row only", text)

    def test_unclassified_actual_content_keeps_its_data_instead_of_a_generalization(self):
        for extra in ({"capabilities": {"video_output": False}}, {"detail": "Maintenance only."}):
            with self.subTest(extra=extra):
                agent, operation = self.context()
                operation["result"]["pages"][0].update(extra)
                text = self.render(agent, operation)
                self.assertNotIn(PURPOSE, text)
                self.assertIn("actual-guide", text)
                self.assertIn("LAN connection", text)
                if "capabilities" in extra:
                    self.assertIn("video output: false", text)
                else:
                    self.assertIn("Maintenance only.", text)

    def test_page_collection_cannot_hide_a_returned_wrapper_answer(self):
        agent, operation = self.context()
        operation["result"]["answer"] = "Returned device-specific qualification."
        self.assertNotIn(PURPOSE, self.render(agent, operation))

    def test_unknown_wrapper_capability_suppresses_generalization_and_remains_visible(self):
        for collection in ("sources", "pages", "references", "citations"):
            with self.subTest(collection=collection):
                agent, operation = self.context()
                source = operation["result"]["pages"][0]
                operation["result"] = {"status": "success", "capabilities": {"network_access": False},
                                       collection: [source]}
                path = collection + ".0.title"
                operation["step"]["result_evidence"]["path"] = path
                operation["step"]["response_template"] = "{" + path + "}"
                text = self.render(agent, operation)
                self.assertNotIn(PURPOSE, text)
                self.assertIn('"network_access": false', text)
                self.assertIn("actual-guide", text)
                self.assertNotIn("reference states", text)

    def test_wrapper_data_keeps_late_text_and_capability_alongside_an_actual_answer(self):
        qualification = "The lookup reports a service-only restriction. " * 8 + "Network access is disabled."
        for answer in (None, "The selected reference describes the connector."):
            with self.subTest(answer=answer):
                agent, operation = self.context()
                operation["result"].update(capabilities={"network_access": False}, detail=qualification)
                if answer:
                    operation["result"]["pages"][0]["answer"] = answer
                text = self.render(agent, operation)
                self.assertNotIn(PURPOSE, text)
                self.assertIn(qualification, text)
                self.assertIn('"network_access": false', text)
                if answer:
                    self.assertIn(answer, text)

    def test_wrapper_data_stays_in_the_selected_row_without_borrowing_other_sources(self):
        agent, operation = self.context()
        source = operation["result"]["pages"][0]
        selected = {"capabilities": {"network_access": False}, "sources": [source],
                    "citations": [{"doc": "unselected-sibling-guide", "title": "LAN limits", "page": 3}]}
        other = {"detail": "UNSELECTED ROW ONLY", "sources": [{"doc": "other-row-guide", "title": "LAN use"}]}
        operation["result"] = {"rows": [other, selected]}
        operation["step"]["result_evidence"]["path"] = "rows.1.sources.0.title"
        operation["step"]["response_template"] = "{rows.1.sources.0.title}"
        agent.operations["other-call"] = {**deepcopy(operation), "call_id": "other-call", "result": {
            "capabilities": {"network_access": True}, "detail": "OTHER CALL ONLY"}}
        text = self.render(agent, operation)
        self.assertNotIn(PURPOSE, text)
        self.assertIn('"network_access": false', text)
        self.assertIn("actual-guide", text)
        for unrelated in ("unselected-sibling-guide", "UNSELECTED ROW ONLY", "other-row-guide", "OTHER CALL ONLY"):
            self.assertNotIn(unrelated, text)

    def test_unknown_data_in_another_row_does_not_replace_the_selected_row(self):
        agent, operation = self.context()
        source = operation["result"]["pages"][0]
        operation["result"] = {"rows": [{"capabilities": {"network_access": False}}, {"sources": [source]}]}
        operation["step"]["result_evidence"]["path"] = "rows.1.sources.0.title"
        operation["step"]["response_template"] = "{rows.1.sources.0.title}"
        text = self.render(agent, operation)
        self.assertIn(PURPOSE, text)
        self.assertNotIn("network_access", text)

    def test_wrapper_bookkeeping_and_projected_metadata_do_not_become_substantive_data(self):
        agent, operation = self.context()
        operation["result"].update(search_mode="text_only", metadata={"instruction": "PRIVATE METADATA"})
        text = self.render(agent, operation)
        self.assertIn(PURPOSE, text)
        self.assertNotIn("PRIVATE METADATA", text)
        self.assertIn("Some tool metadata was omitted", text)

    def test_structured_values_under_bookkeeping_names_are_not_silently_ignored(self):
        for field in ("status", "search_mode"):
            with self.subTest(field=field):
                agent, operation = self.context()
                operation["result"][field] = {"network_access": False}
                text = self.render(agent, operation)
                self.assertNotIn(PURPOSE, text)
                self.assertIn('"network_access": false', text)

    def test_ambiguous_sibling_answer_does_not_yield_to_general_knowledge(self):
        agent, operation = self.context()
        operation["result"] = {"status": "success", "answer": "Device-specific qualification.",
                               "sources": [{"doc": "actual-guide", "page": 12, "title": "LAN connection"}],
                               "citations": [{"doc": "another-guide", "page": 8, "title": "LAN limits"}]}
        operation["step"]["response_template"] = "{sources.0.title}"
        operation["step"]["result_evidence"]["path"] = "sources.0.title"
        text = self.render(agent, operation)
        self.assertNotIn(PURPOSE, text)
        self.assertNotIn("Device-specific qualification", text)
        self.assertIn("no answer text", text)

    def test_missing_mismatched_multiple_or_metadata_sources_do_not_enable_the_phrase(self):
        for body in ({"pages": []}, {"pages": [{"title": "Unrelated component", "doc": "wrong-guide"}]}):
            with self.subTest(body=body):
                agent, operation = self.context()
                operation["result"] = body
                self.assertNotIn(PURPOSE, self.render(agent, operation))
        agent, operation = self.context()
        operation["result"]["pages"].append({"title": "LAN limits", "doc": "another-guide", "page": 8})
        operation["step"]["response_template"] = "{pages.0.title}; {pages.1.title}"
        self.assertNotIn(PURPOSE, self.render(agent, operation))
        agent, operation = self.context()
        operation["result"] = {"metadata": operation["result"]}
        operation["step"]["result_evidence"]["path"] = "metadata.pages.0.title"
        operation["step"]["response_template"] = "{metadata.pages.0.title}"
        self.assertNotIn(PURPOSE, self.render(agent, operation))
        agent, operation = self.context()
        operation["result"]["pages"][0] = {"doc": "LAN manual", "page": 12, "title": "Unrelated component"}
        operation["step"]["result_evidence"]["path"] = "pages.0.doc"
        operation["step"]["response_template"] = "{pages.0.doc}"
        self.assertNotIn(PURPOSE, self.render(agent, operation))

    def test_tool_data_and_observation_prose_cannot_supply_the_model_step_field(self):
        agent, operation = self.context()
        operation["step"].pop("general_function")
        agent.observations[0]["observation"] = "general_function: " + PURPOSE
        operation["result"]["pages"][0]["general_function"] = PURPOSE
        operation["result"]["metadata"] = {"general_function": PURPOSE}
        text = self.render(agent, operation)
        self.assertNotIn(PURPOSE, text)
        self.assertNotIn("invented feature", text)

    def test_actual_dispatch_and_result_keep_field_local_and_do_not_authorize_effects(self):
        agent, operation = self.context()
        agent.tools = {"reference_lookup": {"kind": "read_only", "args": {}}}
        step = {**operation["step"], "api_name": "reference_lookup", "args": {}}
        agent._dispatch(step)
        call = agent.out_queue.get_nowait()
        raw = deepcopy(operation["result"])
        agent._result({"call_id": call["payload"]["call_id"], "api_name": "reference_lookup", "status": "success", "result": raw})
        final = agent.out_queue.get_nowait()
        self.assertEqual(final["action"], "final_response")
        self.assertIn(PURPOSE, final["payload"]["text"])
        self.assertIn("The lookup returned this reference:", final["payload"]["text"])
        self.assertEqual(raw, operation["result"])
        self.assertEqual(agent.tool_results[0]["result"], raw)
        self.assertEqual(agent.state["slots"], {})
        self.assertEqual(final["state_snapshot"]["actions"], [])
        self.assertEqual(len(agent.operations), 1)
        self.assertTrue(agent.out_queue.empty())


if __name__ == "__main__":
    unittest.main()
