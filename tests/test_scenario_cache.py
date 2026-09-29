"""Prompt-prefix KV reuse must never cross a scenario boundary."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

import httpx

from thread_agent.fdb3 import LocalPlanner


class ScenarioCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.owner = Path(self.tmp.name) / "owner"
        self.env = {"THREAD_FDB3_PROMPT_CACHE": "1", "THREAD_FDB3_CACHE_OWNER_FILE": str(self.owner)}
        self.saved = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)
        self.calls = []

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def planner(self, slots_ok=True):
        def handler(request):
            self.calls.append((request.method, request.url.path, request.url.query.decode()))
            if not slots_ok:
                return httpx.Response(501, json={"error": "slots disabled"})
            if request.method == "GET":
                return httpx.Response(200, json=[{"id": 0}, {"id": 1}])
            return httpx.Response(200, json={"id_slot": 0})
        planner = LocalPlanner("http://127.0.0.1:8098/v1", "local")
        planner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return planner

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_new_scenario_erases_every_slot_once(self):
        first = self.planner()
        self.assertTrue(self.run_async(first._scenario_cache()))
        erased = [call for call in self.calls if call[0] == "POST"]
        self.assertEqual(erased, [("POST", "/slots/0", "action=erase"), ("POST", "/slots/1", "action=erase")])
        self.calls.clear()
        self.assertTrue(self.run_async(first._scenario_cache()))
        self.assertEqual(self.calls, [], "same scenario keeps its own prefix")
        second = self.planner()
        self.assertTrue(self.run_async(second._scenario_cache()))
        self.assertEqual(len([call for call in self.calls if call[0] == "POST"]), 2)
        # The earlier scenario's late request must erase again, not reuse the new one.
        self.calls.clear()
        self.assertTrue(self.run_async(first._scenario_cache()))
        self.assertEqual(len([call for call in self.calls if call[0] == "POST"]), 2)

    def test_unconfirmed_erase_runs_uncached(self):
        planner = self.planner(slots_ok=False)
        self.assertFalse(self.run_async(planner._scenario_cache()))
        self.assertFalse(self.owner.exists())

    def test_cache_off_never_touches_server(self):
        os.environ["THREAD_FDB3_PROMPT_CACHE"] = "0"
        planner = self.planner()
        self.assertFalse(self.run_async(planner._scenario_cache()))
        self.assertEqual(self.calls, [])

    def test_follow_up_is_independent_of_guidance(self):
        for guidance, follow_up, expected in [("1", "1", 2), ("1", "0", 0), ("2", "0", 0), ("2", None, 2), ("1", None, 0)]:
            os.environ["THREAD_FDB3_PLANNER_GUIDANCE"] = guidance
            if follow_up is None:
                os.environ.pop("THREAD_FDB3_FOLLOW_UP", None)
            else:
                os.environ["THREAD_FDB3_FOLLOW_UP"] = follow_up
            self.assertEqual(LocalPlanner("http://127.0.0.1:8098/v1", "m").follow_up_rounds, expected)
        os.environ.pop("THREAD_FDB3_FOLLOW_UP", None)
        os.environ.pop("THREAD_FDB3_PLANNER_GUIDANCE", None)


if __name__ == "__main__":
    unittest.main()
