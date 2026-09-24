"""One offline check for the experimental route's request and response boundary."""

import json
import unittest

import httpx

from scripts.provider_route_probe import Route


class RouteProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_groq_text_and_audio_conversion(self):
        calls = []

        def respond(request):
            calls.append(request)
            if request.url.path.endswith("/audio/transcriptions"):
                return httpx.Response(200, json={"text": "I said Boston.", "segments": []})
            body = json.loads(request.content)
            assert body["model"] == "qwen/qwen3.8-27b"
            assert body["reasoning_effort"] == "none"
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                "message": {"content": '{"intent":"help","slots":{},"tool_calls":[],"observations":[],"clarification":null,"response":"Done."}'}}]})

        route = Route("groq", "fake-key", "https://api.groq.com/openai/v1", 3)
        await route.client.aclose()
        route.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        source = {"systemInstruction": {"parts": [{"text": "Return JSON."}]},
                  "contents": [{"parts": [{"text": "hello"}]}],
                  "generationConfig": {"maxOutputTokens": 100}}
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


if __name__ == "__main__":
    unittest.main()
