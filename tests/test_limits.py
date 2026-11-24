"""Bounds and malformed remote input, without substituting any HA internals."""

import asyncio

import httpx2 as httpx
import pytest
from homeassistant.components import conversation

from custom_components.deepseek_ai.api import ApiError, DeepSeekClient
from custom_components.deepseek_ai.engine import trim_turns
from custom_components.deepseek_ai.metrics import Metrics


async def test_sse_without_newline_is_bounded_before_decoding(monkeypatch):
    from custom_components.deepseek_ai import api

    monkeypatch.setattr(api, "MAX_EVENT_BYTES", 32)

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10):
                yield b"x" * 20

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))
    ) as client:
        with pytest.raises(ApiError, match="event_too_large"):
            _ = [event async for event in DeepSeekClient(client, "fake").responses({})]


async def test_cancellation_propagates_and_closes_stream():
    entered, closed = asyncio.Event(), asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b""

        async def aclose(self):
            closed.set()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))
    ) as client:

        async def consume():
            return [event async for event in DeepSeekClient(client, "fake").responses({})]

        job = asyncio.create_task(consume())
        await entered.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert closed.is_set()


async def test_null_and_invalid_usage_cannot_break_followup(hass):
    metrics = Metrics(hass, "fixture")
    for usage in (
        None,
        {"input_tokens_details": None},
        {"output_tokens": float("inf")},
        {"input_tokens": -1},
        {"reasoning_tokens": "PRIVATE_HOME"},
    ):
        metrics.response(usage, 0.1)
    assert metrics.values["requests"] == 5
    assert metrics.values["input_tokens"] == metrics.values["output_tokens"] == 0
    await metrics.save()
    restored = Metrics(hass, "fixture")
    await restored.load()
    assert restored.values == metrics.values
    await restored.reset()
    assert not any(restored.values.values())


def test_history_retains_whole_tool_pairs():
    from homeassistant.helpers import llm

    content = [
        conversation.SystemContent("system"),
        conversation.UserContent("old"),
        conversation.AssistantContent("agent", "", tool_calls=[llm.ToolInput("toggle", {}, "a")]),
        conversation.ToolResultContent("agent", "a", "toggle", llm.ToolResult(data={"ok": True})),
        conversation.UserContent("new"),
    ]
    trimmed = trim_turns(content, 1)
    assert len(trimmed) == 2 and trimmed[-1].content == "new"


async def test_file_pagination_does_not_miss_owned_pending_uploads():
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [{"id": f"file-{len(requests)}"}],
                "has_more": len(requests) < 2,
                "last_id": "file-1",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        files = await DeepSeekClient(client, "fake").list_files()
    assert len(files) == 2 and requests[1].url.params["after"] == "file-1"


async def test_native_deadline_is_failure_and_cleans_job(hass, entry, provider):
    from homeassistant.core import Context
    from test_native import entity_id

    finished = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                await asyncio.Event().wait()
                yield b""
            finally:
                finished.set()

    provider.queue.append(httpx.Response(200, stream=Stream()))
    agent_id = entity_id(hass, entry, "conversation")
    agent = conversation.async_get_agent(hass, agent_id)
    agent.options["total_timeout"] = 0.01
    result = await conversation.async_converse(
        hass, "fixture", None, Context(), language="en", agent_id=agent_id
    )
    assert result.response.error_code is not None and finished.is_set()
    assert not entry.runtime_data.jobs


async def test_http_timeout_is_sanitized():
    async def handler(request):
        raise httpx.ReadTimeout("PRIVATE_KEY PRIVATE_HOME", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ApiError) as error:
            await DeepSeekClient(client, "fake").validate_key()
    assert "PRIVATE" not in str(error.value)
