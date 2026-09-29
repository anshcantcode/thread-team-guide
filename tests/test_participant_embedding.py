"""Synthetic transport/ownership tests, not real embedding quality evidence."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import threading
import unittest

import httpx

from participant.embedding import DIMENSIONS, EMBEDDING_MODEL, embed_image


MEDIA_BYTES = b"synthetic already-validated image bytes for transport tests"
MEDIA = {"mimeType": "image/png", "data": base64.b64encode(MEDIA_BYTES).decode()}
VECTOR = [0.125] * DIMENSIONS


class EmbeddingTests(unittest.IsolatedAsyncioTestCase):
    async def run_with(self, handler, **kwargs):
        pending = set()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await embed_image(client, "synthetic-test-key", MEDIA, pending_tasks=pending, **kwargs)
            await asyncio.sleep(0)
            self.assertFalse(pending)
        return result

    async def test_real_response_bytes_and_provenance(self):
        async def handler(request):
            self.assertEqual(request.url.path, f"/v1beta/models/{EMBEDDING_MODEL}:embedContent")
            body = json.loads(request.content)
            self.assertEqual(base64.b64decode(body["content"]["parts"][0]["inline_data"]["data"]), MEDIA_BYTES)
            self.assertEqual(body["output_dimensionality"], DIMENSIONS)
            return httpx.Response(200, json={"embedding": {"values": VECTOR}})
        result = await self.run_with(handler)
        self.assertEqual(result["values"], VECTOR)
        evidence = result["evidence"]
        self.assertEqual(evidence["status"], "success")
        self.assertEqual(evidence["input_sha256"], hashlib.sha256(MEDIA_BYTES).hexdigest())
        self.assertEqual(evidence["vector_sha256"], hashlib.sha256(json.dumps(VECTOR, separators=(",", ":")).encode()).hexdigest())
        self.assertNotIn("synthetic-test-key", json.dumps(result))

    async def test_invalid_vectors_do_not_gain_bonus(self):
        for values in ([], [1], [0] * DIMENSIONS, [True] * DIMENSIONS, ["1"] * DIMENSIONS):
            with self.subTest(value=repr(values)[:20]):
                result = await self.run_with(lambda _: httpx.Response(200, json={"embedding": {"values": values}}))
                self.assertIsNone(result["values"])
                self.assertNotEqual(result["evidence"]["status"], "success")
        result = await self.run_with(lambda _: httpx.Response(200, content='{"embedding":{"values":[' + ','.join(['NaN'] * DIMENSIONS) + ']}}'))
        self.assertIsNone(result["values"])

    async def test_provider_failure_is_optional_and_not_retried(self):
        count = 0
        def handler(_):
            nonlocal count
            count += 1
            return httpx.Response(429, json={"error": {"message": "private provider details"}})
        result = await self.run_with(handler)
        self.assertEqual(count, 1)
        self.assertIsNone(result["values"])
        self.assertNotIn("private provider details", json.dumps(result))

    async def test_malformed_success_body_is_not_an_embedding(self):
        for body in ([], "invalid", {"embedding": []}, {}, {"embedding": {"values": "invalid"}}):
            with self.subTest(body=body):
                result = await self.run_with(lambda _: httpx.Response(200, json=body))
                self.assertIsNone(result["values"])
                self.assertEqual(result["evidence"]["status"], "invalid_vector")

    async def test_unsupported_media_makes_no_request(self):
        def forbidden(_):
            self.fail("Unsupported media must not reach the API")
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            result = await embed_image(client, "synthetic-test-key", {**MEDIA, "mimeType": "image/webp"})
        self.assertIsNone(result["values"])

    async def test_deadline_rejects_transport_that_swallows_cancellation(self):
        pending = set()
        async def stubborn(_):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                await asyncio.sleep(.01)
            return httpx.Response(200, json={"embedding": {"values": VECTOR}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(stubborn)) as client:
            started = asyncio.get_running_loop().time()
            result = await embed_image(client, "synthetic-test-key", MEDIA, timeout=.03, pending_tasks=pending)
            self.assertLess(asyncio.get_running_loop().time() - started, .3)
            self.assertIsNone(result["values"])
            self.assertEqual(result["evidence"]["status"], "timeout")
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.sleep(0)
            self.assertFalse(pending)

    async def test_caller_cancellation_cannot_return_late_vector(self):
        entered = asyncio.Event()
        pending = set()
        async def stubborn(_):
            entered.set()
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return httpx.Response(200, json={"embedding": {"values": VECTOR}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(stubborn)) as client:
            task = asyncio.create_task(embed_image(client, "synthetic-test-key", MEDIA, pending_tasks=pending))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.sleep(0)
            self.assertFalse(pending)

    async def test_saturated_decoder_executor_still_obeys_budget(self):
        entered, release = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_running_loop()
        loop.set_default_executor(executor)

        def occupy():
            entered.set()
            release.wait(.5)

        blocker = asyncio.create_task(asyncio.to_thread(occupy))
        while not entered.is_set():
            await asyncio.sleep(.001)

        def forbidden(_):
            self.fail("Expired preparation must not call the provider")

        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
                started = loop.time()
                result = await embed_image(client, "synthetic-test-key", MEDIA, timeout=.03)
                self.assertLess(loop.time() - started, .15)
                self.assertEqual(result["evidence"]["status"], "timeout")
                self.assertIsNone(result["values"])
        finally:
            release.set()
            await blocker
            executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
