import asyncio
import unittest

from participant.agent import ParticipantAgent


class MessageBodyAuthorityTests(unittest.TestCase):
    def dispatch(self, text, message):
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue())
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}}]
        agent.tools["send_message"] = {
            "kind": "state_modifying",
            "description": "Send a message to a recipient.",
            "args": {
                "recipient": {"type": "string", "required": True, "description": "Recipient name."},
                "message": {"type": "string", "required": True, "description": "Message text."},
            },
        }
        agent._dispatch({
            "api_name": "send_message",
            "args": {"recipient": "Nia", "message": message},
            "authorization": {"quote": text, "message_index": 0},
        })
        return agent, [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]

    def test_rejects_replacement_for_explicitly_dictated_message(self):
        text = "Send a message to Nia saying Omar arrived."
        agent, events = self.dispatch(text, "Your account is suspended")

        self.assertEqual([event["action"] for event in events], ["clarification_request"])
        self.assertFalse(agent.operations)

    def test_accepts_exactly_dictated_message(self):
        text = "Send a message to Nia saying Omar arrived."
        _, events = self.dispatch(text, "Omar arrived")

        self.assertEqual([event["action"] for event in events], ["tool_call"])
        self.assertEqual(events[0]["payload"]["args"]["message"], "Omar arrived")

    def test_keeps_delegated_message_content_flexible_without_dictation(self):
        text = "Send Nia a message about my arrival later."
        _, events = self.dispatch(text, "I might be a little late.")

        self.assertEqual([event["action"] for event in events], ["tool_call"])


if __name__ == "__main__":
    unittest.main()
