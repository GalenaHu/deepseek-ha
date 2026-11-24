"""The documented minimum must pass both HACS and the native setup guard."""

import json
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2026.11.1", ConfigEntryState.SETUP_ERROR),
        ("2026.11.2", ConfigEntryState.LOADED),
        ("2026.11.3", ConfigEntryState.LOADED),
    ],
)
async def test_native_minimum_version_gate(hass, provider, monkeypatch, version, expected):
    import custom_components.deepseek_ai as integration

    monkeypatch.setattr(integration, "HA_VERSION", version)
    assert await async_setup_component(hass, "homeassistant", {})
    flow = await hass.config_entries.flow.async_init("deepseek_ai", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"api_key": "FAKE"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    try:
        assert entry.state is expected
    finally:
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


def test_hacs_and_runtime_agree_on_minimum():
    from custom_components.deepseek_ai.const import MIN_HA

    hacs = json.loads((Path(__file__).resolve().parents[1] / "hacs.json").read_text())
    assert hacs["homeassistant"] == MIN_HA == "2026.11.2"
