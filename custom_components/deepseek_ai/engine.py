"""Responses-to-ChatLog bridge. HA executes tools only after terminal success."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.components import conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.chat_session import async_get_chat_session
from homeassistant.helpers.json import ExtendedJSONEncoder

from .api import ApiError
from .const import MAX_HISTORY_BYTES
from .json_util import decode_json

if TYPE_CHECKING:
    from . import Runtime


class ToolBatch:
    """Retain completed parallel results, and stop sibling calls on cancellation."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[Any]] = set()
        self.results: dict[str, llm.ToolResult] = {}

    async def finish(self, log: conversation.ChatLog, agent_id: str) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        recorded = {
            item.tool_call_id
            for item in log.content
            if isinstance(item, conversation.ToolResultContent)
        }
        for item in list(log.content):
            if not isinstance(item, conversation.AssistantContent):
                continue
            for call in item.tool_calls or []:
                if call.external or call.id in recorded:
                    continue
                result = self.results.get(
                    call.id,
                    llm.ToolResult(
                        data={"error": "execution_interrupted", "outcome": "unknown_do_not_retry"},
                        error=True,
                    ),
                )
                log.async_add_assistant_content_without_tools(
                    conversation.ToolResultContent(
                        agent_id=agent_id,
                        tool_call_id=call.id,
                        tool_name=call.tool_name,
                        result=result,
                    )
                )
                recorded.add(call.id)


class TrackedTool(llm.Tool):
    """Keep HA-spawned tool tasks within this entry's unload boundary."""

    def __init__(self, runtime: Runtime, tool: llm.Tool, batch: ToolBatch, api: llm.API) -> None:
        self.runtime = runtime
        self.batch = batch
        self.api = api
        self.tool: llm.Tool = tool.tool if isinstance(tool, TrackedTool) else tool
        for field in ("name", "title", "description", "parameters", "annotations", "integration"):
            setattr(self, field, getattr(self.tool, field))

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> llm.ToolResult:
        task = asyncio.current_task()
        assert task is not None
        self.batch.tasks.add(task)
        try:
            async with self.runtime.job():
                if self.api.requires_admin:
                    await llm.async_get_authorized_api_instance(self.api, llm_context)
                result = await self.tool.async_call(hass, tool_input, llm_context)
                if not isinstance(result, llm.ToolResult):
                    result = llm.ToolResult(data=result)
                self.batch.results[tool_input.id] = result
                return result
        except (HomeAssistantError, probatio.Invalid) as err:
            self.batch.results[tool_input.id] = llm.ToolResult(
                data={"error": type(err).__name__},
                error=True,
            )
            raise
        finally:
            self.batch.tasks.discard(task)


def trim_turns(content: list[conversation.Content], count: int) -> list[conversation.Content]:
    """Trim whole user turns, never a function call without its result."""
    starts = [
        index for index, item in enumerate(content) if isinstance(item, conversation.UserContent)
    ]
    if len(starts) <= count:
        return list(content)
    system = [item for item in content[: starts[0]] if isinstance(item, conversation.SystemContent)]
    return system + content[starts[-count] :]


async def response_input(
    runtime: Runtime, log: conversation.ChatLog, options: dict[str, Any]
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = [[]]
    for item in trim_turns(log.content, options["history_turns"]):
        if isinstance(item, conversation.UserContent):
            groups.append([])
        result = groups[-1]
        if isinstance(item, conversation.SystemContent):
            result.append({"role": "system", "content": item.content})
        elif isinstance(item, conversation.UserContent):
            parts = [{"type": "input_text", "text": item.content}]
            parts.extend(
                await runtime.attachments.parts(
                    item.attachments, log.conversation_id, options["model"]
                )
            )
            result.append({"role": "user", "content": parts})
        elif isinstance(item, conversation.AssistantContent):
            if isinstance(item.native, list):
                result.extend(item.native)
            else:
                if item.thinking_content:
                    result.append(
                        {
                            "type": "reasoning",
                            "content": [{"type": "reasoning_text", "text": item.thinking_content}],
                        }
                    )
                if item.content:
                    result.append({"role": "assistant", "content": item.content})
                for call in item.tool_calls or []:
                    result.append(
                        {
                            "type": "function_call",
                            "call_id": call.id,
                            "name": call.tool_name,
                            "arguments": json.dumps(call.tool_args),
                        }
                    )
        elif isinstance(item, conversation.ToolResultContent):
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": item.tool_call_id,
                    "output": json.dumps(item.result.data, cls=ExtendedJSONEncoder),
                }
            )
        while (
            sum(
                len(json.dumps(group, ensure_ascii=False, cls=ExtendedJSONEncoder).encode())
                for group in groups
            )
            > MAX_HISTORY_BYTES
        ):
            if len(groups) <= 2:
                raise ApiError("current_turn_too_large")
            groups.pop(1)
    return [item for group in groups for item in group]


def completed_calls(output: list[dict[str, Any]], log: conversation.ChatLog) -> list[llm.ToolInput]:
    """Validate every call before allowing any of this round's actions to run."""
    existing = {
        call.id
        for item in log.content
        if isinstance(item, conversation.AssistantContent)
        for call in item.tool_calls or []
    }
    allowed = {tool.name: tool for tool in log.llm_api.tools} if log.llm_api else {}
    calls = []
    for item in output:
        if item.get("type") != "function_call":
            continue
        try:
            name, call_id = item["name"], item["call_id"]
            args = decode_json(item["arguments"])
            if (
                not isinstance(args, dict)
                or not isinstance(call_id, str)
                or not call_id
                or call_id in existing
                or name not in allowed
            ):
                raise ValueError
            args = allowed[name].parameters(args)
        except KeyError, TypeError, ValueError, probatio.Invalid:
            raise ApiError("invalid_tool_call") from None
        existing.add(call_id)
        calls.append(llm.ToolInput(id=call_id, tool_name=name, tool_args=args))
    return calls


async def run(
    runtime: Runtime,
    log: conversation.ChatLog,
    agent_id: str,
    options: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> None:
    session_id = log.conversation_id
    if session_id not in runtime.sessions:
        runtime.sessions.add(session_id)
        with async_get_chat_session(runtime.hass, session_id) as session:

            def cleanup() -> None:
                runtime.sessions.discard(session_id)
                runtime.locks.pop(session_id, None)

                async def clean_files() -> None:
                    async with runtime.job():
                        await runtime.attachments.cleanup(session_id)

                if not runtime.closing:
                    runtime.hass.async_create_task(clean_files())

            session.async_on_cleanup(cleanup)
    lock = runtime.locks.setdefault(session_id, asyncio.Lock())
    async with runtime.job(), asyncio.timeout(options["total_timeout"]), runtime.gate, lock:
        batch = ToolBatch()
        try:
            await _run(runtime, log, agent_id, options, schema, batch)
        finally:
            await batch.finish(log, agent_id)


async def _run(
    runtime: Runtime,
    log: conversation.ChatLog,
    agent_id: str,
    options: dict[str, Any],
    schema: dict[str, Any] | None,
    batch: ToolBatch,
) -> None:
    tools = []
    if log.llm_api:
        log.llm_api = replace(
            log.llm_api,
            tools=[
                TrackedTool(runtime, tool, batch, log.llm_api.api) for tool in log.llm_api.tools
            ],
        )
        for tool in log.llm_api.tools:
            parameters = probatio.to_openapi(
                tool.parameters,
                custom_serializer=log.llm_api.custom_serializer,
                openapi_version="3.1.0",
            )
            if not isinstance(parameters, dict):
                raise ApiError("invalid_tool_schema")
            tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": parameters,
                }
            )
    for round_index in range(options["max_tool_rounds"] + 1):
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
            async with aclosing(runtime.api.responses(body, timeout=options["timeout"])) as events:
                async for event in events:
                    kind = event["type"]
                    if (
                        kind == "response.output_text.delta"
                        and isinstance(event.get("delta"), str)
                        and event["delta"]
                    ):
                        text_seen = True
                        yield {"content": event["delta"]}
                    elif (
                        kind == "response.reasoning_text.delta"
                        and isinstance(event.get("delta"), str)
                        and event["delta"]
                    ):
                        thinking_seen = True
                        yield {"thinking_content": event["delta"]}
                    elif kind == "response.refusal.delta":
                        raise ApiError("refused")
                    elif kind == "response.completed":
                        final = event["response"]
                        runtime.metrics.response(final.get("usage"), time.monotonic() - started)
                        output = final["output"]
                        if any(not isinstance(item, dict) for item in output):
                            raise ApiError("invalid_completion")
                        for item in output:
                            parts = item.get("content", [])
                            if not isinstance(parts, list) or any(
                                not isinstance(part, dict) for part in parts
                            ):
                                raise ApiError("invalid_completion")
                            for part in parts:
                                if part.get("type") == "refusal":
                                    raise ApiError("refused")
                                if (
                                    part.get("type") == "output_text"
                                    and not text_seen
                                    and part.get("text")
                                ):
                                    yield {"content": part["text"]}
                                elif (
                                    part.get("type") == "reasoning_text"
                                    and not thinking_seen
                                    and part.get("text")
                                ):
                                    yield {"thinking_content": part["text"]}
                        calls = completed_calls(output, log)
                        if calls and round_index >= options["max_tool_rounds"]:
                            raise ApiError("tool_round_limit")
                        yield {"native": output}
                        if calls:
                            yield {"tool_calls": calls}

        async for _ in log.async_add_delta_content_stream(agent_id, deltas()):
            pass
        if final is None:
            raise ApiError("incomplete_stream")
        if not log.unresponded_tool_results:
            return
    raise ApiError("tool_round_limit")
