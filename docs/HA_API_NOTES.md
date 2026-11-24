# Home Assistant API notes

Checked 2026-11-24 for `deepseek_ai`. Python environment: `.venv/bin/python` → `.venv/bin/python3.14` → `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14`.

**Version boundary:** the initial interface investigation used Core **2026.11.3**, commit `92da9f154079459b9e547126f9bd9fce726de16a`. Minimum support is now **2026.11.2**, commit `ff5d56b825a0fb66b03d01bc297d49e206cdaba3`: the complete 96-test suite, native setup and all AI/speech hooks were executed using real `homeassistant==2026.11.2` and `pytest-homeassistant==2026.11.2`. The signatures documented below remain compatible. CI runs both patch versions. No live provider requests were made.

## Conversation and provider state

`ConversationEntity._async_handle_message(self, user_input: ConversationInput, chat_log: ChatLog) -> ConversationResult` is the platform hook. Call `chat_log.async_provide_llm_data(user_input.as_llm_context(DOMAIN), selected_api_ids, prompt, user_input.extra_system_prompt)` before transport. This preserves caller authorization. Finish with `conversation.async_get_result_from_chat_log(user_input, chat_log)`. Set `_attr_supports_streaming = True`; set `ConversationEntityFeature.CONTROL` when tools are enabled. [Official entity example](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/openai_conversation/conversation.py)

`conversation.async_get_chat_log(hass, session: ChatSession, user_input: ConversationInput | None = None, *, chat_log_delta_listener=None) -> Generator[ChatLog]` is a synchronous context manager: use `with`, not `async with`; pass a ChatSession, not a conversation-ID string.

`ChatLog` has **no `provider_data` field**. `AssistantContent.native: Any` can retain provider-native records without exposing them through `as_dict`. `AssistantContent.thinking_content` is the reasoning-text field. Native data remains session-local, so do not assume persistence across restart. [ChatLog source](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/conversation/chat_log.py)

## ChatLog stream protocol

`async_add_delta_content_stream(agent_id, stream: AsyncIterable[AssistantContentDeltaDict | ToolResultContentDeltaDict]) -> AsyncGenerator[AssistantContent | ToolResultContent]`:

- Start a message with `{"role": "assistant"}`. A new `role` key closes the preceding message.
- Subsequent deltas omit `role`; valid keys are `content`, `thinking_content`, `tool_calls`, `native`.
- Text/thinking concatenate; tool lists concatenate. `native` can be set once per message, not incrementally overwritten.
- `tool_calls` contains complete `llm.ToolInput` values. HA starts non-external calls as soon as each arrives. Do not yield an incomplete argument JSON or a tool from a truncated/failed provider response.
- `external=True` means provider-executed tools, not HA actions. Their results can use `role="tool_result"`, `tool_call_id`, `tool_name`, `result=llm.ToolResult(...)`.
- Exhaust/collect the returned generator; it drives actual tool execution and yields results for the next provider request.

Engineering choice: buffer completed tool calls until the provider turn's terminal success event, then emit them. This prevents unconfirmed SSE data from acting on devices. Never replay the whole tool round after a model-network failure. [ChatLog stream implementation](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/conversation/chat_log.py)

## HTTP client compatibility

`homeassistant/__init__.py` imports `httpx2` and immediately calls `httpx2.alias_httpx()`, aliasing legacy `httpx` / `httpcore` imports to `httpx2` / `httpcore2` before integrations load. Core bans new `httpx` imports in its lint configuration; prefer `import httpx2` in new integration transport code. Avoid importing old `httpx` before `homeassistant` in test startup, which can retain pre-alias class references. `get_async_client(hass, verify_ssl=True, alpn_protocols=SSL_ALPN_HTTP11) -> httpx2.AsyncClient` returns a HA-owned shared client; do not close it. [HA package initialization](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/__init__.py), [HTTP helper](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/helpers/httpx_client.py)

## Text-to-speech

`TTSAudioRequest(language: str, options: dict[str, Any], message_gen: AsyncGenerator[str])`; `TTSAudioResponse(extension: str, data_gen: AsyncGenerator[bytes])`.

Override `async_stream_tts_audio(self, request) -> TTSAudioResponse` for incremental text/audio. The default collects all `message_gen` text, calls `async_get_tts_audio(message, language, options)`, then yields one audio chunk. Implement both paths for direct full-text playback and streaming. Response has no sample-rate metadata field. [TTS entity source](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/tts/entity.py)

Raw PCM has a separate HA path: `PcmFormat(sample_rate, sample_width, channels)` describes little-endian PCM; `ResultStream.async_set_audio_stream(pcm_format, audio_stream)` feeds it with format metadata. `TTSAudioResponse("pcm", ...)` alone lacks that metadata. For a TTS entity use a supported encoded stream or a WAV header with correct PCM format and streaming size placeholders; HA can parse streaming WAV. Avoid treating `preferred_sample_rate` as provider audio metadata. [TTS manager source](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/tts/__init__.py)

## Config entries and subentries

Initial `ConfigFlow.async_create_entry(title=..., data=..., subentries=[...])`; each subentry dictionary needs `data`, `subentry_type`, `title`, `unique_id` (can be `None`). HA assigns ID. Expose types through classmethod `async_get_supported_subentry_types(cls, config_entry) -> dict[str, type[ConfigSubentryFlow]]`. `ConfigSubentryFlow._subentry_type` is an existing property returning `self.handler[1]`.

`ConfigSubentry` is frozen/keyword-only; data is `MappingProxyType`. Updates use `hass.config_entries.async_update_subentry(entry, subentry, *, data=..., title=..., unique_id=...) -> bool`, which fires listeners. Reconfigure flows use `async_update_and_abort` / `async_update_reload_and_abort`, not `async_create_entry`. [Config entry source](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/config_entries.py)

Platform setup iterates `config_entry.subentries.values()` and calls `async_add_entities([entity], config_subentry_id=subentry.subentry_id)`. Register per-subentry unique IDs. Shared runtime client belongs to `ConfigEntry.runtime_data`. [Official setup example](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/openai_conversation/ai_task.py)

## AI task generation and evaluation

`GenDataTask(name, instructions, structure=None, attachments=None, llm_api=None)` has **no context field**. HA supplies caller `Context` separately to `AITaskEntity.internal_async_generate_data(session, task, context=None)`; its chat-log setup applies that context. `_async_generate_data` receives the prepared chat log. Do not construct `GenDataTask(context=...)`.

`AITaskEntity._async_generate_data(self, task: GenDataTask, chat_log: ChatLog) -> GenDataTaskResult`; `GenDataTaskResult(conversation_id=..., data=...)`. Set `GENERATE_DATA | SUPPORT_ATTACHMENTS`, never `GENERATE_IMAGE` for this scope. `task.structure` is a HA schema, not already a raw JSON schema. Convert with HA's schema serializer and validate the parsed response. [AI entity source](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/ai_task/entity.py), [official generation example](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/openai_conversation/ai_task.py)

Evaluation hook: `_async_evaluate(self, task: EvaluationTask) -> EvaluationTaskResult` (no ChatLog argument). Types below are verified against the exact 2026.11.3 tag:

| Type | Fields |
|---|---|
| `EvaluationTask` | `name`, `questions: dict[str, EvaluationQuestion]`, `state=None`, `attachments=None` |
| `NoulQuestion` | `type="noul"`, `instructions` |
| `ChoiceQuestion` | `type="choice"`, `instructions`, `criteria: dict[str,str]` |
| `ScoreQuestion` | `type="score"`, `instructions`, `criteria: list[str]` |
| `NoulAnswer` | `noul: float` |
| `ChoiceAnswer` | `choice: str`, `probabilities: dict[str,float]` |
| `ScoreAnswer` | `score: float`, `probabilities: list[float]` |
| `EvaluationTaskResult` | `answers: dict[str, EvaluationAnswer]`; `as_dict()` serializes dataclasses |

Question classes are `TypedDict` (ordinary dictionaries at runtime): construct with explicit `type="score"` / `"choice"` / `"noul"`, access fields with `question["type"]` / `question["criteria"]`, and serialize dictionaries directly; `dataclasses.asdict(question)` is invalid. Answer classes and `EvaluationTask`/`EvaluationTaskResult` are dataclasses. Answer `type` is assigned by dataclass (`init=False`), so omit it from answer constructors. Validate finite probabilities/range/normalization and exact options/level count yourself; dataclass construction does not provide these checks. HA question schema requires at least two choice/score criteria. [Evaluation types, exact target](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/ai_task/evaluation.py)

Set `EVALUATE | SUPPORT_ATTACHMENTS` only on opt-in experimental evaluation entities. Do not modify HA's preferred evaluation or automatic-evaluation preference. [AI preferences](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/ai_task/__init__.py)

## Exact-version test environment

The legacy `pytest-homeassistant-custom-component` release pins an older HA version. This project instead uses the new official `pytest-homeassistant==2026.11.2` baseline, whose entry point loads genuine HA fixtures, registries, storage, authentication, entities and services. Our fixture provides an isolated temporary configuration directory with a `custom_components` symlink and initializes the native `homeassistant` component before conversation setup. It substitutes only the remote provider HTTP/SSE/WebSocket boundary. No HA replacement stubs, dependency fallbacks, or silently skipped tests are used.

Local WebSocket tests bind only `127.0.0.1`; a transport adapter maps the official URL to that local server and retains the logical provider origin. This adapter lives only in tests. Production cannot configure a custom endpoint. Malicious-origin tests assert that no text is sent after an unexpected handshake origin.

Camera tests use the real camera component and media-source resolver with a test camera returning a generated PNG. Ogg Opus tests use locally generated silence. No actual microphone, camera, speaker or home device is contacted.

Official exact-tag hassfest plugins are run by `scripts/check_metadata.py --ha-source /path/to/core-2026.11.2` against the installed target package. Selected plugins: manifest, JSON, config schema, integration type, translations and config flow. Source checkout must include `script/hassfest` and `packages/hassfest`; the checker is not replaced or rewritten.

[Official helper package](https://github.com/home-assistant/core/tree/92da9f154079459b9e547126f9bd9fce726de16a/packages/pytest-homeassistant), [official hassfest source](https://github.com/home-assistant/core/tree/92da9f154079459b9e547126f9bd9fce726de16a/script/hassfest)
