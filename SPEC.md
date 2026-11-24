# DeepSeek AI v0.1.0

User-approved implementation scope, 2026-11-24.

- Independent `deepseek_ai` custom integration. Minimum Home Assistant 2026.11.3; official DeepSeek endpoints only. No existing instance changes or publication.
- One credentials entry, multiple conversation, generation, experimental evaluation, STT and TTS subentries.
- Streaming multi-turn Responses API conversation, HA tools executed by ChatLog with caller permissions; no tools on AI tasks/evaluations. Web search/fetch agents cannot select HA tools.
- Native conversation.process, ai_task.generate_data, ai_task.evaluate, tts.speak. Strict structured results including images and files. Evaluation types noul/choice/score, opt-in, not calibrated or automatically selected.
- Images/cameras and official document/spreadsheet/text formats; bounded attachments, owned uploaded-file lifecycle and restart cleanup.
- STT WAV/Opus, official 8 MiB/120 s limits. TTS full text and WebSocket streaming, Stella/Tide; no unsupported speed/emotion options.
- Default Flash, thinking off; optional Pro and supported effort; 10 tool rounds by default, bounded timeout/concurrency/history. No automatic device action replay after failure.
- Authentication recovery, reconfigure/unload, safe diagnostics/repairs, persistent usage/latency and reset. No payloads, credentials or sensitive content in logs. No paid debug probes.
- English and Simplified Chinese UI, Chinese guide, HACS-compatible project and ZIP/checksum.
- No image generation, code execution, OpenAI-only settings, custom endpoints, live keys or real devices.

## Agreed test boundaries

Tests exercise native HA config flows and public entity/actions, real HA tool authorization, transport over simulated HTTP/SSE/WebSocket, storage lifecycle, diagnostics and release artifact. Real HA dependency is mandatory: no replacement HA stubs or silently skipped core tests. Cover cancellation/truncation/limits, schema and probability failures, permissions, no action replay, file cleanup and log redaction. Record any unavailable dependencies or unverified actual API/device behavior honestly.

## Standards

Use HA public APIs, typed asynchronous Python, small modules separating transport from HA orchestration. Validate remote payloads and finish events before declaring success. Fixed HTTPS/WSS hosts and no cross-host authenticated redirects. Only explicitly owned remote files may be deleted. Do not log provider payloads or exception bodies. Avoid private upstream integration inheritance, generic speculative backends and duplicated generation services.
