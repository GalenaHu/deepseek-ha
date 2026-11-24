"""Responses-to-ChatLog bridge. HA executes tools only after terminal success."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import probatio
from homeassistant.components import conversation
from homeassistant.helpers import llm
from homeassistant.helpers.chat_session import async_get_chat_session
from homeassistant.helpers.json import ExtendedJSONEncoder

from .api import ApiError


def trim_turns(content: list[conversation.Content], count: int) -> list[conversation.Content]:
    """Trim whole user turns, never a function call without its result."""
    starts = [index for index, item in enumerate(content) if isinstance(item, conversation.UserContent)]
    if len(starts) <= count:
        return list(content)
    system = [item for item in content[:starts[0]] if isinstance(item, conversation.SystemContent)]
    return system + content[starts[-count]:]


async def response_input(runtime: Any, log: conversation.ChatLog, options: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in trim_turns(log.content, options["history_turns"]):
        if isinstance(item, conversation.SystemContent):
            result.append({"role": "system", "content": item.content})
        elif isinstance(item, conversation.UserContent):
            parts = [{"type": "input_text", "text": item.content}]
            parts.extend(await runtime.attachments.parts(item.attachments, log.conversation_id, options["model"]))
            result.append({"role": "user", "content": parts})
        elif isinstance(item, conversation.AssistantContent):
            if isinstance(item.native, list):
                result.extend(item.native)
            else:
                if item.thinking_content:
                    result.append({"type": "reasoning", "content": [{"type": "reasoning_text", "text": item.thinking_content}]})
                if item.content:
                    result.append({"role": "assistant", "content": item.content})
                for call in item.tool_calls or []:
                    result.append({"type": "function_call", "call_id": call.id, "name": call.tool_name, "arguments": json.dumps(call.tool_args)})
        elif isinstance(item, conversation.ToolResultContent):
            result.append({"type": "function_call_output", "call_id": item.tool_call_id, "output": json.dumps(item.result.data, cls=ExtendedJSONEncoder)})
    return result


def completed_calls(output: list[dict[str, Any]], log: conversation.ChatLog) -> list[llm.ToolInput]:
    """Validate every call before allowing any of this round's actions to run."""
    existing = {call.id for item in log.content if isinstance(item, conversation.AssistantContent) for call in item.tool_calls or []}
    allowed = {tool.name: tool for tool in log.llm_api.tools} if log.llm_api else {}
    calls = []
    for item in output:
        if item.get("type") != "function_call":
            continue
        try:
            name, call_id = item["name"], item["call_id"]
            args = json.loads(item["arguments"])
            if not isinstance(args, dict) or not isinstance(call_id, str) or not call_id or call_id in existing or name not in allowed:
                raise ValueError
            args = allowed[name].parameters(args)
        except (KeyError, TypeError, ValueError, probatio.Invalid):
            raise ApiError("invalid_tool_call") from None
        existing.add(call_id)
        calls.append(llm.ToolInput(id=call_id, tool_name=name, tool_args=args))
    return calls


async def run(runtime: Any, log: conversation.ChatLog, agent_id: str, options: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    session_id = log.conversation_id
    if session_id not in runtime.sessions:
        runtime.sessions.add(session_id)
        with async_get_chat_session(runtime.hass, session_id) as session:
            def cleanup() -> None:
                runtime.sessions.discard(session_id)
                runtime.locks.pop(session_id, None)
                runtime.hass.async_create_task(runtime.attachments.cleanup(session_id))
            session.async_on_cleanup(cleanup)
    lock = runtime.locks.setdefault(session_id, asyncio.Lock())
    async with asyncio.timeout(options["total_timeout"]), runtime.gate, lock:
        await _run(runtime, log, agent_id, options, schema)


async def _run(runtime: Any, log: conversation.ChatLog, agent_id: str, options: dict[str, Any], schema: dict[str, Any] | None) -> None:
    tools = []
    if log.llm_api:
        for tool in log.llm_api.tools:
            parameters = probatio.to_openapi(tool.parameters, custom_serializer=log.llm_api.custom_serializer)
            if not isinstance(parameters, dict):
                raise ApiError("invalid_tool_schema")
            tools.append({"type": "function", "name": tool.name, "description": tool.description or "", "parameters": parameters})
    for round_index in range(options["max_tool_rounds"]):
        body: dict[str, Any] = {
            "model": options["model"],
            "input": await response_input(runtime, log, options),
            "max_output_tokens": options["max_tokens"],
            "reasoning": {"effort": options["thinking"]},
        }
        if tools:
            body["tools"] = tools
        if schema is not None:
            body["text"] = {"format": {"type": "json_schema", "name": "result", "schema": schema}}
        started = time.monotonic()
        final: dict[str, Any] | None = None

        async def deltas() -> AsyncIterator[conversation.AssistantContentDeltaDict]:
            nonlocal final
            yield {"role": "assistant"}
            text_seen = False
            thinking_seen = False
            async for event in runtime.api.responses(body, timeout=options["timeout"]):
                kind = event["type"]
                if kind == "response.output_text.delta" and isinstance(event.get("delta"), str) and event["delta"]:
                    text_seen = True
                    yield {"content": event["delta"]}
                elif kind == "response.reasoning_text.delta" and isinstance(event.get("delta"), str) and event["delta"]:
                    thinking_seen = True
                    yield {"thinking_content": event["delta"]}
                elif kind == "response.refusal.delta":
                    raise ApiError("refused")
                elif kind == "response.completed":
                    final = event["response"]
                    output = final["output"]
                    if any(not isinstance(item, dict) for item in output):
                        raise ApiError("invalid_completion")
                    for item in output:
                        parts = item.get("content", [])
                        if not isinstance(parts, list) or any(not isinstance(part, dict) for part in parts):
                            raise ApiError("invalid_completion")
                        for part in parts:
                            if part.get("type") == "refusal":
                                raise ApiError("refused")
                            if part.get("type") == "output_text" and not text_seen and part.get("text"):
                                yield {"content": part["text"]}
                            elif part.get("type") == "reasoning_text" and not thinking_seen and part.get("text"):
                                yield {"thinking_content": part["text"]}
                    calls = completed_calls(output, log)
                    if calls and round_index + 1 >= options["max_tool_rounds"]:
                        raise ApiError("tool_round_limit")
                    yield {"native": output}
                    if calls:
                        yield {"tool_calls": calls}

        async for _ in log.async_add_delta_content_stream(agent_id, deltas()):
            pass
        if final is None:
            raise ApiError("incomplete_stream")
        runtime.metrics.response(final.get("usage", {}), time.monotonic() - started)
        if not log.unresponded_tool_results:
            return
    raise ApiError("tool_round_limit")
