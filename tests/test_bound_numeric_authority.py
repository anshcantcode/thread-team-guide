import asyncio
import unittest

from participant.agent import ParticipantAgent


class BoundNumericAuthorityTests(unittest.TestCase):
    def agent(self, text, *, result=2000, status="success", result_revision=4):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}]
        agent.revision = 4
        agent.operations = {"sensor-1": {
            "kind": "read_only", "key": "read_sensor:lab", "request_start": 0,
            "status": status, "result": {"temperature": result}, "revision": result_revision}}
        agent.tools["set_limit"] = {
            "kind": "state_modifying",
            "description": "Set a limit for a customer.",
            "args": {
                "limit": {"type": "integer", "required": True},
                "customer": {"type": "string", "required": True},
            },
        }
        return agent

    def dispatch(self, text, quote, *, result=2000, proposed=2000, status="success", result_revision=4):
        agent = self.agent(text, result=result, status=status, result_revision=result_revision)
        agent._dispatch({
            "api_name": "set_limit",
            "args": {"limit": proposed, "customer": "Nia"},
            "authorization": {"quote": quote},
            "result_bindings": {"limit": {"call_id": "sensor-1", "path": "temperature"}},
        })
        events = []
        while not agent.out_queue.empty():
            events.append(agent.out_queue.get_nowait())
        return agent, events

    def test_result_cannot_override_explicit_named_limit(self):
        text = "Read the sensor for lab. Then set limit 2 for Nia."
        agent, events = self.dispatch(text, "set limit 2 for Nia")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertFalse(any(operation.get("kind") == "state_modifying"
                             for operation in agent.operations.values()))

    def test_matching_explicit_value_and_returned_value_are_allowed(self):
        cases = (
            ("Read the sensor for lab. Then set limit 2000 for Nia.", "set limit 2000 for Nia"),
            ("Read the sensor for lab. Then set limit to the returned value for Nia.",
             "set limit to the returned value for Nia"),
        )
        for text, quote in cases:
            with self.subTest(text=text):
                _, events = self.dispatch(text, quote)
                self.assertEqual([event["action"] for event in events], ["tool_call"])

    def test_result_must_remain_successful_matching_and_current(self):
        cases = (
            {"status": "failed"},
            {"result": 1000},
            {"result_revision": 3},
        )
        text = "Read the sensor for lab. Then set limit 2000 for Nia."
        for options in cases:
            with self.subTest(options=options):
                _, events = self.dispatch(text, "set limit 2000 for Nia", **options)
                self.assertEqual([event["action"] for event in events], ["clarification_request"])


if __name__ == "__main__":
    unittest.main()
