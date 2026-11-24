"""Bounded, non-retrying transport to the official DeepSeek endpoints only."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import aiohttp
import httpx2 as httpx

from .const import API_ROOT, MAX_EVENT_BYTES, MAX_RESPONSE_BYTES, TTS_URL


class ApiError(Exception):
    """Sanitized provider failure; never retains response bodies or credentials."""

    def __init__(self, code: str, status: int = 0) -> None:
        self.code = code
        self.status = status
        super().__init__(f"DeepSeek: {code}" + (f" ({status})" if status else ""))


class DeepSeekClient:
    """Uses a borrowed HA HTTP client. No configurable host, redirects or retries."""

    def __init__(self, http: httpx.AsyncClient, key: str, ws_session: aiohttp.ClientSession | None = None) -> None:
        self.http = http
        self._key = key
        self.ws_session = ws_session

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}

    @staticmethod
    def _status(status: int) -> None:
        if not 200 <= status < 300:
            code = {401: "invalid_auth", 403: "access_denied", 402: "insufficient_balance", 429: "rate_limited"}.get(status, "http_error")
            raise ApiError(code, status)

    async def _json(self, method: str, path: str, *, timeout: float = 60, **kwargs: Any) -> Any:
        try:
            async with self.http.stream(method, API_ROOT + path, headers=self._headers(), timeout=timeout, follow_redirects=False, **kwargs) as response:
                self._status(response.status_code)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise ApiError("response_too_large")
                result = json.loads(data)
                if isinstance(result, dict) and result.get("error"):
                    raise ApiError("provider_error")
                return result
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeError):
            raise ApiError("invalid_or_unavailable_response") from None

    async def validate_key(self) -> None:
        await self._json("GET", "/models", timeout=10)

    async def responses(self, body: dict[str, Any], *, timeout: float = 60) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE events, requiring a completed terminal response, not clean EOF."""
        try:
            async with self.http.stream("POST", API_ROOT + "/responses", json={**body, "stream": True}, headers=self._headers(), timeout=timeout, follow_redirects=False) as response:
                self._status(response.status_code)
                buffer: list[str] = []
                size = 0
                total = 0
                terminal = False
                async for line in response.aiter_lines():
                    total += len(line.encode())
                    if total > MAX_RESPONSE_BYTES:
                        raise ApiError("response_too_large")
                    if line.startswith("data:"):
                        value = line[5:].lstrip()
                        size += len(value.encode())
                        if size > MAX_EVENT_BYTES:
                            raise ApiError("event_too_large")
                        buffer.append(value)
                    elif not line and buffer:
                        event = json.loads("\n".join(buffer))
                        buffer, size = [], 0
                        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                            raise ApiError("invalid_event")
                        kind = event["type"]
                        if kind in ("response.failed", "response.incomplete", "error"):
                            raise ApiError("response_failed_or_truncated")
                        if kind == "response.completed":
                            result = event.get("response", {})
                            if not isinstance(result, dict) or result.get("status") != "completed" or not isinstance(result.get("output"), list):
                                raise ApiError("invalid_completion")
                            terminal = True
                        yield event
                        if terminal:
                            return
                raise ApiError("incomplete_stream")
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeError):
            raise ApiError("invalid_or_unavailable_stream") from None

    async def search(self, query: str, count: int = 5) -> dict[str, Any]:
        if not query.strip() or len(query) > 128 or not 1 <= count <= 10:
            raise ApiError("invalid_search")
        result = await self._json("POST", "/v1/tools/search", json={"query": query, "count": count})
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise ApiError("invalid_search_result")
        return {"results": [{k: row[k] for k in ("title", "url", "summary", "snippet", "site_name", "date") if k in row} for row in result["results"][:count] if isinstance(row, dict)]}

    async def fetch(self, url: str) -> dict[str, Any]:
        from urllib.parse import urlsplit

        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or len(url) > 8192:
            raise ApiError("invalid_url")
        result = await self._json("POST", "/v1/tools/fetch", json={"url": url})
        if not isinstance(result, dict) or not isinstance(result.get("content"), str):
            raise ApiError("invalid_fetch_result")
        return {"url": url, "title": str(result.get("title", "")), "content": result["content"][:50000]}

    async def upload(self, filename: str, content: bytes, mime: str, purpose: str) -> str:
        result = await self._json("POST", "/files", timeout=300, data={"purpose": purpose}, files={"file": (filename, content, mime)})
        file_id = result.get("id") if isinstance(result, dict) else None
        if not isinstance(file_id, str) or not file_id.startswith("file-"):
            raise ApiError("invalid_file_response")
        return file_id

    async def list_files(self) -> list[dict[str, Any]]:
        result = await self._json("GET", "/files")
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise ApiError("invalid_file_list")
        return [item for item in result["data"] if isinstance(item, dict)]

    async def delete_file(self, file_id: str) -> None:
        if not file_id.startswith("file-") or not file_id.replace("-", "").replace("_", "").isalnum():
            raise ApiError("invalid_file_id")
        try:
            await self._json("DELETE", "/files/" + file_id)
        except ApiError as err:
            if err.status != 404:
                raise

    async def transcribe(self, audio: bytes, extension: str = "wav") -> dict[str, Any]:
        if extension not in ("wav", "ogg") or not 0 < len(audio) <= 8 * 1024 * 1024:
            raise ApiError("invalid_audio")
        result = await self._json("POST", "/v1/tools/asr", files={"file": ("speech." + extension, audio, "audio/" + extension)}, timeout=120)
        if not isinstance(result, dict) or not isinstance(result.get("text"), str) or not isinstance(result.get("duration_ms"), (int, float)):
            raise ApiError("invalid_transcription")
        return result

    async def speech(self, messages: AsyncIterator[str], voice: str, *, timeout: float = 60, on_characters: Callable[[int], None] | None = None) -> AsyncIterator[bytes]:
        """Stream signed 16-bit mono 24 kHz PCM; only finish/success means success."""
        if self.ws_session is None or voice not in ("stella", "tide"):
            raise ApiError("invalid_voice_or_session")
        try:
            async with self.ws_session.ws_connect(TTS_URL + "&voice_id=" + voice, headers=self._headers(), heartbeat=25, max_msg_size=4 * 1024 * 1024) as ws:
                async def send() -> None:
                    characters = 0
                    total_bytes = 0
                    async for text in messages:
                        if not isinstance(text, str):
                            raise ApiError("invalid_tts_text")
                        characters += sum(2 if "\u4e00" <= ch <= "\u9fff" else 1 for ch in text)
                        total_bytes += len(text.encode())
                        if characters > 10000 or total_bytes > 65536:
                            raise ApiError("tts_text_too_large")
                        await ws.send_json({"event": "text", "text": text})
                    await ws.send_json({"event": "finish_text"})
                    if on_characters:
                        on_characters(characters)

                sender = asyncio.create_task(send())
                try:
                    while True:
                        if sender.done():
                            sender.result()
                        message = await asyncio.wait_for(ws.receive(), timeout)
                        if message.type == aiohttp.WSMsgType.BINARY:
                            yield message.data
                        elif message.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(message.data)
                            if event.get("event") == "finish":
                                if event.get("code") != "success":
                                    raise ApiError("speech_failed")
                                await sender
                                return
                        elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            raise ApiError("incomplete_audio_stream")
                finally:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
        except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError, UnicodeError):
            raise ApiError("speech_unavailable") from None
