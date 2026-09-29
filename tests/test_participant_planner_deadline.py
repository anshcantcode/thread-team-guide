"""A completed future cannot make an expired planning budget valid again."""
import asyncio
import time
import unittest

from participant.planner import Planner


class PlannerDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.planner = Planner()

    async def asyncTearDown(self):
        await self.planner.close()

    async def test_event_loop_stall_cannot_admit_a_result_after_its_deadline(self):
        async def blocked_then_complete():
            # Deterministically put both completion and timer callbacks behind
            # a blocking operation, as can happen in a provider adapter.
            time.sleep(.02)
            return {"proposal": "must not be admitted"}

        with self.assertRaises(asyncio.TimeoutError):
            await self.planner._bounded(blocked_then_complete(), .001)

    async def test_a_result_inside_its_budget_is_still_returned(self):
        async def immediate():
            return {"proposal": "within budget"}

        self.assertEqual(await self.planner._bounded(immediate(), 1), {"proposal": "within budget"})


if __name__ == "__main__":
    unittest.main()
