"""Public configuration and AI actions, with the actual HA platform machinery."""

import json

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er


def entity_id(hass, entry, kind, domain=None):
    sub = next(value for value in entry.subentries.values() if value.subentry_type == kind)
    return next(
        item.entity_id
        for item in er.async_get(hass).entities.values()
        if item.config_entry_id == entry.entry_id and item.config_subentry_id == sub.subentry_id
    )


async def test_setup_native_generation_and_diagnostics(hass, entry, provider, caplog):
    from custom_components.deepseek_ai.diagnostics import async_get_config_entry_diagnostics

    assert {sub.subentry_type for sub in entry.subentries.values()} == {
        "conversation",
        "ai_task",
        "stt",
        "tts",
    }
    provider.complete('{"present": true}')
    result = await hass.services.async_call(
        "ai_task",
        "generate_data",
        {
            "entity_id": entity_id(hass, entry, "ai_task"),
            "task_name": "fixture",
            "instructions": "PRIVATE_HOME fixture",
            "structure": {"present": {"required": True, "selector": {"boolean": {}}}},
        },
        blocking=True,
        return_response=True,
    )
    assert result["data"] == {"present": True}
    request = json.loads(provider.requests[-1].content)
    assert request["text"]["format"]["schema"]["properties"]["present"]["type"] == "boolean"
    diagnostics = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
    assert "TEST_KEY" not in diagnostics and "PRIVATE_HOME" not in diagnostics
    assert entry.runtime_data.metrics.values["input_tokens"] == 9
    assert "PRIVATE_HOME" not in caplog.text and "TEST_KEY_NEVER_REAL" not in caplog.text


async def test_structured_wrong_type_fails_without_logging_payload(hass, entry, provider, caplog):
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    provider.complete('{"present": "PRIVATE_HOME"}')
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "ai_task",
            "generate_data",
            {
                "entity_id": entity_id(hass, entry, "ai_task"),
                "task_name": "fixture",
                "instructions": "json",
                "structure": {"present": {"required": True, "selector": {"boolean": {}}}},
            },
            blocking=True,
            return_response=True,
        )
    assert "PRIVATE_HOME" not in caplog.text


async def test_reauth_reconfigure_and_subentry_conflict(hass, entry, provider):
    reauth = await hass.config_entries.flow.async_init(
        "deepseek_ai", context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data
    )
    result = await hass.config_entries.flow.async_configure(
        reauth["flow_id"], {"api_key": "UPDATED_FAKE_KEY", "max_concurrent": 1}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry.data["api_key"] == "UPDATED_FAKE_KEY"
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "conversation"), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Web plus home", "web": True, "llm_hass_api": ["assist"]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "web_tools_conflict"


async def test_no_home_tools_conversation_and_multiturn(hass, entry, provider):
    sub = next(item for item in entry.subentries.values() if item.subentry_type == "conversation")
    hass.config_entries.async_update_subentry(entry, sub, data={"llm_hass_api": []})
    await hass.async_block_till_done()
    agent = entity_id(hass, entry, "conversation")
    provider.complete("你好")
    first = await conversation.async_converse(
        hass, "PRIVATE_HOME", None, Context(), language="zh-CN", agent_id=agent
    )
    assert first.response.speech["plain"]["speech"] == "你好"
    provider.complete("我记得")
    await conversation.async_converse(
        hass, "继续", first.conversation_id, Context(), language="zh-CN", agent_id=agent
    )
    inputs = json.loads(provider.requests[-1].content)["input"]
    assert any("PRIVATE_HOME" in str(item) for item in inputs)


async def test_reconfigure_credential_and_multiple_subentries(hass, entry, provider):
    flow = await hass.config_entries.flow.async_init(
        "deepseek_ai", context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"api_key": "RECONFIGURED_FAKE_KEY", "max_concurrent": 3}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry.data["max_concurrent"] == 3
    for kind in ("conversation", "ai_task", "stt", "tts"):
        flow = await hass.config_entries.subentries.async_init(
            (entry.entry_id, kind), context={"source": "user"}
        )
        result = await hass.config_entries.subentries.async_configure(
            flow["flow_id"], {"name": f"Second {kind}"}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
    assert len(entry.subentries) == 8
    entities = [
        item
        for item in er.async_get(hass).entities.values()
        if item.config_entry_id == entry.entry_id
    ]
    assert len([item for item in entities if item.domain == "conversation"]) == 2


async def test_invalid_credentials_show_form_error(hass, provider):
    from unittest.mock import patch

    from homeassistant.setup import async_setup_component

    from custom_components.deepseek_ai.api import ApiError, DeepSeekClient

    assert await async_setup_component(hass, "homeassistant", {})
    flow = await hass.config_entries.flow.async_init("deepseek_ai", context={"source": "user"})
    with patch.object(DeepSeekClient, "validate_key", side_effect=ApiError("invalid_auth", 401)):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"api_key": "fake"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_usage_reset_native_button_and_reload_persistence(hass, entry, provider):
    provider.complete("hello")
    from test_tools import converse

    await converse(hass, entry)
    assert entry.runtime_data.metrics.values["requests"] == 1
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.metrics.values["requests"] == 1
    button_id = next(
        item.entity_id
        for item in er.async_get(hass).entities.values()
        if item.config_entry_id == entry.entry_id and item.domain == "button"
    )
    count = len(provider.requests)
    await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
    assert len(provider.requests) == count and entry.runtime_data.metrics.values["requests"] == 0


async def test_provider_auth_failure_starts_native_reauth(hass, entry, provider, caplog):
    import httpx2 as httpx
    from test_tools import converse

    provider.queue.append(httpx.Response(401, text="PRIVATE_HOME PRIVATE_KEY"))
    result = await converse(hass, entry)
    await hass.async_block_till_done()
    assert result.response.error_code is not None
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )
    assert "PRIVATE_HOME" not in caplog.text and "PRIVATE_KEY" not in caplog.text
