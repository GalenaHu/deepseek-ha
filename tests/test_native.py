"""Public configuration and AI actions, with the actual HA platform machinery."""

import json

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er


def entity_id(hass, entry, kind, domain=None):
    sub = next(value for value in entry.subentries.values() if value.subentry_type == kind)
    return er.async_get(hass).async_get_entity_id(domain or ("ai_task" if kind in ("ai_task", "evaluation") else kind), "deepseek_ai", sub.subentry_id)


async def test_setup_native_generation_and_diagnostics(hass, entry, provider):
    from custom_components.deepseek_ai.diagnostics import async_get_config_entry_diagnostics

    assert {sub.subentry_type for sub in entry.subentries.values()} == {"conversation", "ai_task", "stt", "tts"}
    provider.complete('{"present": true}')
    result = await hass.services.async_call("ai_task", "generate_data", {"entity_id": entity_id(hass, entry, "ai_task"), "task_name": "fixture", "instructions": "PRIVATE_HOME fixture", "structure": {"present": {"required": True, "selector": {"boolean": {}}}}}, blocking=True, return_response=True)
    assert result["data"] == {"present": True}
    request = json.loads(provider.requests[-1].content)
    assert request["text"]["format"]["schema"]["properties"]["present"]["type"] == "boolean"
    diagnostics = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
    assert "TEST_KEY" not in diagnostics and "PRIVATE_HOME" not in diagnostics
    assert entry.runtime_data.metrics.values["input_tokens"] == 9


async def test_structured_wrong_type_fails_without_logging_payload(hass, entry, provider, caplog):
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    provider.complete('{"present": "PRIVATE_HOME"}')
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("ai_task", "generate_data", {"entity_id": entity_id(hass, entry, "ai_task"), "task_name": "fixture", "instructions": "json", "structure": {"present": {"required": True, "selector": {"boolean": {}}}}}, blocking=True, return_response=True)
    assert "PRIVATE_HOME" not in caplog.text


async def test_reauth_reconfigure_and_subentry_conflict(hass, entry, provider):
    reauth = await hass.config_entries.flow.async_init("deepseek_ai", context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data)
    result = await hass.config_entries.flow.async_configure(reauth["flow_id"], {"api_key": "UPDATED_FAKE_KEY", "max_concurrent": 1})
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry.data["api_key"] == "UPDATED_FAKE_KEY"
    flow = await hass.config_entries.subentries.async_init(entry.entry_id, "conversation", context={"source": "user"})
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"name": "Web plus home", "web": True, "llm_hass_api": ["assist"]})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "web_tools_conflict"


async def test_no_home_tools_conversation_and_multiturn(hass, entry, provider):
    sub = next(item for item in entry.subentries.values() if item.subentry_type == "conversation")
    hass.config_entries.async_update_subentry(entry, sub, data={"llm_hass_api": []})
    await hass.async_block_till_done()
    agent = entity_id(hass, entry, "conversation")
    provider.complete("你好")
    first = await conversation.async_converse(hass, "PRIVATE_HOME", None, Context(), language="zh-CN", agent_id=agent)
    assert first.response.speech["plain"]["speech"] == "你好"
    provider.complete("我记得")
    await conversation.async_converse(hass, "继续", first.conversation_id, Context(), language="zh-CN", agent_id=agent)
    inputs = json.loads(provider.requests[-1].content)["input"]
    assert any("PRIVATE_HOME" in str(item) for item in inputs)

