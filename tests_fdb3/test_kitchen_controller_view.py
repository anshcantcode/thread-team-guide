"""The Kitchen page's controller view is a read-only, display-safe mirror of real controller events."""
import asyncio
import unittest

from thread_agent.fdb3_client import controller_update, forward_controller


class ControllerViewTests(unittest.TestCase):
    def test_stages_and_safe_fields(self):
        self.assertEqual(controller_update({"action": "tool_call", "payload": {
            "call_id": "call-1", "api_name": "add_checklist_item", "args": {"text": "wash the spinach"}}}),
            {"type": "controller", "stage": "sending", "api_name": "add_checklist_item", "call_id": "call-1",
             "args": {"text": "wash the spinach"}})
        self.assertEqual(controller_update({"action": "cancel_tool", "payload": {"call_id": "call-1"}})["stage"], "withdrawn")
        held = controller_update({"action": "clarification_request", "payload": {
            "text": "Please explicitly confirm.", "gate": {"api_name": "add_checklist_item", "reasons": ["internal"]}}})
        self.assertEqual(held["stage"], "held")
        self.assertNotIn("gate", held)  # gate reasons stay on the host
        self.assertEqual(controller_update({"action": "clarification_request", "payload": {"text": "Which item?"}})["stage"], "asked")
        self.assertIsNone(controller_update({"action": "some_internal_event", "payload": {}}))
        self.assertIsNone(controller_update("not an event"))

    def test_forwarder_mirrors_new_events_until_closed(self):
        class Bridge: events = []
        bridge, sent, state = Bridge(), [], {"open": True}
        async def send(update):
            sent.append(update)
            if len(sent) == 2:
                state["open"] = False
        async def run():
            bridge.events.extend([{"action": "tool_call", "payload": {"api_name": "add_checklist_item", "args": {"text": "a"}}},
                                  {"action": "internal", "payload": {}},
                                  {"action": "final_response", "payload": {"text": "Added."}}])
            await asyncio.wait_for(forward_controller(bridge, send, lambda: state["open"], interval=0.01), 2)
        asyncio.run(run())
        self.assertEqual([update["stage"] for update in sent], ["sending", "answered"])


if __name__ == "__main__":
    unittest.main()
