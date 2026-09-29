"""Two-queue boundary for local Theme 5 development, not the official kit.

One adapter owns one session. Supply fresh scenario manifests and a planner. None
on input means EOF; None on output means cleanup completed. The injected clock
schedules agent/tool deadlines. The 120-second wall cap is independent.
"""
import asyncio
import json

from .engine import Session
from .media import validate_media
from .protocol import InputEvent, Manifest


def parse_event(raw):
    if isinstance(raw, str):
        if len(raw) > 9_000_000:
            raise ValueError('Input event exceeds the transport limit.')
        def invalid_constant(value):
            raise ValueError('Nonfinite JSON numbers are not permitted.')
        raw = json.loads(raw, parse_constant=invalid_constant)
    json.dumps(raw, allow_nan=False)
    event = InputEvent.model_validate(raw)
    if event.type == 'tool_result':
        if (not isinstance(event.data.get('call_id'), str)
                or not isinstance(event.data.get('result'), dict)):
            raise ValueError('Tool results require a call_id and an object result.')
    if event.type == 'manifest':
        Manifest.model_validate(event.data.get('manifest')).check()
    validate_media(event)
    return event


class QueueAdapter:
    def __init__(self, planner, *, clock=None, manifests=None, timezone='Asia/Kolkata', date=None):
        checked = {}
        for raw in manifests or []:
            manifest = (raw if isinstance(raw, Manifest) else Manifest.model_validate(raw)).check()
            if manifest.id in checked:
                raise ValueError('Duplicate scenario manifest ID.')
            checked[manifest.id] = manifest
        self.session = Session(planner, clock=clock, evaluation=True, external=True,
                               manifests=checked, timezone=timezone, date=date)
        self.events = asyncio.Queue(maxsize=128)
        self.actions = self.session.outbox

    async def _consume(self):
        while True:
            raw = await self.events.get()
            try:
                if raw is None:
                    break
                try:
                    await self.session.accept(parse_event(raw))
                except (ValueError, KeyError, TypeError) as exc:
                    self.session.emit('protocol_error', 'Invalid input event rejected.', error_type=type(exc).__name__)
            finally:
                self.events.task_done()
        await self.session.inputs.join()
        if self.session.input_floor_held or self.session.transcript_chunks:
            self.session.stop('pause')
        while self.session.tasks:
            await asyncio.gather(*list(self.session.tasks), return_exceptions=True)

    async def run(self, wall_timeout=120):
        if not 0 < wall_timeout <= 120:
            raise ValueError('Scenario wall timeout must be in (0, 120] seconds.')
        try:
            await asyncio.wait_for(self._consume(), wall_timeout)
        except asyncio.TimeoutError:
            self.session.stop('end')
            self.session.emit('scenario_timeout', 'Scenario wall-clock limit reached. Unconfirmed actions remain unresolved.', state_snapshot=self.session.summary())
        finally:
            await self.session.close()
            self.session.emit('session_closed', 'Input stream closed; session resources released.', state_snapshot=self.session.summary())
            self.actions.put_nowait(None)
