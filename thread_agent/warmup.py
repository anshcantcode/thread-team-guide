"""Bounded pre-scenario setup check; prints no credentials and retains no session."""
import argparse
import asyncio
import json
import platform
import time

from .planner import ModelPlanner, settings


async def warmup(check_provider=False):
    started = time.monotonic()
    planner = ModelPlanner()
    try:
        provider = await asyncio.wait_for(planner.health(), 300) if check_provider else None
        ready = provider['ready'] if provider else True
        return {'type': 'warmup', 'ready': ready, 'python': platform.python_version(),
                'provider': settings()['provider'], 'model': settings()['model'],
                'provider_checked': check_provider, 'elapsed_ms': round((time.monotonic()-started)*1000, 2),
                'budget_seconds': 300, 'session_state_retained': False,
                **({'message': provider['message']} if provider else {})}
    except asyncio.TimeoutError:
        return {'type': 'warmup', 'ready': False, 'reason': 'Setup exceeded the 300-second budget.'}
    finally:
        await planner.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-provider', action='store_true', help='Make a real provider health request, using quota.')
    result = asyncio.run(warmup(parser.parse_args().check_provider))
    print(json.dumps(result, allow_nan=False))
    raise SystemExit(0 if result['ready'] else 1)
