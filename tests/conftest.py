"""Real HA fixtures, with only the remote provider transport substituted."""

import json
from collections import deque
from unittest.mock import patch

import httpx2 as httpx
import pytest

pytest_plugins = ["pytest_homeassistant_custom_component.plugins"]


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


class Provider:
    def __init__(self):
        self.queue = deque()
        self.requests = []

    def complete(self, text, *, output=None):
        output = output if output is not None else [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]
        final = {"status": "completed", "output": output, "usage": {"input_tokens": 9, "output_tokens": 3}}
        events = []
        if text:
            events.append({"type": "response.output_text.delta", "delta": text})
        events.append({"type": "response.completed", "response": final})
        self.queue.append(httpx.Response(200, text="".join("data: " + json.dumps(event) + "\n\n" for event in events)))

    async def handle(self, request):
        self.requests.append(request)
        assert request.url.host == "api.deepseek.com", "Provider transport tried an unexpected host"
        if request.url.path == "/models":
            return httpx.Response(200, json={"data": []})
        if request.url.path == "/files" and request.method == "GET":
            return httpx.Response(200, json={"data": []})
        if not self.queue:
            raise AssertionError("Unexpected provider request: " + request.url.path)
        return self.queue.popleft()


@pytest.fixture
async def provider():
    from custom_components.deepseek_ai import config_flow
    from custom_components.deepseek_ai import get_async_client as unused

    service = Provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(service.handle)) as client:
        with patch("custom_components.deepseek_ai.get_async_client", return_value=client), patch.object(config_flow, "get_async_client", return_value=client):
            yield service


@pytest.fixture
async def entry(hass, provider):
    from homeassistant.data_entry_flow import FlowResultType

    first = await hass.config_entries.flow.async_init("deepseek_ai", context={"source": "user"})
    assert first["type"] is FlowResultType.FORM
    created = await hass.config_entries.flow.async_configure(first["flow_id"], {"api_key": "TEST_KEY_NEVER_REAL", "max_concurrent": 2})
    assert created["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    config_entry = created["result"]
    assert config_entry.state.value == "loaded", config_entry.state
    yield config_entry
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

