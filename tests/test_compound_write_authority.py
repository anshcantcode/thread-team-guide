"""Independent regression for compound string values, unrelated to FDB items."""
import asyncio
import unittest
from participant.agent import ParticipantAgent


class CompoundAuthorityTests(unittest.TestCase):
    def dispatches(self, command, value):
        agent = ParticipantAgent(asyncio.Queue(),asyncio.Queue())
        agent.messages = [{"event_type":"user_speech_chunk","payload":{"text":command}}]
        agent.tools["set_profile"] = {"kind":"state_modifying","description":"Set a profile for a customer.",
            "args":{"profile":{"type":"string","required":True},"customer":{"type":"string","required":True}}}
        agent._dispatch({"api_name":"set_profile","args":{"profile":value,"customer":"Elena"},
                         "authorization":{"quote":command,"message_index":0}})
        return any(agent.out_queue.get_nowait()["action"] == "tool_call" for _ in range(agent.out_queue.qsize()))

    def test_truncated_compound_rejected(self):
        self.assertFalse(self.dispatches("Set profile slow and steady for Elena.","slow"))

    def test_complete_compound_and_simple_values_allowed(self):
        self.assertTrue(self.dispatches("Set profile slow and steady for Elena.","slow and steady"))
        self.assertTrue(self.dispatches("Set profile steady for Elena.","steady"))

    def test_explicit_other_field_is_not_part_of_compound(self):
        self.assertTrue(self.dispatches("Set profile=steady and customer=Elena.","steady"))


if __name__ == "__main__": unittest.main()
