"""Authored field-association controls; no benchmark inputs, labels, or models.

These test actual rendered statements, source immutability, and the controller's
successful/error receipt path. Matching a number elsewhere in a result is never
accepted as evidence for its role in a sentence.
"""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent
from participant.presentation import quantitative_template_is_bound


class QuantitativeGroundingTests(unittest.TestCase):
    def render(self, body, template, *, status="success", kind="read_only"):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"inspect_inventory": {"kind": kind, "args": {}}}
        agent._append_message("user_speech_chunk", {"text": "Report the current reading.", "end_of_turn": True})
        operation = {"call_id": "reading-1", "api_name": "inspect_inventory", "kind": kind,
                     "status": status, "revision": agent.revision, "args": {},
                     "result": {"status": status, **deepcopy(body)},
                     "step": {"response_template": template}}
        before = deepcopy(operation)
        text = agent._render(operation)
        self.assertEqual(operation, before)
        self.assertEqual(agent.operations, {})
        self.assertEqual(agent.state["slots"], {})
        self.assertTrue(agent.out_queue.empty())
        return text

    def test_ratio_cannot_be_presented_as_a_total(self):
        body = {"output_mass": 248.0, "yield_ratio": 0.62}
        text = self.render(body, "The batch yields {yield_ratio} kilograms.")
        self.assertNotIn("batch yields", text)
        self.assertIn("output mass: 248.0", text)
        self.assertIn("yield ratio: 0.62", text)

    def test_swapped_sibling_quantities_keep_their_actual_roles(self):
        body = {"remaining_stock": 23, "reorder_limit": 7}
        text = self.render(body, "Remaining stock: {reorder_limit}; reorder limit: {remaining_stock}.")
        self.assertNotIn("Remaining stock: 7", text)
        self.assertIn("remaining stock: 23", text)
        self.assertIn("reorder limit: 7", text)

    def test_field_binding_does_not_depend_on_inequality(self):
        body = {"remaining_stock": 7, "reorder_limit": 7}
        text = self.render(body, "Remaining stock: {reorder_limit}.")
        self.assertIn("reorder limit: 7", text)
        self.assertTrue(text.startswith("Here is what I found:"))

    def test_labeled_quantities_preserve_natural_templates(self):
        for key, label in (("remaining_stock", "Remaining stock"),
                           ("remaining_stock", "Remaining-stock"),
                           ("remainingStock", "Remaining stock"),
                           ("残量", "残量")):
            with self.subTest(key=key):
                text = self.render({key: 23, "reorder_limit": 7},
                                   f"The {label} is {{{key}}}; reorder limit: {{reorder_limit}}.")
                self.assertEqual(text, f"The {label} is 23; reorder limit: 7.")

    def test_numeric_strings_and_booleans_use_the_same_boundary(self):
        for value in ("0.62", "6.2e-1", False, True):
            with self.subTest(value=value):
                text = self.render({"valid": value, "quantity": 19}, "Quantity: {valid}.")
                self.assertIn("quantity: 19", text)
                self.assertNotIn("Quantity:", text)
                bound = self.render({"valid": value}, "Valid: {valid}.")
                self.assertEqual(bound, f"Valid: {value}.")

    def test_unit_suffix_cannot_relabel_an_actual_measurement(self):
        body = {"distance_km": 18, "unit": "km"}
        for template in ("Distance km: {distance_km} miles.", "Distance: {distance_km} miles."):
            with self.subTest(template=template):
                text = self.render(body, template)
                self.assertNotIn("miles", text)
                self.assertIn("distance km: 18", text)
                self.assertIn("unit: km", text)

    def test_literal_quantities_cannot_borrow_a_different_placeholder(self):
        body = {"remaining_stock": 23, "reorder_limit": 7, "location": "West depot"}
        for template in ("Remaining stock is 7. Location: {location}.",
                         "Remaining stock is 99; reorder limit: {reorder_limit}.",
                         "Remaining stock is 7."):
            with self.subTest(template=template):
                text = self.render(body, template)
                self.assertIn("remaining stock: 23", text)
                self.assertNotIn("Remaining stock is", text)

    def test_unbound_comparisons_are_rejected_at_every_position(self):
        body = {"remaining_stock": 23, "reorder_limit": 7}
        for template in (
            "Stock is below the limit. Remaining stock: {remaining_stock}; reorder limit: {reorder_limit}.",
            "Remaining stock: {remaining_stock}. Stock is below the limit. Reorder limit: {reorder_limit}.",
            "Remaining stock: {remaining_stock}; reorder limit: {reorder_limit}. Stock is below the limit.",
            "Remaining stock: {remaining_stock}, which is below the limit; reorder limit: {reorder_limit}.",
        ):
            with self.subTest(template=template):
                text = self.render(body, template)
                self.assertNotIn("below", text)
                self.assertIn("remaining stock: 23", text)
                self.assertIn("reorder limit: 7", text)

    def test_spelled_quantity_cannot_borrow_a_valid_placeholder(self):
        body = {"remaining_stock": 23, "reorder_limit": 7, "location": "West depot"}
        for template in ("Remaining stock is seven. Reorder limit: {reorder_limit}.",
                         "Remaining stock is seven. Location: {location}.",
                         "Remaining stock is seven."):
            with self.subTest(template=template):
                text = self.render(body, template)
                self.assertNotIn("seven", text)
                self.assertIn("remaining stock: 23", text)

    def test_punctuation_does_not_hide_unit_or_completion_claims(self):
        body = {"yield_ratio": 0.62, "output_mass": 248}
        for template in ("Yield ratio: {yield_ratio}, kilograms of output.",
                         "Yield ratio: {yield_ratio}; the transfer is complete.",
                         "Yield ratio: {yield_ratio} and kilograms of output.",
                         "Yield ratio: {yield_ratio}. The whole job succeeded."):
            with self.subTest(template=template):
                text = self.render(body, template)
                self.assertIn("yield ratio: 0.62", text)
                self.assertIn("output mass: 248", text)
                for unsupported in ("kilograms", "complete", "succeeded"):
                    self.assertNotIn(unsupported, text)

    def test_formatted_numeric_strings_keep_their_roles_without_conversion(self):
        for remaining, limit in (("2,300", "1,000"), ("2 300", "1 000"),
                                 ("2\u202f300", "1\u202f000"), ("2’300", "1’000"),
                                 ("$2,300.00", "$1,000.00"), ("2.300,00", "1.000,00"),
                                 ("+2.3E3", "+1E3"), ("２３００", "１０００")):
            with self.subTest(remaining=remaining):
                body = {"remaining_stock": remaining, "reorder_limit": limit}
                text = self.render(body, "Remaining stock: {reorder_limit}.")
                self.assertTrue(text.startswith("Here is what I found:"))
                self.assertIn("remaining stock: " + " ".join(remaining.split()), text)
                self.assertIn("reorder limit: " + " ".join(limit.split()), text)
                self.assertEqual(self.render(body, "Remaining stock: {remaining_stock}; reorder limit: {reorder_limit}."),
                                 f"Remaining stock: {remaining}; reorder limit: {limit}.")

    def test_numeric_containers_cannot_be_relabelled_as_one_measurement(self):
        for body, path in (({"measurement": {"mass": 12.0, "density": 0.8}}, "measurement"),
                           ({"measurements": [{"mass": 12.0, "density": 0.8}]}, "measurements")):
            with self.subTest(path=path):
                for template in (f"The mass is {{{path}}} kilograms.",
                                 f"Measurements: {{{path}}}, kilograms of output."):
                    text = self.render(body, template)
                    self.assertNotIn("kilograms", text)
                    self.assertIn("mass: 12.0", text)
                    self.assertIn("density: 0.8", text)

    def test_container_and_mixed_scalar_pairs_can_keep_explicit_labels(self):
        body = {"measurement": {"mass": 12.0, "density": 0.8}, "station": "North"}
        self.assertEqual(self.render(body, "Measurement: {measurement}; station: {station}."),
                         'Measurement: {"mass": 12.0, "density": 0.8}; station: North.')

    def test_only_separators_can_join_complete_pairs(self):
        body = {"remaining_stock": 23, "reorder_limit": 7}
        for separator in ("; ", ", ", ". ", " and ", ", and "):
            with self.subTest(separator=separator):
                self.assertEqual(self.render(body, "Remaining stock: {remaining_stock}" + separator +
                                                   "reorder limit: {reorder_limit}."),
                                 "Remaining stock: 23" + separator + "reorder limit: 7.")
        for template in ("Remaining stock < {remaining_stock}.",
                         "Remaining stock: {remaining_stock} < reorder limit: {reorder_limit}.",
                         "Remaining stock: {remaining_stock} <= {reorder_limit}."):
            with self.subTest(template=template):
                self.assertNotIn("<", self.render(body, template))

    def test_template_cannot_attach_a_sign_or_decimal_point_to_a_value(self):
        body = {"amount": 23}
        for template in ("Amount -{amount}.", "Amount - {amount}.", "Amount +{amount}.",
                         "Amount .{amount}.", "Amount is -{amount}.", "Amount −{amount}.",
                         "Amount －{amount}.", "Amount [{amount}]."):
            with self.subTest(template=template):
                self.assertFalse(quantitative_template_is_bound(template, body))
                self.assertEqual(self.render(body, template), "Here is what I found: amount: 23.")
        for amount in (-23, 0.23, 23):
            with self.subTest(actual_amount=amount):
                self.assertTrue(quantitative_template_is_bound("Amount: {amount}.", {"amount": amount}))
                self.assertEqual(self.render({"amount": amount}, "Amount: {amount}."), f"Amount: {amount}.")

    def test_field_label_cannot_be_borrowed_from_an_earlier_clause(self):
        body = {"remaining_stock": 23, "reorder_limit": 7}
        for template in ("Reorder limit was checked. Remaining stock: {reorder_limit}.",
                         "Remaining stock based on reorder limit: {reorder_limit}.",
                         "Reorder limit: {reorder_limit}; remaining stock: {reorder_limit}."):
            with self.subTest(template=template):
                text = self.render(body, template)
                self.assertIn("remaining stock: 23", text)
                self.assertNotIn("remaining stock: 7", text.casefold())

    def test_duplicate_nested_field_names_require_the_record_path(self):
        body = {"readings": [{"value": 12}, {"value": 43}]}
        self.assertEqual(self.render(body, "Readings 1 value: {readings.1.value}."),
                         "Readings 1 value: 43.")
        for template in ("Value: {readings.1.value}.", "Readings 0 value: {readings.1.value}."):
            with self.subTest(template=template):
                text = self.render(body, template)
                self.assertIn("value: 12", text)
                self.assertNotIn("value: 43", text)
                self.assertIn("1 additional entries", text)

    def test_unique_nested_quantity_can_keep_its_leaf_label(self):
        self.assertEqual(self.render({"reading": {"humidity": 54}}, "Humidity is {reading.humidity}."),
                         "Humidity is 54.")

    def test_string_explanations_remain_flexible(self):
        body = {"guidance": "Carry drinking water", "options": [{"ref": "ROUTE-C"}]}
        self.assertEqual(self.render(body, "Travel advice: {guidance}."), "Travel advice: Carry drinking water.")

    def test_status_or_unsupported_path_is_not_an_answer(self):
        body = {"remaining_stock": 23, "reorder_limit": 7}
        for template in ("Complete: {status}.", "The amount is {absent}."):
            with self.subTest(template=template):
                self.assertIn("remaining stock: 23", self.render(body, template))

    def test_unsuccessful_outcomes_cannot_be_rendered_as_done(self):
        for status in ("pending", "unknown", "error", "cancel_requested", "not_submitted", "invalidated"):
            with self.subTest(status=status):
                text = self.render({"quantity": 19}, "Done. Quantity: {quantity}.",
                                   status=status, kind="state_modifying")
                self.assertIn("do not have a successful tool result", text)
                self.assertNotIn("19", text)
                self.assertNotIn("Done", text)


class QuantitativeReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivered_read_receipt_renders_fields_without_changing_execution(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"measure_batch": {"kind": "read_only", "args": {}}}
        agent._append_message("user_speech_chunk", {"text": "Measure the batch.", "end_of_turn": True})
        agent._apply({"intent": "measure_batch", "slots": {}, "tool_calls": [{
            "api_name": "measure_batch", "args": {},
            "response_template": "The output is {yield_ratio} kilograms."}]})
        events = []
        while not agent.out_queue.empty():
            events.append(agent.out_queue.get_nowait())
        calls = [row for row in events if row["action"] == "tool_call"]
        self.assertEqual(len(calls), 1)
        result = {"status": "success", "output_mass": 248.0, "yield_ratio": 0.62}
        agent._result({**calls[0]["payload"], "status": "success", "result": result})
        final = agent.out_queue.get_nowait()
        self.assertEqual(final["action"], "final_response")
        self.assertIn("output mass: 248.0", final["payload"]["text"])
        self.assertNotIn("0.62 kilograms", final["payload"]["text"])
        self.assertEqual(len(agent.operations), 1)
        self.assertEqual(agent.tool_results[0]["result"], result)
        self.assertTrue(agent.out_queue.empty())

    async def test_error_receipt_cannot_use_success_template(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"measure_batch": {"kind": "read_only", "args": {}}}
        agent._append_message("user_speech_chunk", {"text": "Measure the batch.", "end_of_turn": True})
        agent._apply({"intent": "measure_batch", "slots": {}, "tool_calls": [{
            "api_name": "measure_batch", "args": {}, "response_template": "Done. Mass: {mass}."}]})
        call = None
        while not agent.out_queue.empty():
            event = agent.out_queue.get_nowait()
            if event["action"] == "tool_call":
                call = event
        self.assertIsNotNone(call)
        agent._result({**call["payload"], "status": "error", "result": {"status": "error", "error": "not_found"}})
        final = agent.out_queue.get_nowait()
        self.assertIn("unable to complete", final["payload"]["text"])
        self.assertNotIn("Done", final["payload"]["text"])
        self.assertEqual(len(agent.operations), 1)

    async def test_conflicting_result_status_is_not_admitted_for_presentation(self):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.tools = {"measure_batch": {"kind": "read_only", "args": {}}}
        agent._append_message("user_speech_chunk", {"text": "Measure the batch.", "end_of_turn": True})
        agent._apply({"intent": "measure_batch", "slots": {}, "tool_calls": [{
            "api_name": "measure_batch", "args": {}, "response_template": "Done. Mass: {mass}."}]})
        call = None
        while not agent.out_queue.empty():
            event = agent.out_queue.get_nowait()
            if event["action"] == "tool_call":
                call = event
        self.assertIsNotNone(call)
        agent._result({**call["payload"], "status": "success", "result": {"status": "error", "mass": 19}})
        self.assertEqual(agent.operations[call["payload"]["call_id"]]["status"], "pending")
        self.assertTrue(agent.out_queue.empty())
