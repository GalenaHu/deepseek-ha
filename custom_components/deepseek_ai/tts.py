"""Full-message and incremental-text speech, with explicit provider finish check."""

import asyncio
import struct
import time

from homeassistant.components import tts
from homeassistant.exceptions import HomeAssistantError

from .api import ApiError
from .const import TTS_LANGUAGES
from .entity import AgentEntity

WAV_HEADER = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 0xFFFFFFFF, b"WAVE", b"fmt ", 16, 1, 1, 24000, 48000, 2, 16, b"data", 0xFFFFFFFF)


async def async_setup_entry(hass, entry, async_add_entities):
    for subentry in entry.subentries.values():
        if subentry.subentry_type == "tts":
            async_add_entities([DeepSeekTTS(entry, subentry)], config_subentry_id=subentry.subentry_id)


class DeepSeekTTS(tts.TextToSpeechEntity, AgentEntity):
    _attr_supported_languages = TTS_LANGUAGES
    _attr_default_language = "zh-CN"
    _attr_supported_options = [tts.ATTR_VOICE]

    def __init__(self, entry, subentry):
        AgentEntity.__init__(self, entry, subentry)
        self._attr_default_options = {tts.ATTR_VOICE: self.options["voice"]}

    def async_get_supported_voices(self, language):
        return [tts.Voice("stella", "Stella"), tts.Voice("tide", "Tide")]

    async def _audio(self, messages, options):
        runtime = self.entry.runtime_data
        started = time.monotonic()
        voice = options.get(tts.ATTR_VOICE, self.options["voice"])
        try:
            async with asyncio.timeout(self.options["total_timeout"]), runtime.gate:
                yield WAV_HEADER
                byte_count = 0
                characters = 0
                def record(count):
                    nonlocal characters
                    characters = count
                async for chunk in runtime.api.speech(messages, voice, timeout=self.options["timeout"], on_characters=record):
                    byte_count += len(chunk)
                    if byte_count > 24_000 * 2 * 1800:
                        raise ApiError("audio_too_large")
                    yield chunk
                if not byte_count or byte_count % 2:
                    raise ApiError("invalid_audio_stream")
                runtime.metrics.add(requests=1, tts_characters=characters, latency_ms=(time.monotonic() - started) * 1000)
        except (ApiError, TimeoutError) as err:
            if isinstance(err, ApiError):
                runtime.handle_error(err)
            raise HomeAssistantError(str(err) if isinstance(err, ApiError) else "DeepSeek speech timed out") from None

    async def async_get_tts_audio(self, message, language, options):
        async def messages():
            yield message
        data = b"".join([chunk async for chunk in self._audio(messages(), options)])
        # Full-message consumers need a finite RIFF length for ordinary readers.
        size = len(data) - len(WAV_HEADER)
        header = bytearray(WAV_HEADER)
        struct.pack_into("<I", header, 4, size + 36)
        struct.pack_into("<I", header, 40, size)
        return "wav", bytes(header) + data[len(WAV_HEADER):]

    async def async_stream_tts_audio(self, request):
        return tts.TTSAudioResponse(extension="wav", data_gen=self._audio(request.message_gen, request.options))
