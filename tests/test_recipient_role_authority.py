import asyncio
import unittest

from participant.agent import ParticipantAgent


class RecipientRoleAuthorityTests(unittest.TestCase):
    TEXT = "Send a message to Nia saying Omar arrived."

    def dispatch(self, recipient, description):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": self.TEXT}}]
        agent.tools["send_message"] = {
            "kind": "state_modifying",
            "description": "Send a message to a recipient.",
            "args": {
                "recipient": {"type": "string", "required": True, "description": description},
                "message": {"type": "string", "required": True, "description": "Message text."},
            },
        }
        agent._dispatch({
            "api_name": "send_message",
            "args": {"recipient": recipient, "message": "Omar arrived"},
            "authorization": {"quote": self.TEXT, "message_index": 0},
        })
        return agent, [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    def test_body_name_cannot_override_recipient_role(self):
        for description in ("Recipient name.", "Recipient of the message."):
            with self.subTest(description=description):
                agent, events = self.dispatch("Omar", description)

                self.assertEqual([event["action"] for event in events], ["clarification_request"])
                self.assertFalse(agent.operations)

    def test_unmentioned_recipient_is_not_authorized_by_body_descriptor(self):
        agent, events = self.dispatch("Zoe", "Recipient of the message.")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertFalse(agent.operations)

    def test_explicit_recipient_and_message_body_are_preserved(self):
        _, events = self.dispatch("Nia", "Recipient of the message.")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"], {
            "recipient": "Nia", "message": "Omar arrived"})


if __name__ == "__main__":
    unittest.main()
