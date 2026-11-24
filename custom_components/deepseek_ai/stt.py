"""Buffered STT for DeepSeek's explicitly non-streaming recognition API."""

import asyncio
import io
import time
import wave

from homeassistant.components import stt

from .api import ApiError
from .const import MAX_AUDIO_BYTES, MAX_AUDIO_SECONDS, STT_LANGUAGES
from .entity import AgentEntity


async def async_setup_entry(hass, entry, async_add_entities):
    for subentry in entry.subentries.values():
        if subentry.subentry_type == "stt":
            async_add_entities([DeepSeekSTT(entry, subentry)], config_subentry_id=subentry.subentry_id)


class DeepSeekSTT(stt.SpeechToTextEntity, AgentEntity):
    _attr_supported_languages = STT_LANGUAGES
    _attr_supported_formats = [stt.AudioFormats.WAV, stt.AudioFormats.OGG]
    _attr_supported_codecs = [stt.AudioCodecs.PCM, stt.AudioCodecs.OPUS]
    _attr_supported_bit_rates = [stt.AudioBitRates.BITRATE_16]
    _attr_supported_sample_rates = [stt.AudioSampleRates.SAMPLERATE_16000, stt.AudioSampleRates.SAMPLERATE_48000]
    _attr_supported_channels = [stt.AudioChannels.CHANNEL_MONO]

    def __init__(self, entry, subentry):
        AgentEntity.__init__(self, entry, subentry)

    async def async_process_audio_stream(self, metadata, stream):
        runtime = self.entry.runtime_data
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.options["total_timeout"]), runtime.gate:
                raw = bytearray()
                async for chunk in stream:
                    raw.extend(chunk)
                    if len(raw) > MAX_AUDIO_BYTES - 44:
                        raise ApiError("audio_too_large")
                if metadata.codec == stt.AudioCodecs.PCM:
                    if metadata.format != stt.AudioFormats.WAV or len(raw) % 2:
                        raise ApiError("invalid_audio")
                    if len(raw) / (int(metadata.sample_rate) * 2) > MAX_AUDIO_SECONDS:
                        raise ApiError("audio_too_long")
                    buffer = io.BytesIO()
                    with wave.open(buffer, "wb") as file:
                        file.setnchannels(1)
                        file.setsampwidth(2)
                        file.setframerate(int(metadata.sample_rate))
                        file.writeframes(raw)
                    data = buffer.getvalue()
                    result = await runtime.api.transcribe(data)
                elif metadata.codec == stt.AudioCodecs.OPUS and metadata.format == stt.AudioFormats.OGG:
                    # Validate granule duration with HA's audio metadata library.
                    from mutagen.oggopus import OggOpus
                    info = OggOpus(io.BytesIO(raw)).info
                    if info.length > MAX_AUDIO_SECONDS:
                        raise ApiError("audio_too_long")
                    result = await runtime.api.transcribe(bytes(raw), "ogg")
                else:
                    raise ApiError("unsupported_audio")
                if not isinstance(result.get("text"), str) or not isinstance(result.get("duration_ms"), (int, float)) or not 0 <= result["duration_ms"] <= 120000:
                    raise ApiError("invalid_transcription")
                runtime.metrics.add(requests=1, stt_seconds=result["duration_ms"] / 1000, latency_ms=(time.monotonic() - started) * 1000)
                return stt.SpeechResult(result["text"], stt.SpeechResultState.SUCCESS)
        except (ApiError, TimeoutError, ValueError, OSError) as err:
            if isinstance(err, ApiError):
                runtime.handle_error(err)
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

