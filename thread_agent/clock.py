"""One injectable timeline for controller deadlines and deterministic local replay."""
import asyncio
from datetime import datetime, timedelta, timezone
import heapq
import itertools
import math
import time


class RealClock:
    deterministic = False

    def now(self):
        return time.perf_counter()

    def utcnow(self):
        return datetime.now(timezone.utc)

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class VirtualClock:
    """Driven by the harness, never by model or tool code. Seconds are monotonic."""
    deterministic = True

    def __init__(self, epoch=None):
        self.epoch = epoch or datetime(2026, 9, 14, tzinfo=timezone.utc)
        if self.epoch.tzinfo is None:
            raise ValueError('The virtual epoch must include a timezone.')
        self.time = 0.0
        self.waiters = []
        self.sequence = itertools.count()

    def now(self):
        return self.time

    def utcnow(self):
        return self.epoch + timedelta(seconds=self.time)

    async def sleep(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('A delay must be finite and nonnegative.')
        if seconds == 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self.waiters, (self.time + seconds, next(self.sequence), future))
        await future

    def next_deadline(self):
        while self.waiters and self.waiters[0][2].done():
            heapq.heappop(self.waiters)
        return self.waiters[0][0] if self.waiters else None

    def advance_to(self, seconds):
        if not math.isfinite(seconds) or seconds < self.time:
            raise ValueError('The virtual clock cannot move backwards or to a nonfinite time.')
        self.time = seconds
        while self.waiters and self.waiters[0][0] <= seconds:
            _, _, future = heapq.heappop(self.waiters)
            if not future.done():
                future.set_result(None)
