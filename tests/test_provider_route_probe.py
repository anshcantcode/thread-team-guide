"""One offline check for the experimental route's request and response boundary."""

import json
import unittest

import httpx

from scripts.provider_route_probe import Route


class RouteProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_gemma_direct_transport(self):
        def respond(request):
            self.assertEqual(request.url.path, "/v1beta/models/gemma-4-26b-a4b-it:generateContent")
            self.assertEqual(request.headers["x-goog-api-key"], "gemma-key")
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

        route = Route("gemma", "gemma-key", "https://generativelanguage.googleapis.com/v1beta", 1)
        await route.client.aclose()
        route.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com/test",
                                json={"contents": [{"parts": [{"text": "hello"}]}]})
        response = await route.handle_async_request(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(route.rows[0]["status"], 200)
        self.assertNotIn("gemma-key", json.dumps(route.rows))
        await route.client.aclose()

    async def test_openrouter_free_schema_boundary(self):
        def respond(request):
            self.assertEqual(request.headers["authorization"], "Bearer openrouter-key")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "qwen/qwen3.8-27b:free")
            self.assertEqual(body["reasoning"], {"enabled": False})
            self.assertTrue(body["provider"]["require_parameters"])
            self.assertEqual(body["response_format"]["type"], "json_schema")
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"content": '{"response":"Done."}'}}]})

        route = Route("openrouter", "openrouter-key", "https://openrouter.ai/api/v1", 2,
                      asr_key="groq-key")
        await route.client.aclose()
        route.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        source = {"systemInstruction": {"parts": [{"text": "Return JSON."}]},
                  "contents": [{"parts": [{"text": "hello"}]}],
                  "generationConfig": {"maxOutputTokens": 100, "responseJsonSchema": {
                      "type": "object", "properties": {"response": {"type": "string"}}}}}
        response = await route.handle_async_request(httpx.Request(
            "POST", "https://generativelanguage.googleapis.com/test", json=source))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])["response"], "Done.")
        self.assertEqual(route.asr_key, "groq-key")
        await route.client.aclose()

    async def test_groq_text_and_audio_conversion(self):
        calls = []

        def respond(request):
            calls.append(request)
            if request.url.path.endswith("/audio/transcriptions"):
                return httpx.Response(200, json={"text": "I said Boston.", "segments": []})
            body = json.loads(request.content)
            assert body["model"] == "qwen/qwen3.8-27b"
            assert body["reasoning_effort"] == "none"
            assert body["response_format"]["type"] == "json_schema"
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"content": '{"intent":"help","slots":{},"tool_calls":[],"observations":[],"clarification":null,"response":"Done."}'}}]})

        route = Route("groq", "fake-key", "https://api.groq.com/openai/v1", 3)
        await route.client.aclose()
        route.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        source = {"systemInstruction": {"parts": [{"text": "Return JSON."}]},
                  "contents": [{"parts": [{"text": "hello"}]}],
                  "generationConfig": {"maxOutputTokens": 100, "responseJsonSchema": {
                      "type": "object", "properties": {"response": {"type": "string"}}}}}
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com/test", json=source)
        response = await route.handle_async_request(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])["response"], "Done.")
        self.assertEqual(route.rows[0]["status"], 200)
        self.assertEqual(len(calls), 1)
        source["systemInstruction"]["parts"][0]["text"] = "Transcribe the actual speech verbatim"
        source["contents"][0]["parts"] = [
            {"text": "Current audio evidence for message_index=2;"},
            {"inlineData": {"mimeType": "audio/mpeg", "data": "YXVkaW8="}},
        ]
        response = await route.handle_async_request(httpx.Request(
            "POST", "https://generativelanguage.googleapis.com/test", json=source))
        observations = json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])["observations"]
        self.assertEqual(observations[0]["transcript"], "I said Boston.")
        self.assertEqual(observations[0]["message_index"], 2)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("fake-key", json.dumps(route.rows))
        await route.client.aclose()

        limited = Route("groq", "fake-key", "https://api.groq.com/openai/v1", 1)
        await limited.client.aclose()
        limited.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"retry-after": "60"})))
        source["systemInstruction"]["parts"][0]["text"] = "Return JSON."
        source["contents"][0]["parts"] = [{"text": "hello"}]
        response = await limited.handle_async_request(httpx.Request(
            "POST", "https://generativelanguage.googleapis.com/test", json=source))
        self.assertEqual(response.status_code, 429)
        self.assertTrue(limited.rate_limited)
        self.assertEqual(limited.rows[0]["retry_after"], "60")
        await limited.client.aclose()


if __name__ == "__main__":
    unittest.main()
