import asyncio
import unittest

from participant.agent import ParticipantAgent


class RecipientArrayAuthorityTests(unittest.TestCase):
    TEXT = "Send a message to Nia saying Omar arrived."

    def dispatch(self, recipient, *, array=False):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": self.TEXT}}]
        recipient_schema = {
            "type": "array",
            "required": True,
            "items": {"type": "string", "description": "Recipient name."},
        } if array else {
            "type": "string", "required": True, "description": "Recipient name."
        }
        agent.tools["send_message"] = {
            "kind": "state_modifying",
            "description": "Send a message to a recipient.",
            "args": {
                "recipient": recipient_schema,
                "message": {"type": "string", "required": True, "description": "Message text."},
            },
        }
        agent._dispatch({
            "api_name": "send_message",
            "args": {"recipient": recipient, "message": "Omar arrived"},
            "authorization": {"quote": self.TEXT, "message_index": 0},
        })
        events = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
        return agent, events

    def test_array_recipient_cannot_borrow_a_name_from_the_message(self):
        agent, events = self.dispatch(["Omar"], array=True)

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertFalse(agent.operations)

    def test_explicit_array_recipient_dispatches(self):
        _, events = self.dispatch(["Nia"], array=True)

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"], {
            "recipient": ["Nia"], "message": "Omar arrived"})

    def test_scalar_recipient_controls(self):
        for recipient, expected in (("Omar", "clarification_request"), ("Nia", "tool_call")):
            with self.subTest(recipient=recipient):
                agent, events = self.dispatch(recipient)

                self.assertEqual([event["action"] for event in events], [expected])
                self.assertEqual(bool(agent.operations), expected == "tool_call")


if __name__ == "__main__":
    unittest.main()
