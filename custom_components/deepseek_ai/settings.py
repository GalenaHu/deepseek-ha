"""Validated agent settings shared by configuration and runtime."""

from collections.abc import Mapping
from typing import Any

from .const import DEFAULTS, MODELS, SUBTYPES


def agent_settings(kind: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate persisted settings too, so a stale config cannot bypass isolation."""
    if kind not in SUBTYPES:
        raise ValueError("invalid_subtype")
    result = {**DEFAULTS, **data}
    if result["model"] not in MODELS or result["thinking"] not in ("none", "low", "high", "max"):
        raise ValueError("invalid_model")
    for field, minimum, maximum in (
        ("max_tokens", 64, 384000),
        ("max_tool_rounds", 1, 20),
        ("history_turns", 1, 50),
        ("timeout", 5, 600),
        ("total_timeout", 30, 900),
    ):
        value = result[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or int(value) != value
            or not minimum <= value <= maximum
        ):
            raise ValueError("invalid_limits")
        result[field] = int(value)
    apis = result.get("llm_hass_api", ["assist"] if kind == "conversation" else [])
    if not isinstance(apis, list) or any(not isinstance(api, str) for api in apis):
        raise ValueError("invalid_tools")
    if kind != "conversation" and apis:
        raise ValueError("task_tools_forbidden")
    if not isinstance(result["web"], bool) or (result["web"] and apis):
        raise ValueError("web_tools_conflict")
    if kind in ("evaluation", "stt", "tts") and result["web"]:
        raise ValueError("invalid_tools")
    if result["voice"] not in ("stella", "tide") or not isinstance(result["prompt"], str):
        raise ValueError("invalid_options")
    result["llm_hass_api"] = apis
    return result
