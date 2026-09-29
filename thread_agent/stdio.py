"""JSONL streaming entry point for the provisional thread.v1 adapter.

stdin: timestamped InputEvent objects, including tool_result and manifest.
stdout: explicit tool_call/cancel/speak/clarify/final/snapshot events.
No organiser compatibility is claimed until the actual kit is available.
"""
import argparse
import asyncio
import json
import sys
import threading

from .adapter import QueueAdapter
from .fixtures import PACKS
from .planner import ModelPlanner, settings
from .protocol import InputEvent


async def run(sandbox=False, wall_timeout=120):
    planner=ModelPlanner()
    adapter=QueueAdapter(planner, timezone=settings()['timezone'], manifests=list(PACKS.values()) if sandbox else [])
    adapter.session.external=not sandbox
    loop=asyncio.get_running_loop()
    def input_lines():
        while True:
            line=sys.stdin.readline()
            if loop.is_closed(): return
            try:
                asyncio.run_coroutine_threadsafe(adapter.events.put(line if line else None),loop).result()
            except Exception:
                return
            if not line: return
    async def output():
        while True:
            event=await adapter.actions.get()
            try:
                if event is None: return
                print(json.dumps(event,ensure_ascii=True,allow_nan=False),flush=True)
            finally:
                adapter.actions.task_done()
    # A daemon reader cannot prevent the scenario wall cap from terminating a
    # process whose peer leaves stdin open. Default-executor readline can.
    reader=threading.Thread(target=input_lines,daemon=True)
    reader.start()
    writer=asyncio.create_task(output())
    try:
        await adapter.run(wall_timeout)
        await writer
    finally:
        writer.cancel()
        await asyncio.gather(writer,return_exceptions=True)
        await planner.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sandbox',action='store_true',help='Run built-in sandbox services instead of waiting for externally supplied tool results.')
    parser.add_argument('--wall-timeout', type=float, default=120)
    args=parser.parse_args()
    asyncio.run(run(args.sandbox,args.wall_timeout))
