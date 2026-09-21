"""Optional real image embeddings, computed from current media with a hard budget.

API contract: https://ai.google.dev/gemini-api/docs/embeddings#embedding-images
No fixture vectors, generation prompts, retries, or cross-session media cache.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import math

import httpx


EMBEDDING_MODEL = "gemini-embedding-2"
DIMENSIONS = 768


async def embed_image(client, api_key: str, inline_data: dict, *, timeout: float = 3.0,
                      pending_tasks: set | None = None) -> dict:
    """Return real values or None, plus redacted provenance; cancellation propagates.

The caller supplies media already validated by MediaLoader. Register requests in
its owned task set so close() can cancel even an uncooperative transport. A late
response never becomes an embedding after the deadline or caller cancellation.
"""
    loop = asyncio.get_running_loop()
    started = loop.time()
    evidence = {"model": EMBEDDING_MODEL, "status": "invalid_input"}
    result = {"values": None, "evidence": evidence}
    request_task = None
    try:
        if not isinstance(inline_data, dict) or inline_data.get("mimeType") not in ("image/png", "image/jpeg"):
            evidence["status"] = "unsupported_media"
            return result
        encoded = inline_data.get("data")
        if not isinstance(encoded, str) or not encoded or len(encoded) > 11_000_000:
            return result
        if not isinstance(api_key, str) or not api_key:
            evidence["status"] = "unconfigured"
            return result
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 5:
            return result
        raw = await asyncio.wait_for(
            asyncio.to_thread(base64.b64decode, encoded, validate=True), timeout=timeout)
        if not raw:
            return result
        evidence.update(input_sha256=hashlib.sha256(raw).hexdigest(), input_bytes=len(raw),
                        mime_type=inline_data["mimeType"])
        remaining = timeout - (loop.time() - started)
        if remaining <= 0:
            evidence["status"] = "timeout"
            return result
        request_task = asyncio.create_task(client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:embedContent",
            headers={"x-goog-api-key": api_key},
            json={"content": {"parts": [{"inline_data": {
                "mime_type": inline_data["mimeType"], "data": encoded}}]},
                  "output_dimensionality": DIMENSIONS}, timeout=remaining))
        if pending_tasks is not None:
            pending_tasks.add(request_task)

        def finished(task):
            if pending_tasks is not None:
                pending_tasks.discard(task)
            if not task.cancelled():
                task.exception()

        request_task.add_done_callback(finished)
        done, _ = await asyncio.wait({request_task}, timeout=remaining)
        if not done or loop.time() - started >= timeout:
            request_task.cancel()
            evidence["status"] = "timeout"
            return result
        response = request_task.result()
        evidence["http_status"] = response.status_code
        if response.status_code != 200:
            evidence["status"] = "provider_error"
            return result
        payload = response.json()
        embedding = payload.get("embedding") if isinstance(payload, dict) else None
        values = embedding.get("values") if isinstance(embedding, dict) else None
        if not isinstance(values, list) or len(values) != DIMENSIONS:
            evidence["status"] = "invalid_vector"
            return result
        if any(type(v) not in (int, float) for v in values):
            evidence["status"] = "invalid_vector"
            return result
        values = [float(v) for v in values]
        norm = math.sqrt(math.fsum(v * v for v in values))
        if not all(math.isfinite(v) for v in values) or not math.isfinite(norm) or norm <= 0:
            evidence["status"] = "invalid_vector"
            return result
        packed = json.dumps(values, separators=(",", ":"), allow_nan=False).encode()
        evidence.update(status="success", dimensions=len(values), norm=norm,
                        vector_sha256=hashlib.sha256(packed).hexdigest())
        result["values"] = values
        return result
    except asyncio.CancelledError:
        if request_task is not None:
            request_task.cancel()
        evidence["status"] = "cancelled"
        raise
    except asyncio.TimeoutError:
        evidence["status"] = "timeout"
        return result
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError, binascii.Error):
        evidence["status"] = "unavailable"
        return result
    finally:
        evidence["elapsed_ms"] = round((loop.time() - started) * 1000, 2)
