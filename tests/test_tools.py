"""Real HA exposure, authorization and ChatLog side-effect recovery."""

import json

import httpx2 as httpx
import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context, callback
from test_native import entity_id


def tool_output(name="intent__HassTurnOn", call_id="call-1", **args):
    return [
        {"type": "function_call", "call_id": call_id, "name": name, "arguments": json.dumps(args)}
    ]


@pytest.fixture
async def lights(hass, entry):
    calls = []
    hass.states.async_set("light.exposed", "off", {"friendly_name": "Exposed"})
    hass.states.async_set("light.secret", "off", {"friendly_name": "Secret"})
    async_expose_entity(hass, "conversation", "light.exposed", True)
    async_expose_entity(hass, "conversation", "light.secret", False)

    @callback
    def turn_on(call):
        calls.append(call)

    hass.services.async_register("light", "turn_on", turn_on)
    return calls


async def converse(
    hass, entry, text="Turn on", conversation_id=None, context=None, satellite_id=None
):
    return await conversation.async_converse(
        hass,
        text,
        conversation_id,
        context or Context(),
        language="en",
        agent_id=entity_id(hass, entry, "conversation"),
        satellite_id=satellite_id,
    )


async def test_unexposed_entity_cannot_be_controlled(hass, entry, provider, lights):
    provider.complete(
        "",
        output=[
            {
                "type": "function_call",
                "call_id": "hidden",
                "name": "intent__HassTurnOn",
                "arguments": json.dumps({"name": "Secret", "domain": "light"}),
            }
        ],
    )
    provider.complete("Denied")
    await converse(hass, entry)
    assert not lights
    request = json.loads(provider.requests[-1].content)
    outputs = [item for item in request["input"] if item.get("type") == "function_call_output"]
    assert outputs and "error" in outputs[-1]["output"]


async def test_tools_after_success_are_not_replayed_on_network_failure(
    hass, entry, provider, lights
):
    provider.complete(
        "",
        output=[
            {
                "type": "function_call",
                "call_id": "once",
                "name": "intent__HassTurnOn",
                "arguments": json.dumps({"name": "Exposed", "domain": "light"}),
            }
        ],
    )
    provider.queue.append(httpx.Response(503, text="PRIVATE_ERROR"))
    failed = await converse(hass, entry)
    assert len(lights) == 1
    assert failed.response.error_code is not None
    provider.complete("The action already ran")
    await converse(hass, entry, "Continue", failed.conversation_id)
    assert len(lights) == 1
    inputs = json.loads(provider.requests[-1].content)["input"]
    assert any(
        item.get("type") == "function_call_output" and item["call_id"] == "once" for item in inputs
    )


@pytest.mark.parametrize("status", ["response.incomplete", "response.failed"])
async def test_failed_stream_never_executes_actions(hass, entry, provider, lights, status):
    event = {"type": status, "response": {"output": tool_output()}}
    provider.queue.append(httpx.Response(200, text="data: " + json.dumps(event) + "\n\n"))
    result = await converse(hass, entry)
    assert result.response.error_code is not None
    assert not lights


@pytest.mark.parametrize("identity", ["none", "ordinary", "admin"])
async def test_admin_tool_api_enforces_real_user_context(hass, entry, provider, identity):
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "conversation")
    hass.config_entries.async_update_subentry(entry, sub, data={"llm_hass_api": ["homeassistant"]})
    await hass.async_block_till_done()
    await hass.auth.async_create_user("Owner", group_ids=[GROUP_ID_ADMIN])
    context = Context()
    if identity != "none":
        user = await hass.auth.async_create_user(
            identity, group_ids=[GROUP_ID_ADMIN if identity == "admin" else GROUP_ID_USER]
        )
        context = Context(user_id=user.id)
    count = len(provider.requests)
    if identity == "admin":
        provider.complete("Ready")
    result = await converse(
        hass,
        entry,
        context=context,
        satellite_id="assist_satellite.fixture" if identity == "none" else None,
    )
    if identity == "admin":
        assert result.response.error_code is None
        assert len(provider.requests) == count + 1
    else:
        assert result.response.error_code is not None
        assert len(provider.requests) == count


async def test_unload_cancels_active_sse_before_any_tool_action(
    hass, entry, provider, lights, caplog
):
    import asyncio

    entered, released = asyncio.Event(), asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await released.wait()
            yield b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n'

    provider.queue.append(httpx.Response(200, stream=Stream()))
    runtime = entry.runtime_data
    job = asyncio.create_task(converse(hass, entry, "PRIVATE_HOME"))
    await entered.wait()
    assert runtime.jobs
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(asyncio.CancelledError):
        await job
    released.set()
    assert runtime.closing and not runtime.jobs
    assert not lights
    assert "PRIVATE_HOME" not in caplog.text
    # Fixture teardown may call unload again; HA treats it as already unloaded.


async def test_parallel_tool_cancel_preserves_completed_result_and_stops_siblings(
    hass, entry, provider
):
    import asyncio

    from homeassistant.helpers import llm
    from homeassistant.helpers.chat_session import async_get_chat_session

    started, completed, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Tool(llm.Tool):
        integration = "deepseek_ai"

        def __init__(self, name):
            self.name = name

        async def async_call(self, hass, tool_input, llm_context):
            if self.name == "fixture__slow":
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            completed.set()
            return llm.ToolResult(data={"already_executed": True})

    class API(llm.API):
        async def async_get_api_instance(self, llm_context):
            return llm.APIInstance(
                api=self,
                api_prompt="Fixture MCP tools",
                llm_context=llm_context,
                tools=[Tool("fixture__slow"), Tool("fixture__fast")],
            )

    remove = llm.async_register_api(hass, API(hass=hass, id="fixture_mcp", name="Fixture MCP"))
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "conversation")
    hass.config_entries.async_update_subentry(entry, sub, data={"llm_hass_api": ["fixture_mcp"]})
    await hass.async_block_till_done()
    provider.complete(
        "", output=tool_output("fixture__slow", "slow") + tool_output("fixture__fast", "fast")
    )
    job = asyncio.create_task(converse(hass, entry, conversation_id="cancel-fixture"))
    await started.wait()
    await completed.wait()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert stopped.is_set()
    assert not entry.runtime_data.jobs
    with async_get_chat_session(hass, "cancel-fixture", context=Context()) as session:
        with conversation.async_get_chat_log(hass, session) as log:
            results = {
                item.tool_call_id: item.result.data
                for item in log.content
                if isinstance(item, conversation.ToolResultContent)
            }
    assert entry.runtime_data.metrics.values["input_tokens"] == 9
    assert results["fast"] == {"already_executed": True}
    assert results["slow"]["outcome"] == "unknown_do_not_retry"
    remove()


async def test_demoted_admin_cannot_reuse_cached_tool_api(hass, entry, provider):
    await hass.auth.async_create_user("Owner", group_ids=[GROUP_ID_ADMIN])
    user = await hass.auth.async_create_user("Admin", group_ids=[GROUP_ID_ADMIN])
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "conversation")
    hass.config_entries.async_update_subentry(entry, sub, data={"llm_hass_api": ["homeassistant"]})
    await hass.async_block_till_done()
    provider.complete("Ready")
    first = await converse(hass, entry, context=Context(user_id=user.id))
    assert first.response.error_code is None
    await hass.auth.async_update_user(user, group_ids=[GROUP_ID_USER])
    assert not user.is_admin
    count = len(provider.requests)
    result = await converse(
        hass, entry, conversation_id=first.conversation_id, context=Context(user_id=user.id)
    )
    assert result.response.error_code is not None and len(provider.requests) == count
