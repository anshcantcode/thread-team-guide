import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import participant.agent as participant_agent
from participant.agent import ParticipantAgent


class Clock:
    def __init__(self, value=100):
        self.value = value

    def __call__(self):
        return self.value


class NoopPlanner:
    async def setup(self):
        pass

    async def close(self):
        pass


class WriteDeadlineRaceTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, clock, delay_range_ms=(1000, 1000)):
        text = "Create a note saying hello. Then create another note saying extra."
        agent = ParticipantAgent(asyncio.Queue(), asyncio.Queue(), planner=NoopPlanner())
        agent.tools = {"create_note": {
            "kind": "state_modifying", "description": "Create a note.",
            "args": {"text": {"type": "string", "required": True}},
            "delay_range_ms": list(delay_range_ms),
        }}
        agent.messages = [{"event_type": "user_speech_chunk", "payload": {"text": text}, "revision": 0}]
        step = {"api_name": "create_note", "args": {"text": "hello"},
                "authorization": {"quote": "Create a note saying hello"},
                "after_result": {"api_name": "create_note", "args": {"text": "extra"},
                                 "authorization": {"quote": "create another note saying extra"}}}
        with patch.object(participant_agent, "time", SimpleNamespace(monotonic=clock)):
            self.assertTrue(agent._dispatch(step))
        call = agent.out_queue.get_nowait()
        self.assertEqual(call["action"], "tool_call")
        return agent, call

    def observe_loop(self, agent, clock, call):
        sweeps, results = asyncio.Queue(), asyncio.Queue()
        expire, result = agent._expire_writes, agent._result

        def observed_expire():
            expire()
            sweeps.put_nowait((clock.value, agent.operations[call["payload"]["call_id"]]["status"]))

        def observed_result(payload):
            result(payload)
            results.put_nowait(None)

        agent._expire_writes = observed_expire
        agent._result = observed_result
        return sweeps, results

    async def wait_for(self, queue):
        return await asyncio.wait_for(queue.get(), 1)

    async def stop(self, agent, task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(agent._closed)

    def late_results(self, agent, call):
        for receipt_id in ("LATE-FIRST", "LATE-SECOND"):
            agent.in_queue.put_nowait({"event_type": "tool_result", "payload": {
                **call["payload"], "status": "success",
                "result": {"status": "success", "receipt_id": receipt_id}}})

    def assert_reconciled_without_continuation(self, agent, call):
        operation = agent.operations[call["payload"]["call_id"]]
        self.assertEqual(operation["status"], "success")
        self.assertEqual(operation["result"]["receipt_id"], "LATE-FIRST")
        self.assertTrue(operation["continuation_retired"])
        self.assertEqual(agent.snapshot()["slots"]["receipt_id"], "LATE-FIRST")
        self.assertEqual(len(agent.operations), 1)
        self.assertEqual(len(agent.tool_results), 1)
        output = [agent.out_queue.get_nowait() for _ in range(agent.out_queue.qsize())]
        self.assertEqual([item["action"] for item in output], ["final_response"])
        self.assertIn("could not confirm", output[0]["payload"]["text"])
        self.assertNotIn("LATE-FIRST", output[0]["payload"]["text"])

    async def test_late_queued_results_expire_before_reconciliation(self):
        clock = Clock()
        agent, call = self.make_agent(clock)
        deadline = agent.operations[call["payload"]["call_id"]]["deadline"]
        sweeps, results = self.observe_loop(agent, clock, call)
        with patch.object(participant_agent, "time", SimpleNamespace(monotonic=clock)):
            task = asyncio.create_task(agent.run())
            try:
                agent.in_queue.put_nowait({"event_type": "loop_tick", "payload": {}})
                self.assertEqual((await self.wait_for(sweeps))[1], "pending")
                clock.value = deadline + 0.01
                self.late_results(agent, call)
                await self.wait_for(results)
                await self.wait_for(results)
            finally:
                await self.stop(agent, task)
        self.assert_reconciled_without_continuation(agent, call)

    async def test_expiry_sweep_before_queued_result_has_same_terminal_behavior(self):
        clock = Clock()
        agent, call = self.make_agent(clock)
        deadline = agent.operations[call["payload"]["call_id"]]["deadline"]
        sweeps, results = self.observe_loop(agent, clock, call)
        with patch.object(participant_agent, "time", SimpleNamespace(monotonic=clock)):
            task = asyncio.create_task(agent.run())
            try:
                agent.in_queue.put_nowait({"event_type": "loop_tick", "payload": {}})
                self.assertEqual((await self.wait_for(sweeps))[1], "pending")
                clock.value = deadline + 0.01
                agent.in_queue.put_nowait({"event_type": "loop_tick", "payload": {}})
                self.assertEqual((await self.wait_for(sweeps))[1], "unknown")
                self.late_results(agent, call)
                await self.wait_for(results)
                await self.wait_for(results)
            finally:
                await self.stop(agent, task)
        self.assert_reconciled_without_continuation(agent, call)

    async def test_scenario_end_shortened_deadline_expires_before_queued_result(self):
        clock = Clock()
        agent, call = self.make_agent(clock, (30000, 30000))
        operation = agent.operations[call["payload"]["call_id"]]
        original_deadline = operation["deadline"]
        sweeps, results = self.observe_loop(agent, clock, call)
        with patch.object(participant_agent, "time", SimpleNamespace(monotonic=clock)):
            task = asyncio.create_task(agent.run())
            try:
                agent.in_queue.put_nowait({"event_type": "scenario_end", "payload": {}})
                self.assertEqual((await self.wait_for(sweeps))[1], "pending")
                self.assertLess(operation["deadline"], original_deadline)
                clock.value = operation["deadline"] + 0.01
                self.late_results(agent, call)
                await self.wait_for(results)
                await self.wait_for(results)
            finally:
                await self.stop(agent, task)
        self.assert_reconciled_without_continuation(agent, call)


if __name__ == "__main__":
    unittest.main()
