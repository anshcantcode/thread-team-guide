"""Start the shared controller inside the Android app's private process.

The native client supplies memory-only credentials and an unguessable local token.
No laptop, shell process, downloaded code, external bind address or bundled .env.
"""
import json
import os
from pathlib import Path
import threading
import time

_server = None
_thread = None
_error = ''


def record_voice_metrics(metrics):
    """Content-free counters for release/device diagnostics, never audio or text."""
    if os.environ.get('THREAD_EMBEDDED') == 'android':
        try: print('THREAD_VOICE_METRICS ' + json.dumps(metrics, separators=(',', ':')), flush=True)
        except OSError: pass


def configure(raw):
    config = json.loads(raw)
    if not isinstance(config, dict): raise ValueError('Expected phone configuration.')
    defaults = {'THREAD_API_KEY': '', 'THREAD_MODEL': 'gemini-3.5-flash-lite',
                'THREAD_LIVE_MODEL': 'gemini-3.1-flash-live-preview',
                'THREAD_TIMEZONE': 'Asia/Kolkata', 'THREAD_LIVE_SEARCH': 'false'}
    for name, default in defaults.items():
        value = config.get(name, default)
        if not isinstance(value, str) or len(value) > 256 or '\n' in value or '\r' in value:
            raise ValueError('Invalid phone configuration.')
    for name, default in defaults.items(): os.environ[name] = config.get(name, default)
    os.environ['THREAD_PROVIDER'] = 'gemini'


def start(files_dir, config, token):
    global _server, _thread, _error
    configure(config)
    if _thread and _thread.is_alive() and _server and _server.started: return True
    if not isinstance(token, str) or len(token) < 32: raise ValueError('Missing local client credential.')
    data = Path(files_dir) / 'backend'
    data.mkdir(parents=True, exist_ok=True)
    os.environ.update(THREAD_EMBEDDED='android', THREAD_DATA_DIR=str(data), THREAD_LOCAL_TOKEN=token,
                      THREAD_SPOTIFY_REDIRECT='http://127.0.0.1:8767/api/spotify/callback')
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    import uvicorn
    from .server import app
    _error = ''
    _server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8767, loop='asyncio',
        http='h11', ws='websockets', log_config=None, access_log=False, proxy_headers=False,
        log_level='warning', timeout_graceful_shutdown=2))

    def serve():
        global _error
        try: _server.run()
        except BaseException as error: _error = type(error).__name__

    _thread = threading.Thread(target=serve, name='THREAD local backend', daemon=True)
    _thread.start()
    until = time.monotonic() + 20
    while not _server.started:
        if _error or not _thread.is_alive(): raise RuntimeError('The phone backend could not start: ' + (_error or 'server stopped'))
        if time.monotonic() >= until: raise TimeoutError('The phone backend did not become ready.')
        time.sleep(.025)
    return True
