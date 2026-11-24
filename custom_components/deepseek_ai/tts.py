"""Full-message and incremental-text speech, with explicit provider finish check."""

from __future__ import annotations

import asyncio
import struct
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Any

from homeassistant.components import tts
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeepSeekEntry
from .api import ApiError
from .const import TTS_LANGUAGES
from .entity import AgentEntity

WAV_HEADER = struct.pack(
    "<4sI4s4sIHHIIHH4sI",
    b"RIFF",
    0xFFFFFFFF,
    b"WAVE",
    b"fmt ",
    16,
    1,
    1,
    24000,
    48000,
    2,
    16,
    b"data",
    0xFFFFFFFF,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: DeepSeekEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for subentry in entry.subentries.values():
        if subentry.subentry_type == "tts":
            async_add_entities(
                [DeepSeekTTS(entry, subentry)], config_subentry_id=subentry.subentry_id
            )


class DeepSeekTTS(tts.TextToSpeechEntity, AgentEntity):
    _attr_supported_languages = TTS_LANGUAGES
    _attr_default_language = "zh-CN"
    _attr_supported_options = [tts.ATTR_VOICE]

    def __init__(self, entry: DeepSeekEntry, subentry: ConfigSubentry) -> None:
        AgentEntity.__init__(self, entry, subentry)
        self._attr_default_options = {tts.ATTR_VOICE: self.options["voice"]}

    def async_get_supported_voices(self, language: str) -> list[tts.Voice]:
        return [tts.Voice("stella", "Stella"), tts.Voice("tide", "Tide")]

    async def _audio(
        self, messages: AsyncIterator[str], options: dict[str, Any]
    ) -> AsyncGenerator[bytes]:
        runtime = self.entry.runtime_data
        started = time.monotonic()
        voice = options.get(tts.ATTR_VOICE, self.options["voice"])
        try:
            async with runtime.job(), asyncio.timeout(self.options["total_timeout"]), runtime.gate:
                yield WAV_HEADER
                byte_count = 0
                characters = 0

                def record(count: int) -> None:
                    nonlocal characters
                    characters = count

                async with aclosing(
                    runtime.api.speech(
                        messages, voice, timeout=self.options["timeout"], on_characters=record
                    )
                ) as audio:
                    async for chunk in audio:
                        byte_count += len(chunk)
                        if byte_count > 24_000 * 2 * 1800:
                            raise ApiError("audio_too_large")
                        yield chunk
                if not byte_count or byte_count % 2:
                    raise ApiError("invalid_audio_stream")
                runtime.metrics.add(
                    requests=1,
                    tts_characters=characters,
                    latency_ms=(time.monotonic() - started) * 1000,
                )
        except (ApiError, TimeoutError) as err:
            if isinstance(err, ApiError):
                runtime.handle_error(err)
            raise HomeAssistantError(
                str(err) if isinstance(err, ApiError) else "DeepSeek speech timed out"
            ) from None

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> tuple[str, bytes]:
        async def messages() -> AsyncGenerator[str]:
            yield message

        data = b"".join([chunk async for chunk in self._audio(messages(), options)])
        # Full-message consumers need a finite RIFF length for ordinary readers.
        size = len(data) - len(WAV_HEADER)
        header = bytearray(WAV_HEADER)
        struct.pack_into("<I", header, 4, size + 36)
        struct.pack_into("<I", header, 40, size)
        return "wav", bytes(header) + data[len(WAV_HEADER) :]

    async def async_stream_tts_audio(self, request: tts.TTSAudioRequest) -> tts.TTSAudioResponse:
        return tts.TTSAudioResponse(
            extension="wav", data_gen=self._audio(request.message_gen, request.options)
        )
