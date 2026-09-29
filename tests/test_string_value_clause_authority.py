import asyncio
import unittest

from participant.agent import ParticipantAgent


class StringValueClauseAuthorityTests(unittest.TestCase):
    def dispatch(self, text, mode):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}]
        agent.tools["set_mode"] = {
            "kind": "state_modifying",
            "description": "Set a mode for a customer.",
            "args": {"mode": {"type": "string"}, "customer": {"type": "string"}},
        }
        agent._dispatch({
            "api_name": "set_mode",
            "args": {"mode": mode, "customer": "Nia"},
            "authorization": {"quote": text, "message_index": 0},
        })
        events = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
        return agent, events

    def test_explanation_cannot_supply_a_conflicting_mode(self):
        agent, events = self.dispatch(
            "Set mode safe for Nia and explain mode dangerous.", "dangerous")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertFalse(agent.operations)

    def test_explicit_mode_still_dispatches(self):
        _, events = self.dispatch("Set mode safe for Nia.", "safe")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["mode"], "safe")

    def test_compound_mode_still_dispatches(self):
        _, events = self.dispatch("Set mode quiet and safe for Nia.", "quiet and safe")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["mode"], "quiet and safe")

    def test_bound_object_accepts_the_string_leaf_before_other_exact_leaves(self):
        command = ("Set settings.mode=safe and settings.limit=2000 "
                   "and settings.enabled=false for Nia.")
        settings = {"mode": "safe", "limit": 2000, "enabled": False}
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": command}}]
        agent.revision = 1
        agent.operations["lookup"] = {
            "kind": "read_only", "status": "success", "revision": 1,
            "key": "lookup-key", "request_start": 0,
            "result": {"settings": settings},
        }
        agent.tools["set_settings"] = {
            "kind": "state_modifying",
            "args": {"settings": {"type": "object", "properties": {
                "mode": {"type": "string"},
                "limit": {"type": "integer"},
                "enabled": {"type": "boolean"},
            }}, "customer": {"type": "string"}},
        }
        agent._dispatch({
            "api_name": "set_settings",
            "args": {"settings": settings, "customer": "Nia"},
            "authorization": {"quote": command, "message_index": 0},
            "result_bindings": {"settings": {"call_id": "lookup", "path": "settings"}},
        })
        events = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

        self.assertEqual([event["action"] for event in events], ["tool_call"])


if __name__ == "__main__":
    unittest.main()
