"""Native speech entities against simulated HTTP and actual local WebSockets."""

import asyncio
import io
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import httpx2 as httpx
import pytest
from aiohttp import web
from homeassistant.components import stt, tts
from homeassistant.components.tts.const import DATA_COMPONENT
from homeassistant.exceptions import HomeAssistantError
from test_native import entity_id
from yarl import URL

from custom_components.deepseek_ai.api import ApiError


async def chunks(*values):
    for value in values:
        yield value


@pytest.fixture
async def speech_server(aiohttp_server, socket_enabled):
    received = []
    behavior = {
        "code": "success",
        "origin": "wss://api.deepseek.com/v1/tools/tts",
        "hang": False,
        "done": asyncio.Event(),
    }

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        try:
            async for message in ws:
                event = message.json()
                received.append(event)
                if event["event"] == "text":
                    await ws.send_bytes(b"\x01\x00" * 20)
                if event["event"] == "finish_text":
                    behavior["done"].set()
                    if behavior["code"] == "close":
                        await ws.close()
                        break
                    if not behavior["hang"]:
                        await ws.send_json({"event": "finish", "code": behavior["code"]})
                        await ws.close()
        finally:
            await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/tts", handler)
    server = await aiohttp_server(app)
    async with aiohttp.ClientSession() as session:

        class MappedSocket:
            def __init__(self, socket):
                self.socket = socket
                self._response = SimpleNamespace(url=URL(behavior["origin"]))

            def __getattr__(self, name):
                return getattr(self.socket, name)

        class Session:
            @asynccontextmanager
            async def ws_connect(self, url, **kwargs):
                assert url.startswith("wss://api.deepseek.com/v1/tools/tts?")
                assert kwargs.pop("headers")["Authorization"].startswith("Bearer ")
                async with session.ws_connect(server.make_url("/tts"), **kwargs) as socket:
                    yield MappedSocket(socket)

        yield Session(), received, behavior


@pytest.mark.parametrize("voice", ["stella", "tide"])
async def test_tts_full_and_incremental_text(hass, entry, speech_server, voice):
    session, received, _ = speech_server
    entry.runtime_data.api.ws_session = session
    entity = hass.data[DATA_COMPONENT].get_entity(entity_id(hass, entry, "tts"))
    extension, audio = await entity.async_get_tts_audio("你好", "zh-CN", {"voice": voice})
    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.getframerate() == 24000 and wav.getnchannels() == 1
        assert wav.getnframes() == 20
    assert extension == "wav"
    response = await entity.async_stream_tts_audio(
        tts.TTSAudioRequest(
            language="zh-CN", options={"voice": voice}, message_gen=chunks("你", "好")
        )
    )
    streamed = b"".join([part async for part in response.data_gen])
    assert streamed.startswith(b"RIFF") and len(streamed) == 44 + 80
    assert [event["text"] for event in received if event["event"] == "text"] == ["你好", "你", "好"]
    assert entry.runtime_data.metrics.values["tts_characters"] == 4


@pytest.mark.parametrize("failure", ["close", "failed", "redirect"])
async def test_tts_failure_and_unexpected_origin(hass, entry, speech_server, failure):
    session, received, behavior = speech_server
    if failure == "redirect":
        behavior["origin"] = "wss://attacker.invalid/v1/tools/tts"
    else:
        behavior["code"] = failure
    entry.runtime_data.api.ws_session = session
    entity = hass.data[DATA_COMPONENT].get_entity(entity_id(hass, entry, "tts"))
    with pytest.raises(HomeAssistantError):
        await entity.async_get_tts_audio("PRIVATE_HOME", "zh-CN", {})
    if failure == "redirect":
        assert received == []


async def test_tts_sender_failure_does_not_wait_for_server(entry, speech_server):
    session, _, _ = speech_server
    entry.runtime_data.api.ws_session = session
    with pytest.raises(ApiError, match="tts_text_too_large"):
        async with asyncio.timeout(2):
            _ = [
                data async for data in entry.runtime_data.api.speech(chunks("x" * 10001), "stella")
            ]


async def test_tts_cancel_closes_socket(entry, speech_server):
    session, received, behavior = speech_server
    behavior["hang"] = True
    entry.runtime_data.api.ws_session = session

    async def consume():
        return [data async for data in entry.runtime_data.api.speech(chunks("hello"), "tide")]

    job = asyncio.create_task(consume())
    async with asyncio.timeout(2):
        await behavior["done"].wait()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job


def metadata():
    return stt.SpeechMetadata(
        language="zh-CN",
        format=stt.AudioFormats.WAV,
        codec=stt.AudioCodecs.PCM,
        bit_rate=stt.AudioBitRates.BITRATE_16,
        sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
        channel=stt.AudioChannels.CHANNEL_MONO,
    )


async def test_stt_wraps_pcm_and_uses_timeout(hass, entry, provider):
    entity = stt.async_get_speech_to_text_entity(hass, entity_id(hass, entry, "stt"))
    entity.options["timeout"] = 17
    provider.queue.append(httpx.Response(200, json={"text": "你好", "duration_ms": 1000}))
    result = await entity.internal_async_process_audio_stream(metadata(), chunks(b"\0\0" * 16000))
    assert result.result is stt.SpeechResultState.SUCCESS and result.text == "你好"
    request = provider.requests[-1]
    assert request.url.path == "/v1/tools/asr"
    assert b"RIFF" in request.content and b"WAVE" in request.content
    assert request.extensions["timeout"]["read"] == 17


@pytest.mark.parametrize("case", ["duration", "size", "odd", "bad_ogg"])
async def test_stt_rejects_invalid_recording_before_upload(hass, entry, provider, case):
    entity = stt.async_get_speech_to_text_entity(hass, entity_id(hass, entry, "stt"))
    data = {
        "duration": b"\0\0" * (16000 * 120 + 1),
        "size": b"\0" * (8 * 1024 * 1024),
        "odd": b"x",
        "bad_ogg": b"bad ogg",
    }[case]
    meta = metadata()
    if case == "bad_ogg":
        meta.format, meta.codec = stt.AudioFormats.OGG, stt.AudioCodecs.OPUS
    count = len(provider.requests)
    result = await entity.internal_async_process_audio_stream(meta, chunks(data))
    assert result.result is stt.SpeechResultState.ERROR
    assert len(provider.requests) == count


async def test_stt_valid_ogg_opus(hass, entry, provider):
    entity = stt.async_get_speech_to_text_entity(hass, entity_id(hass, entry, "stt"))
    meta = metadata()
    meta.codec, meta.format = stt.AudioCodecs.OPUS, stt.AudioFormats.OGG
    meta.sample_rate = stt.AudioSampleRates.SAMPLERATE_48000
    provider.queue.append(httpx.Response(200, json={"text": "", "duration_ms": 100}))
    audio = (Path(__file__).parent / "fixtures/silence.ogg").read_bytes()
    result = await entity.internal_async_process_audio_stream(meta, chunks(audio))
    assert result.result is stt.SpeechResultState.SUCCESS
    assert audio in provider.requests[-1].content


async def test_stream_consumer_close_releases_sender_and_runtime(hass, entry, speech_server):
    session, _, behavior = speech_server
    behavior["hang"] = True
    entry.runtime_data.api.ws_session = session
    entity = hass.data[DATA_COMPONENT].get_entity(entity_id(hass, entry, "tts"))
    response = await entity.async_stream_tts_audio(
        tts.TTSAudioRequest(language="zh-CN", options={}, message_gen=chunks("Hello"))
    )
    assert (await anext(response.data_gen)).startswith(b"RIFF")
    assert await anext(response.data_gen)
    await response.data_gen.aclose()
    assert not entry.runtime_data.jobs
