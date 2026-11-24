"""Opt-in evaluation actions and isolated public-web tools."""

import json

import httpx2 as httpx
import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from test_native import entity_id
from test_tools import converse


async def add_subentry(hass, entry, kind, data):
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, kind), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], data)
    await hass.async_block_till_done()
    return result


async def test_evaluation_requires_optin_and_all_question_types(hass, entry, provider):
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "evaluation"), context={"source": "user"}
    )
    denied = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Experimental"}
    )
    assert denied["type"] is FlowResultType.FORM
    assert denied["errors"]["base"] == "experimental_required"
    created = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Experimental", "acknowledge_experimental": True}
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    provider.complete(
        json.dumps(
            {
                "yes": {"noul": 0.8},
                "pick": {"choice": "a", "probabilities": {"a": 0.7, "b": 0.3}},
                "level": {"score": 0.3, "probabilities": [0.7, 0.3]},
            }
        )
    )
    result = await hass.services.async_call(
        "ai_task",
        "evaluate",
        {
            "entity_id": entity_id(hass, entry, "evaluation"),
            "task_name": "Explicit only",
            "state": "fixture",
            "questions": {
                "yes": {"type": "noul", "instructions": "True?"},
                "pick": {
                    "type": "choice",
                    "instructions": "Pick",
                    "criteria": {"a": "A", "b": "B"},
                },
                "level": {"type": "score", "instructions": "Score", "criteria": ["low", "high"]},
            },
        },
        blocking=True,
        return_response=True,
    )
    assert result["answers"]["yes"] == {"type": "noul", "noul": 0.8}
    assert result["answers"]["pick"]["choice"] == "a"
    assert result["answers"]["level"]["score"] == 0.3
    assert "tools" not in json.loads(provider.requests[-1].content)
    from homeassistant.components.ai_task.const import DATA_PREFERENCES

    assert hass.data[DATA_PREFERENCES].evaluate_entity_id is None


async def test_web_agent_calls_only_official_search_and_returns_sources(hass, entry, provider):
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "conversation")
    hass.config_entries.async_update_subentry(entry, sub, data={"web": True, "llm_hass_api": []})
    await hass.async_block_till_done()
    provider.complete(
        "",
        output=[
            {
                "type": "function_call",
                "call_id": "search-1",
                "name": "deepseek_ai__search",
                "arguments": json.dumps({"query": "Home Assistant"}),
            }
        ],
    )
    provider.queue.append(
        httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "HA",
                        "url": "https://www.home-assistant.io/",
                        "snippet": "Home automation",
                    }
                ]
            },
        )
    )
    provider.complete("Source: https://www.home-assistant.io/")
    result = await converse(hass, entry, "Search")
    assert result.response.error_code is None
    bodies = [json.loads(r.content) for r in provider.requests if r.url.path == "/responses"]
    assert {tool["name"] for tool in bodies[0]["tools"]} == {
        "deepseek_ai__search",
        "deepseek_ai__fetch",
    }
    assert any(r.url.path == "/v1/tools/search" for r in provider.requests)
    assert "https://www.home-assistant.io/" in str(bodies[-1]["input"])


@pytest.mark.parametrize("output", ["{}", '{"answer":"wrong"}', "not json"])
async def test_native_task_missing_field_and_bad_json_fail(hass, entry, provider, output):
    provider.complete(output)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "ai_task",
            "generate_data",
            {
                "entity_id": entity_id(hass, entry, "ai_task"),
                "task_name": "strict",
                "instructions": "JSON",
                "structure": {"answer": {"required": True, "selector": {"boolean": {}}}},
            },
            blocking=True,
            return_response=True,
        )


@pytest.mark.parametrize("kind", ["refusal", "incomplete"])
async def test_task_refusal_or_truncation_never_succeeds(hass, entry, provider, kind):
    if kind == "refusal":
        provider.complete(
            "",
            output=[
                {"type": "message", "content": [{"type": "refusal", "refusal": "PRIVATE_HOME"}]}
            ],
        )
    else:
        provider.queue.append(httpx.Response(200, text='data: {"type":"response.incomplete"}\n\n'))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "ai_task",
            "generate_data",
            {
                "entity_id": entity_id(hass, entry, "ai_task"),
                "task_name": "strict",
                "instructions": "JSON",
            },
            blocking=True,
            return_response=True,
        )
