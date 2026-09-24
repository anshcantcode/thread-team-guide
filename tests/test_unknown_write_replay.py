"""Unresolved equivalent writes stay blocked across interruption event encodings."""
import asyncio
import unittest

from participant.agent import ParticipantAgent


TEXT = "Create a note called hello."
TOOL = {"kind": "state_modifying", "description": "Create a note.",
        "args": {"text": {"type": "string", "required": True}}}


def step(text="hello"):
    quote = TEXT if text == "hello" else f"Create a note called {text}."
    return {"api_name": "create_note", "args": {"text": text}, "authorization": {"quote": quote}}


def event(agent, kind, payload=None):
    agent._handle({"event_type": kind, "payload": payload or {}})


def make_agent():
    agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
    agent.tools = {"create_note": TOOL}
    agent._start_plan = lambda: None
    event(agent, "user_speech_chunk", {"text": TEXT, "end_of_turn": True})
    assert agent._dispatch(step())
    original = next(iter(agent.operations.values()))
    return agent, original


def make_unresolved(agent, original, status):
    if status == "unknown":
        agent._result({"call_id": original["call_id"], "api_name": original["api_name"],
                       "status": "error", "result": {"status": "error", "error": "timeout",
                                                            "receipt_id": "RECEIPT-1"}})
    else:
        assert status == "cancel_requested"


class UnknownWriteReplayTests(unittest.TestCase):
    def block_duplicate(self, scenario, status):
        agent, original = make_agent()
        make_unresolved(agent, original, status)
        if scenario == "spoken interruption":
            event(agent, "interruption", {"text": TEXT})
        elif scenario in {"new text", "new audio", "split speech"}:
            event(agent, "interruption")
            if scenario == "new text":
                event(agent, "user_speech_chunk", {"text": TEXT, "end_of_turn": True})
            elif scenario == "new audio":
                index = len(agent.messages)
                event(agent, "user_audio_chunk", {"audio_ref": "recording", "end_of_turn": True})
                agent.observations[index] = {"uncertain": False, "transcript": TEXT}
            else:
                event(agent, "user_speech_chunk", {"text": "Create a note ", "end_of_turn": False})
                event(agent, "user_speech_chunk", {"text": "called hello.", "end_of_turn": True})
        else:
            self.fail(f"unknown scenario: {scenario}")

        self.assertFalse(agent._dispatch(step()))
        self.assertEqual(len(agent.operations), 1)
        self.assertEqual(original["status"], status)
        self.assertEqual(original.get("result", {}).get("receipt_id"),
                         "RECEIPT-1" if status == "unknown" else None)
        tool_calls = [action["payload"]["call_id"] for action in self._drain(agent)
                      if action["action"] == "tool_call"]
        self.assertEqual(tool_calls, [original["call_id"]])

    @staticmethod
    def _drain(agent):
        actions = []
        while not agent.out_queue.empty():
            actions.append(agent.out_queue.get_nowait())
        return actions

    def test_unresolved_equivalent_write_is_blocked_for_each_interruption_encoding(self):
        for scenario in ("spoken interruption", "new text", "new audio", "split speech"):
            for status in ("unknown", "cancel_requested"):
                with self.subTest(scenario=scenario, status=status):
                    self.block_duplicate(scenario, status)

    def test_distinct_effect_and_fresh_authorization_after_resolution_remain_allowed(self):
        agent, original = make_agent()
        agent._result({"call_id": original["call_id"], "api_name": original["api_name"],
                       "status": "success", "result": {"status": "success", "receipt_id": "RECEIPT-1"}})
        event(agent, "user_speech_chunk", {"text": "Create a note called hello.", "end_of_turn": True})
        self.assertTrue(agent._dispatch(step()))

        other, unresolved = make_agent()
        make_unresolved(other, unresolved, "unknown")
        event(other, "interruption")
        event(other, "user_speech_chunk", {"text": "Create a note called goodbye.", "end_of_turn": True})
        self.assertTrue(other._dispatch(step("goodbye")))


if __name__ == "__main__":
    unittest.main()
