"""Buffered STT for DeepSeek's explicitly non-streaming recognition API."""

from __future__ import annotations

import asyncio
import io
import time
import wave
from collections.abc import AsyncIterable

from homeassistant.components import stt
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from mutagen import MutagenError

from . import DeepSeekEntry
from .api import ApiError
from .const import MAX_AUDIO_BYTES, MAX_AUDIO_SECONDS, STT_LANGUAGES
from .entity import AgentEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: DeepSeekEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for subentry in entry.subentries.values():
        if subentry.subentry_type == "stt":
            async_add_entities(
                [DeepSeekSTT(entry, subentry)], config_subentry_id=subentry.subentry_id
            )


class DeepSeekSTT(stt.SpeechToTextEntity, AgentEntity):
    _attr_supported_languages = STT_LANGUAGES
    _attr_supported_formats = [stt.AudioFormats.WAV, stt.AudioFormats.OGG]
    _attr_supported_codecs = [stt.AudioCodecs.PCM, stt.AudioCodecs.OPUS]
    _attr_supported_bit_rates = [stt.AudioBitRates.BITRATE_16]
    _attr_supported_sample_rates = [
        stt.AudioSampleRates.SAMPLERATE_8000,
        stt.AudioSampleRates.SAMPLERATE_16000,
        stt.AudioSampleRates.SAMPLERATE_32000,
        stt.AudioSampleRates.SAMPLERATE_44100,
        stt.AudioSampleRates.SAMPLERATE_48000,
    ]
    _attr_supported_channels = [stt.AudioChannels.CHANNEL_MONO, stt.AudioChannels.CHANNEL_STEREO]

    def __init__(self, entry: DeepSeekEntry, subentry: ConfigSubentry) -> None:
        AgentEntity.__init__(self, entry, subentry)

    @property
    def supported_languages(self) -> list[str]:
        return self._attr_supported_languages

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        return self._attr_supported_formats

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        return self._attr_supported_codecs

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        return self._attr_supported_bit_rates

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        return self._attr_supported_sample_rates

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        return self._attr_supported_channels

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        runtime = self.entry.runtime_data
        started = time.monotonic()
        try:
            async with runtime.job(), asyncio.timeout(self.options["total_timeout"]), runtime.gate:
                if not self.check_metadata(metadata):
                    raise ApiError("unsupported_audio_metadata")
                raw = bytearray()
                async for chunk in stream:
                    raw.extend(chunk)
                    if len(raw) > MAX_AUDIO_BYTES - (
                        44 if metadata.codec == stt.AudioCodecs.PCM else 0
                    ):
                        raise ApiError("audio_too_large")
                if not raw:
                    raise ApiError("invalid_audio")
                if metadata.codec == stt.AudioCodecs.PCM:
                    frame_bytes = int(metadata.channel) * 2
                    if metadata.format != stt.AudioFormats.WAV or len(raw) % frame_bytes:
                        raise ApiError("invalid_audio")
                    if len(raw) / (int(metadata.sample_rate) * frame_bytes) > MAX_AUDIO_SECONDS:
                        raise ApiError("audio_too_long")
                    buffer = io.BytesIO()
                    with wave.open(buffer, "wb") as file:
                        file.setnchannels(int(metadata.channel))
                        file.setsampwidth(2)
                        file.setframerate(int(metadata.sample_rate))
                        file.writeframes(raw)
                    data = buffer.getvalue()
                    result = await runtime.api.transcribe(data, timeout=self.options["timeout"])
                elif (
                    metadata.codec == stt.AudioCodecs.OPUS
                    and metadata.format == stt.AudioFormats.OGG
                ):
                    # Validate granule duration with HA's audio metadata library.
                    from mutagen.oggopus import OggOpus

                    info = OggOpus(io.BytesIO(raw)).info
                    if (
                        info is None
                        or info.length > MAX_AUDIO_SECONDS
                        or info.channels not in (1, 2)
                    ):
                        raise ApiError("audio_too_long")
                    result = await runtime.api.transcribe(
                        bytes(raw), "ogg", timeout=self.options["timeout"]
                    )
                else:
                    raise ApiError("unsupported_audio")
                if (
                    not isinstance(result.get("text"), str)
                    or type(result.get("duration_ms")) not in (int, float)
                    or not 0 <= result["duration_ms"] <= 120000
                ):
                    raise ApiError("invalid_transcription")
                runtime.metrics.add(
                    requests=1,
                    stt_seconds=result["duration_ms"] / 1000,
                    latency_ms=(time.monotonic() - started) * 1000,
                )
                return stt.SpeechResult(result["text"], stt.SpeechResultState.SUCCESS)
        except (ApiError, TimeoutError, ValueError, OSError, MutagenError) as err:
            if isinstance(err, ApiError):
                runtime.handle_error(err)
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
