"""Behavior of the fixed-endpoint transport against simulated provider responses."""

import json
import unittest

import httpx2 as httpx

from custom_components.deepseek_ai.api import ApiError, DeepSeekClient


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_requires_successful_terminal_event(self):
        async def handler(request):
            self.assertEqual(str(request.url), "https://api.deepseek.com/responses")
            return httpx.Response(
                200, text='data: {"type":"response.output_text.delta","delta":"Hi"}\n\n'
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = DeepSeekClient(http, "fixture-key")
            with self.assertRaisesRegex(ApiError, "incomplete_stream"):
                _ = [event async for event in api.responses({"input": "Hello"})]

    async def test_completed_stream_and_usage(self):
        final = {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hi"}]}],
            "usage": {"input_tokens": 7, "output_tokens": 2},
        }

        async def handler(request):
            self.assertEqual(request.headers["authorization"], "Bearer fixture-key")
            self.assertTrue(json.loads(request.content)["stream"])
            return httpx.Response(
                200,
                text='data: {"type":"response.completed","response":' + json.dumps(final) + "}\n\n",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            events = [
                event
                async for event in DeepSeekClient(http, "fixture-key").responses({"input": "Hello"})
            ]
        self.assertEqual(events[-1]["response"]["usage"]["input_tokens"], 7)

    async def test_error_body_and_redirect_never_leak_or_follow(self):
        for status in (302, 401, 429, 503):
            calls = []

            async def handler(request):
                calls.append(str(request.url))
                return httpx.Response(
                    status,
                    headers={"location": "https://attacker.invalid"},
                    text="PRIVATE_KEY PRIVATE_HOME",
                )

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler), follow_redirects=True
            ) as http:
                with self.assertRaises(ApiError) as caught:
                    await DeepSeekClient(http, "fixture-key").validate_key()
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assertEqual(len(calls), 1)
