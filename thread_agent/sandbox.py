"""An asynchronous service with its own ledger, independent of the assistant's intent."""
import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from .fixtures import lookup
from .capabilities import BUILTINS, Notebook, safe_execute
from .clock import RealClock


class Sandbox:
    def __init__(self, *, clock=None, persistent=True):
        self.clock = clock or RealClock()
        self.persistent = persistent
        self._notebook = None
        self._storage = None
        self.config = {'read_delay': 2.2, 'write_delay': 2.0, 'prepare_delay': 0.8,
                       'timeout': 3.5, 'late_reads': False, 'duplicate_result': False,
                       'fail_next_read': False, 'action_mode': 'normal'}
        self.ledger = {}
        self.submissions = []
        self.creations = []
        self.last_results = {}

    @property
    def notebook(self):
        if self._notebook is None:
            if not self.persistent:
                self._storage = TemporaryDirectory(prefix='thread-session-')
            self._notebook = Notebook(Path(self._storage.name) / 'notebook.sqlite3' if self._storage else None)
        return self._notebook

    @notebook.setter
    def notebook(self, value):
        self._notebook = value

    def close(self):
        if self._storage:
            self._storage.cleanup()
            self._storage = None
        self._notebook = None

    async def read(self, domain, args):
        fail = self.config['fail_next_read']
        self.config['fail_next_read'] = False
        await self.clock.sleep(self.config['read_delay'])
        if fail:
            return {'status': 'failed', 'error': 'Injected sandbox search failure. Availability was not established.'}
        if domain in BUILTINS:
            return await safe_execute(domain, args, notebook=self.notebook)
        return {'status': 'completed', 'provenance': 'demo', **lookup(domain, args)}

    async def create(self, operation_id, domain, args):
        if operation_id in self.ledger:
            # Service-side idempotency is independent of the agent's delivery deduplication.
            return deepcopy(self.ledger[operation_id])
        record = {'status': 'pending', 'operation_id': operation_id, 'domain': domain, 'arguments': deepcopy(args)}
        self.ledger[operation_id] = record
        self.submissions.append(operation_id)
        if domain == 'notes':
            try:
                result = self.notebook.save(operation_id, args)
            except Exception:
                # A write may have committed before a storage error. Reconcile, never assume no effect.
                result = {'status': 'unknown', 'operation_id': operation_id}
            record.update(result)
            if result['status'] == 'completed': self.creations.append(operation_id)
            return deepcopy(record)
        mode = self.config['action_mode']
        record['mode'] = mode
        await self.clock.sleep(0.15 if mode in ('delayed', 'too_late', 'unverifiable') else self.config['write_delay'])
        if record['status'] == 'pending':
            record.update(status='completed', reference=f'SIM-{domain[:3].upper()}-{operation_id[-8:].upper()}')
            self.creations.append(operation_id)
        if mode in ('delayed', 'unverifiable'):
            await self.clock.sleep(self.config['timeout'] + 4)
        return deepcopy(record)

    async def cancel(self, operation_id):
        await self.clock.sleep(0.25)
        record = self.ledger.get(operation_id)
        if record and record.get('domain') == 'notes':
            result = self.notebook.cancel(operation_id)
            record.update(result)
            return result
        if record is None:
            return {'status': 'not_performed', 'operation_id': operation_id}
        if record.get('mode') in ('too_late', 'unverifiable'):
            return {'status': 'declined', 'operation_id': operation_id,
                    'known_status': record['status'] if record['mode'] == 'too_late' else 'unknown',
                    'reference': record.get('reference') if record['mode'] == 'too_late' else None}
        if record['status'] == 'pending':
            record['status'] = 'not_performed'
        elif record['status'] == 'completed':
            record['status'] = 'cancelled'
        return deepcopy(record)

    async def status(self, operation_id):
        await self.clock.sleep(0.15)
        record = self.ledger.get(operation_id)
        if record and record.get('domain') == 'notes': return self.notebook.status(operation_id)
        if record and record.get('mode') == 'unverifiable':
            return {'status': 'unknown', 'operation_id': operation_id}
        return deepcopy(record) if record else {'status': 'not_performed', 'operation_id': operation_id}
