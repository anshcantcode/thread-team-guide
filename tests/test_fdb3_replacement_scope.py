"""Generic actor stories for explicit cancellation followed by replacement."""
import asyncio
from copy import deepcopy
import unittest

from participant.agent import ParticipantAgent


TOOLS = {
    "append_entry": {"kind": "state_modifying", "description": "Append an entry to the work queue.",
                     "args": {"text": {"type": "string", "required": True}}},
    "publish_notice": {"kind": "state_modifying", "description": "Publish a notice to the bulletin.",
                       "args": {"body": {"type": "string", "required": True}}},
    "set_entry": {"kind": "state_modifying", "description": "Set an entry's complete state.", "args": {
        "entry_id": {"type": "string", "required": True}, "complete": {"type": "boolean", "required": True}}},
}
OLD = "Append dust the silver tray to my work queue."
CANCEL = "No, do not append silver tray."
NEW = "Append polish the brass lamp to my work queue instead."


def proposal(text="polish the brass lamp", quote=NEW, **extra):
    return {"api_name": "append_entry", "args": {"text": text}, "authorization": {"quote": quote}, **extra}


class Planner:
    def __init__(self): self.decision = {}
    async def setup(self): pass
    async def close(self): pass
    async def plan(self, context): return deepcopy(self.decision)


class ReplacementScopeTests(unittest.IsolatedAsyncioTestCase):
    async def run_story(self, turns, step=None, *, prior_status=None, deliver_result=False):
        step = deepcopy(step or proposal())
        planner = Planner()
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=planner)
        task = asyncio.create_task(agent.run())
        emitted = []

        async def terminal():
            while True:
                event = await asyncio.wait_for(agent.out_queue.get(), 2)
                emitted.append(event)
                if event["action"] in {"tool_call", "clarification_request", "final_response"}:
                    return event

        async def barrier():
            ready = asyncio.Event()
            await agent.in_queue.put({"event_type": "controller_barrier", "payload": {"ready": ready}})
            await asyncio.wait_for(ready.wait(), 2)

        try:
            await agent.in_queue.put({"event_type": "tool_manifest", "payload": {"tools": TOOLS}})
            final = None
            for turn, text in enumerate(turns):
                first_effect = turn == 0 and prior_status is not None
                current = proposal("dust the silver tray", OLD) if first_effect else step
                planner.decision = ({"tool_calls": [current]} if first_effect or turn == len(turns) - 1
                                    else {"response": "Awaiting the next instruction."})
                chunks = text if isinstance(text, list) else [text]
                for index, chunk in enumerate(chunks):
                    await agent.in_queue.put({"event_type": "user_speech_chunk", "payload": {
                        "text": chunk, "end_of_turn": index == len(chunks) - 1}})
                    if index < len(chunks) - 1:
                        await barrier()
                final = await terminal()
                if first_effect:
                    self.assertEqual(final["action"], "tool_call")
                    call_id = final["payload"]["call_id"]
                    if prior_status == "not_submitted":
                        await agent.in_queue.put({"event_type": "tool_not_submitted", "payload": {
                            "call_id": call_id, "api_name": "append_entry"}})
                        await barrier()
                    else:
                        agent.operations[call_id]["execution_admitted"] = True
                        if prior_status in {"success", "unknown"}:
                            status = "error" if prior_status == "unknown" else "success"
                            await agent.in_queue.put({"event_type": "tool_result", "payload": {
                                "call_id": call_id, "api_name": "append_entry", "status": status,
                                "result": {"status": status, **({"error": "timeout"} if status == "error" else {"entry_id": "E-1"})}}})
                            await terminal()
            if deliver_result and final["action"] == "tool_call":
                await agent.in_queue.put({"event_type": "tool_result", "payload": {
                    **{key: final["payload"][key] for key in ("call_id", "api_name")}, "status": "success",
                    "result": {"status": "success", "entry_id": "E-8"}}})
                await barrier()
                while not agent.out_queue.empty():
                    emitted.append(agent.out_queue.get_nowait())
            return final, emitted, deepcopy(agent.operations), deepcopy(agent.messages)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_three_final_turns_accept_only_literal_new_multiword_value(self):
        final, emitted, operations, messages = await self.run_story([OLD, CANCEL, NEW])
        self.assertEqual(final["action"], "tool_call")
        self.assertEqual(final["payload"]["args"], {"text": "polish the brass lamp"})
        self.assertEqual(len(operations), 1)
        self.assertEqual([m["payload"]["text"] for m in messages], [OLD, CANCEL, NEW])
        self.assertEqual(sum(e["action"] == "tool_call" for e in emitted), 1)

    async def test_same_turn_cancellation_and_replacement_uses_surviving_span(self):
        final, _, operations, _ = await self.run_story([CANCEL + " " + NEW])
        self.assertEqual(final["action"], "tool_call")
        self.assertEqual(len(operations), 1)

    async def test_another_tool_verb_and_argument_name_use_same_mechanism(self):
        text = "Publish the revised workshop agenda to the bulletin instead."
        step = {"api_name": "publish_notice", "args": {"body": "the revised workshop agenda"},
                "authorization": {"quote": text}}
        final, _, _, _ = await self.run_story([
            "Publish the old workshop agenda to the bulletin.",
            "No, do not publish the old workshop agenda.", text], step)
        self.assertEqual(final["action"], "tool_call")

    async def test_fabricated_quote_with_period_replacing_instead_rejects(self):
        final, _, operations, _ = await self.run_story([OLD, CANCEL, NEW],
            proposal(quote="Append polish the brass lamp to my work queue."))
        self.assertEqual(final["action"], "clarification_request")
        self.assertEqual(operations, {})

    async def test_obsolete_changed_truncated_or_extra_value_cannot_bind(self):
        for value in ("dust the silver tray", "polish the silver lamp", "brass lamp", "polish the brass lamp and door"):
            with self.subTest(value=value):
                final, _, operations, _ = await self.run_story([OLD, CANCEL, NEW], proposal(value))
                self.assertEqual(final["action"], "clarification_request")
                self.assertEqual(operations, {})

    async def test_prior_or_replacement_conditions_and_reported_sources_reject(self):
        histories = [("If approved, " + OLD, CANCEL, NEW), ("She said " + OLD, CANCEL, NEW),
                     ('"' + OLD + '"', CANCEL, NEW), (OLD, CANCEL[:-1] + " when approved.", NEW),
                     (OLD, "She said " + CANCEL, NEW), (OLD, CANCEL, NEW[:-8] + "when approved instead.")]
        for turns in histories:
            with self.subTest(turns=turns):
                final, _, operations, _ = await self.run_story(turns, proposal(quote=turns[-1]))
                self.assertEqual(final["action"], "clarification_request")
                self.assertEqual(operations, {})

    async def test_cancellation_alone_or_missing_cancel_scope_cannot_authorize(self):
        # Once an earlier turn named this action, "instead" needs the full history-checked
        # replacement shape. (A first turn's "... instead." has nothing earlier to replace
        # and is covered by test_first_turn_instead_is_a_plain_request.)
        for turns in ([OLD, CANCEL], [OLD, NEW], [OLD, "No, do not publish silver tray.", NEW]):
            with self.subTest(turns=turns):
                final, _, operations, _ = await self.run_story(turns)
                self.assertEqual(final["action"], "clarification_request")
                self.assertEqual(operations, {})

    async def test_first_turn_instead_is_a_plain_request(self):
        # Changed 28 Sep: with no earlier turn naming the action, "instead" refers to the
        # current state ("pull from savings instead"), not to a request it could undo.
        final, _, operations, _ = await self.run_story([NEW])
        self.assertEqual(final["action"], "tool_call")
        self.assertEqual(len(operations), 1)

    async def test_admitted_success_or_unknown_old_effect_is_never_assumed_undone(self):
        for status in ("pending", "success", "unknown"):
            with self.subTest(status=status):
                final, emitted, operations, _ = await self.run_story([OLD, CANCEL, NEW], prior_status=status)
                self.assertEqual(final["action"], "clarification_request")
                self.assertEqual(len(operations), 1)
                self.assertEqual(sum(e["action"] == "tool_call" for e in emitted), 1)

    async def test_definitely_not_submitted_old_effect_allows_replacement(self):
        final, _, operations, _ = await self.run_story([OLD, CANCEL, NEW], prior_status="not_submitted")
        self.assertEqual(final["action"], "tool_call")
        self.assertEqual(operations["call-1"]["status"], "not_submitted")
        self.assertEqual(len(operations), 2)

    async def test_unrequested_after_result_cannot_mark_new_entry_complete(self):
        step = proposal(after_result={"api_name": "set_entry", "args": {"complete": True},
            "bindings": {"entry_id": "entry_id"}, "authorization": {"quote": "Set E-8 complete=true"}})
        final, emitted, operations, _ = await self.run_story([OLD, CANCEL, NEW], step, deliver_result=True)
        self.assertEqual(final["action"], "tool_call")
        self.assertEqual([e["payload"]["api_name"] for e in emitted if e["action"] == "tool_call"], ["append_entry"])
        self.assertEqual(len(operations), 1)

    async def test_replacement_quote_must_use_actual_current_message_index(self):
        for index in (0, 1, 99, True, "2"):
            with self.subTest(index=index):
                step = proposal()
                step["authorization"]["message_index"] = index
                final, _, operations, _ = await self.run_story([OLD, CANCEL, NEW], step)
                self.assertEqual(final["action"], "clarification_request")
                self.assertEqual(operations, {})
        step = proposal()
        step["authorization"]["message_index"] = 2
        final, _, _, _ = await self.run_story([OLD, CANCEL, NEW], step)
        self.assertEqual(final["action"], "tool_call")

    async def test_chunked_same_turn_scope_keeps_original_quote_indices(self):
        step = proposal(quote="Append polish the brass lamp")
        step["authorization"]["message_index"] = 1
        final, _, _, messages = await self.run_story([[CANCEL, "Append polish the brass lamp", "to my work queue instead."]], step)
        self.assertEqual(final["action"], "tool_call")
        self.assertEqual(messages[0]["payload"]["text"], CANCEL)
        step["authorization"]["message_index"] = 0
        final, _, operations, _ = await self.run_story([[CANCEL, "Append polish the brass lamp", "to my work queue instead."]], step)
        self.assertEqual(final["action"], "clarification_request")
        self.assertEqual(operations, {})

    async def test_mixed_cancellation_quote_and_new_destination_reject(self):
        final, _, operations, _ = await self.run_story([CANCEL + " " + NEW], proposal(quote=CANCEL + " " + NEW))
        self.assertEqual(final["action"], "clarification_request")
        self.assertEqual(operations, {})
        changed = NEW.replace("work queue", "archive")
        final, _, operations, _ = await self.run_story([OLD, CANCEL, changed], proposal(quote=changed))
        self.assertEqual(final["action"], "clarification_request")
        self.assertEqual(operations, {})

    async def test_pronouns_or_additional_actions_do_not_form_literal_replacement(self):
        for value in ("it", "wash it", "the selected entry", "polish the lamp and delete logs", "polish the lamp then publish news"):
            with self.subTest(value=value):
                text = "Append " + value + " to my work queue instead."
                final, _, operations, _ = await self.run_story([OLD, CANCEL, text], proposal(value, text))
                self.assertEqual(final["action"], "clarification_request")
                self.assertEqual(operations, {})


if __name__ == "__main__":
    unittest.main()
