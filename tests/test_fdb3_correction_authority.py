"""Independent correction-authority stories through the actual actor loop."""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent


TOOLS = {
    "add_ingredient": {"kind": "state_modifying", "description": "Add an ingredient.",
                       "args": {"ingredient": {"type": "string", "required": True}}},
    "set_device": {"kind": "state_modifying", "description": "Set a device.", "args": {
        "device": {"type": "string", "required": True}, "enabled": {"type": "boolean", "required": True}}},
    "schedule_job": {"kind": "state_modifying", "description": "Schedule a job.", "args": {
        "job": {"type": "string", "required": True}, "duration": {"type": "number", "required": True}}},
    "send_note": {"kind": "state_modifying", "description": "Send a note.", "args": {
        "recipient": {"type": "string", "required": True}, "message": {"type": "string", "required": True}}},
}


class Planner:
    def __init__(self, step): self.step = step
    async def setup(self): pass
    async def close(self): pass
    async def plan(self, context): return {"intent": "requested_action", "slots": {}, "tool_calls": [self.step]}


def addition(ingredient="fennel", quote="add fennel", **authorization):
    return {"api_name": "add_ingredient", "args": {"ingredient": ingredient},
            "authorization": {"quote": quote, **authorization}}


class CorrectionAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def probe(self, text, step=None, *, before=None, tools=None):
        planner = Planner(deepcopy(step or addition()))
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        task = asyncio.create_task(agent.run())
        async def terminal():
            while True:
                event = await asyncio.wait_for(agent.out_queue.get(), 2)
                if event["action"] in {"tool_call", "clarification_request", "final_response"}:
                    return event
        try:
            await agent.in_queue.put({"event_type": "tool_manifest", "payload": {"tools": tools or TOOLS}})
            if before:
                planner.step = before[1]
                await agent.in_queue.put({"event_type": "user_speech_chunk", "payload": {"text": before[0], "end_of_turn": True}})
                old = await terminal()
                self.assertEqual(old["action"], "tool_call")
                not_submitted = len(before) > 2 and before[2] == "not_submitted"
                if not not_submitted:
                    agent.operations[old["payload"]["call_id"]]["execution_admitted"] = True
                if len(before) > 2:
                    status = before[2]
                    if not_submitted:
                        await agent.in_queue.put({"event_type": "tool_not_submitted", "payload": {
                            "call_id": old["payload"]["call_id"], "api_name": before[1]["api_name"]}})
                        ready = asyncio.Event()
                        await agent.in_queue.put({"event_type": "controller_barrier", "payload": {"ready": ready}})
                        await asyncio.wait_for(ready.wait(), 2)
                    else:
                        await agent.in_queue.put({"event_type": "tool_result", "payload": {
                            "call_id": old["payload"]["call_id"], "api_name": before[1]["api_name"], "status": status,
                            "result": {"status": status, **({"error": "timeout"} if status == "error" else {})}}})
                        await terminal()
                planner.step = deepcopy(step or addition())
            chunks = text if isinstance(text, list) else [text]
            for index, chunk in enumerate(chunks):
                await agent.in_queue.put({"event_type": "user_speech_chunk", "payload": {
                    "text": chunk, "end_of_turn": index == len(chunks) - 1}})
                if index < len(chunks) - 1:
                    ready = asyncio.Event()
                    await agent.in_queue.put({"event_type": "controller_barrier", "payload": {"ready": ready}})
                    await asyncio.wait_for(ready.wait(), 2)
                    self.assertEqual(agent.operations, {})
            event = await terminal()
            return event, deepcopy(agent.operations)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def rejected(self, text, step=None, **options):
        event, operations = await self.probe(text, step, **options)
        self.assertEqual(event["action"], "clarification_request", (text, event))
        if not options.get("before"):
            self.assertEqual(operations, {})

    async def accepted(self, text, step=None):
        event, operations = await self.probe(text, step)
        self.assertEqual(event["action"], "tool_call", (text, event))
        self.assertEqual(event["payload"]["args"], (step or addition())["args"])
        self.assertEqual(len(operations), 1)

    async def test_actually_cannot_authorize_superseded_quote(self):
        await self.rejected("Add cumin. Actually, add fennel.", addition("cumin", "Add cumin"))

    async def test_corrected_when_approved_is_not_authority(self):
        await self.rejected("Add cumin. Actually, add fennel when approved.")

    async def test_standalone_qualifications_require_proof(self):
        for qualification in ("when approved", "after approval", "provided that approval arrives", "unless declined",
                              "once approved", "assuming approval arrives", "as long as approved"):
            with self.subTest(qualification=qualification):
                await self.rejected("Add fennel " + qualification + ".")

    async def test_complete_replacement_is_only_surviving_authority(self):
        for marker in ("No", "Actually"):
            for quote in ("add fennel", "add fennel."):
                with self.subTest(marker=marker, quote=quote):
                    await self.accepted("Add cumin. " + marker + ", add fennel.", addition(quote=quote))

    async def test_multiple_descriptor_verbs_and_flat_primitive_shapes(self):
        cases = [
            ("Set lamp enabled=false. No, set fan enabled=true.",
             {"api_name": "set_device", "args": {"device": "fan", "enabled": True},
              "authorization": {"quote": "set fan enabled=true"}}),
            ("Schedule job=Orion, duration=4. Actually, schedule job=Vega, duration=2.5.",
             {"api_name": "schedule_job", "args": {"job": "Vega", "duration": 2.5},
              "authorization": {"quote": "schedule job=Vega, duration=2.5"}}),
            ("Send recipient=Noor, message=ready. No, send recipient=Lina, message=arrived.",
             {"api_name": "send_note", "args": {"recipient": "Lina", "message": "arrived"},
              "authorization": {"quote": "send recipient=Lina, message=arrived"}}),
        ]
        for text, step in cases:
            with self.subTest(text=text):
                await self.accepted(text, step)

    async def test_mixed_or_wrong_target_quotes_do_not_borrow_old_arguments(self):
        text = "Add cumin. No, add fennel."
        for step in (addition("cumin", "add fennel"), addition("cumin", "Add cumin"),
                     addition("fennel", text), addition("fennel", "fennel")):
            with self.subTest(step=step):
                await self.rejected(text, step)

    async def test_original_conditions_cannot_disappear_with_replacement(self):
        for old in ("Add cumin if approved", "Add cumin when approved", "Add cumin after approval",
                    "Add cumin provided that approval arrives", "If approved, add cumin", "Maybe add cumin"):
            with self.subTest(old=old):
                await self.rejected(old + ". No, add fennel.")

    async def test_negative_or_qualified_replacement_cannot_cherry_pick_authority(self):
        for new in ("do not add fennel", "add fennel if approved", "add fennel when approved",
                    "add fennel after approval", "add fennel provided that approval arrives",
                    "add fennel unless declined", "add fennel only after approval", "maybe add fennel"):
            with self.subTest(new=new):
                await self.rejected("Add cumin. Actually, " + new + ".")

    async def test_quotation_reporting_hypothetical_and_questions_reject(self):
        for text in ('"Add cumin. No, add fennel."', "He said Add cumin. No, add fennel.",
                     "Imagine: Add cumin. No, add fennel.", "Suppose Add cumin. No, add fennel.",
                     "Should I add cumin? No, add fennel."):
            with self.subTest(text=text):
                await self.rejected(text)

    async def test_retracted_question_then_imperative_authorizes_only_the_imperative(self):
        # Sprint 2: the cited clause is a plain imperative with no scope marker; the
        # earlier question is retracted, not a condition on it.
        await self.accepted("Add cumin? Actually, add fennel.")

    async def test_pronouns_ellipsis_delegation_and_multiple_tasks_reject(self):
        for text in ("Add cumin. No, fennel.", "Add cumin. No, add it.",
                     "Add cumin. No, add the selected result.",
                     "Add cumin. No, add fennel. No, add dill.",
                     "Add cumin. No, add fennel. Stop.",
                     "Add cumin. Actually add fennel."):
            with self.subTest(text=text):
                await self.rejected(text)

    async def test_corrected_command_keeps_authority_beside_unrelated_later_tasks(self):
        # Sprint 2 (clause-scoped authority): a leading retraction marker retracts what
        # precedes it, and a later independent task does not retract the correction.
        # Later retractions ("No, add dill.", "Stop.") still reject above.
        for text in ("Add cumin. No, add fennel. Add dill.", "Add cumin. No, add fennel. Find a recipe.",
                     "No, add fennel.", "Actually, add fennel.",
                     # Same-turn replacement with its earlier command present in the turn.
                     "Add cumin. Instead, add fennel."):
            with self.subTest(text=text):
                await self.accepted(text)

    async def test_multiword_replacement_keeps_the_complete_value(self):
        # Sprint 2: full multiword values are retained; a truncated value still rejects.
        await self.accepted("Add dried-cumin. No, add fresh fennel.", addition("fresh fennel", "add fresh fennel"))
        await self.rejected("Add dried-cumin. No, add fresh fennel.", addition("fresh", "add fresh fennel"))

    async def test_explicit_literal_pronoun_target_cannot_fake_complete_replacement(self):
        for value in ("it", "them", "selected", "first"):
            with self.subTest(value=value):
                await self.rejected("Add cumin. No, add " + value + ".", addition(value, "add " + value))

    async def test_replacement_must_state_its_own_complete_arguments(self):
        step = {"api_name": "set_device", "args": {"device": "fan", "enabled": True},
                "authorization": {"quote": "set fan enabled=true"}}
        # Sprint 2: the replacement states every argument itself, so the incomplete
        # retracted clause is irrelevant. Values are never borrowed from it:
        await self.accepted("Set lamp. No, set fan enabled=true.", step)
        step["authorization"]["quote"] = "set fan"
        await self.rejected("Set lamp enabled=false. No, set fan.", step)

    async def test_retracted_different_action_leaves_only_the_new_action(self):
        # Sprint 2: "No" retracts the removal; the only surviving request is to add
        # fennel. The retracted removal is never executed or inferred as an undo.
        await self.accepted("Remove cumin. No, add fennel.")

    async def test_numeric_value_or_quote_cannot_be_shortened(self):
        step = {"api_name": "schedule_job", "args": {"job": "Vega", "duration": 2},
                "authorization": {"quote": "schedule job=Vega duration=2"}}
        await self.rejected("Schedule job=Orion duration=4. No, schedule job=Vega duration=2.5.", step)

    async def test_chunked_replacement_and_indices_use_original_message_positions(self):
        await self.accepted(["Add cumin.", "No, add fennel."], addition(message_index=1))
        await self.accepted(["Add cumin. No,", "add", "fennel."], addition())
        await self.accepted(["Add cumin. No", ", add fennel."], addition(message_index=1))
        for index in (0, -1, 99, True, "1"):
            with self.subTest(index=index):
                await self.rejected(["Add cumin.", "No, add fennel."], addition(message_index=index))

    async def test_unicode_and_whitespace_do_not_shift_authority_to_old_chunk(self):
        await self.accepted(["  Add café.  ", "\tActually, add fenouil. "], addition("fenouil", "add fenouil", message_index=1))
        await self.rejected(["  Add café.  ", "\tActually, add fenouil. "], addition("café", "Add café", message_index=0))

    async def test_two_independent_affirmative_commands_keep_separate_authority(self):
        await self.accepted("Add cumin. Add fennel.")
        await self.accepted("Add cumin. Add fennel.", addition("cumin", "Add cumin"))

    async def test_correction_does_not_replace_an_already_submitted_effect(self):
        for status in (None, "success", "error"):
            with self.subTest(status=status):
                before = ("Add cumin.", addition("cumin", "Add cumin"))
                if status:
                    before += (status,)
                await self.rejected("Add cumin. No, add fennel.", before=before)

    async def test_plain_fresh_instruction_remains_separate_from_correction(self):
        event, operations = await self.probe("Add fennel.", before=("Add cumin.", addition("cumin", "Add cumin")))
        self.assertEqual(event["action"], "tool_call")
        self.assertEqual(len(operations), 2)

    async def test_omitted_optional_old_argument_cannot_hide_submitted_effect(self):
        tools = deepcopy(TOOLS)
        tools["add_ingredient"]["args"]["amount"] = {"type": "integer", "required": False, "default": 1}
        for amount in (1, 7):
            with self.subTest(amount=amount):
                old = addition("cumin", f"Add cumin amount={amount}")
                old["args"]["amount"] = amount
                await self.rejected("Add cumin. No, add fennel.", tools=tools,
                                    before=(f"Add cumin amount={amount}.", old))

    async def test_known_not_submitted_optional_old_effect_allows_replacement(self):
        tools = deepcopy(TOOLS)
        tools["add_ingredient"]["args"]["amount"] = {"type": "integer", "required": False, "default": 1}
        old = addition("cumin", "Add cumin amount=7")
        old["args"]["amount"] = 7
        event, operations = await self.probe("Add cumin. No, add fennel.", tools=tools,
            before=("Add cumin amount=7.", old, "not_submitted"))
        self.assertEqual(event["action"], "tool_call")
        self.assertEqual(operations["call-1"]["status"], "not_submitted")
        self.assertEqual(event["payload"]["args"], {"ingredient": "fennel"})

    async def test_equivalent_descriptor_api_alias_cannot_hide_submitted_old_effect(self):
        tools = deepcopy(TOOLS)
        tools["add_ingredient_alternate"] = deepcopy(tools["add_ingredient"])
        replacement = addition()
        replacement["api_name"] = "add_ingredient_alternate"
        await self.rejected("Add cumin. No, add fennel.", replacement, tools=tools,
                            before=("Add cumin.", addition("cumin", "Add cumin")))

    async def test_renamed_target_field_cannot_hide_submitted_old_effect(self):
        tools = deepcopy(TOOLS)
        tools["add_item"] = {"kind": "state_modifying", "description": "Add an ingredient.",
                             "args": {"item": {"type": "string", "required": True}}}
        replacement = {"api_name": "add_item", "args": {"item": "fennel"},
                       "authorization": {"quote": "add fennel"}}
        await self.rejected("Add cumin. No, add fennel.", replacement, tools=tools,
                            before=("Add cumin.", addition("cumin", "Add cumin")))

    async def test_distinct_provided_old_value_does_not_match_unrelated_effect(self):
        event, operations = await self.probe("Add cumin. No, add fennel.",
            before=("Add coriander.", addition("coriander", "Add coriander")))
        self.assertEqual(event["action"], "tool_call")
        self.assertEqual(event["payload"]["args"], {"ingredient": "fennel"})
        self.assertEqual(len(operations), 2)

    async def test_qualifier_words_inside_json_argument_data_remain_data(self):
        tool = {"kind": "state_modifying", "description": "Set preferences.", "args": {
            "preferences": {"type": "object", "required": True, "properties": {
                "note": {"type": "string", "required": True}}}}}
        text = 'Set preferences {"note":"when approved, after approval, provided that accepted"}.'
        step = {"api_name": "set_preferences", "args": {"preferences": {
            "note": "when approved, after approval, provided that accepted"}}, "authorization": {"quote": text}}
        event, _ = await self.probe(text, step, tools={"set_preferences": tool})
        self.assertEqual(event["action"], "tool_call")


if __name__ == "__main__":
    unittest.main()
