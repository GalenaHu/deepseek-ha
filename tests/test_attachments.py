"""HA-authorized attachment combinations and durable upload ownership."""

import base64
import json

import httpx2 as httpx
import probatio
import pytest
from homeassistant.components import ai_task, conversation
from homeassistant.components.ai_task.const import DATA_COMPONENT
from homeassistant.core import Context
from homeassistant.helpers.chat_session import async_get_chat_session
from test_native import entity_id

from custom_components.deepseek_ai.api import ApiError
from custom_components.deepseek_ai.attachments import Attachments

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


async def test_native_task_image_document_and_full_schema(hass, entry, provider, tmp_path):
    image, document = tmp_path / "frame.png", tmp_path / "scan.pdf"
    image.write_bytes(PNG)
    document.write_bytes(b"%PDF-1.4 simulated provider parser input")
    attachments = [
        conversation.Attachment("media-source://authorized/image", "image/png", image),
        conversation.Attachment("media-source://authorized/document", "application/pdf", document),
    ]
    provider.queue.append(httpx.Response(200, json={"id": "file-api-owned"}))
    provider.complete('{"present":true}')
    entity = hass.data[DATA_COMPONENT].get_entity(entity_id(hass, entry, "ai_task"))
    with async_get_chat_session(hass, context=Context()) as session:
        result = await entity.internal_async_generate_data(
            session,
            ai_task.GenDataTask(
                name="combo",
                instructions="Analyze image and scanned document",
                structure=probatio.Schema({probatio.Required("present"): bool}),
                attachments=attachments,
            ),
        )
        assert result.data == {"present": True}
        body = json.loads(provider.requests[-1].content)
        assert "tools" not in body
        parts = body["input"][-1]["content"]
        assert {p["type"] for p in parts} == {"input_text", "input_image", "input_file"}
        upload = next(r for r in provider.requests if r.method == "POST" and r.url.path == "/files")
        assert upload.content.index(b"rich_layout_recognition") < upload.content.index(b"%PDF")
        assert body["text"]["format"]["schema"]["required"] == ["present"]
        provider.queue.append(httpx.Response(200, json={"deleted": True}))
        await entry.runtime_data.attachments.cleanup(session.conversation_id)
    assert not entry.runtime_data.attachments.owned


@pytest.mark.parametrize(
    "suffix,purpose",
    [
        (".txt", "user_data"),
        (".xlsx", "user_data"),
        (".pdf", "rich_layout_recognition"),
        (".docx", "rich_layout_recognition"),
    ],
)
async def test_file_type_selects_official_parser(hass, entry, provider, tmp_path, suffix, purpose):
    file = tmp_path / ("input" + suffix)
    file.write_bytes(b"fixture")
    provider.queue.append(httpx.Response(200, json={"id": "file-api-owned"}))
    result = await entry.runtime_data.attachments.parts(
        [conversation.Attachment("media-source://authorized", "application/octet-stream", file)],
        "fixture",
        "deepseek-flash",
    )
    assert result == [{"type": "input_file", "file_id": "file-api-owned"}]
    assert purpose.encode() in provider.requests[-1].content
    provider.queue.append(httpx.Response(200, json={"deleted": True}))
    await entry.runtime_data.attachments.cleanup("fixture")


@pytest.mark.parametrize("case", ["size", "symlink", "type", "model", "count"])
async def test_invalid_attachments_rejected_before_network(hass, entry, provider, tmp_path, case):
    path = tmp_path / "input.txt"
    path.write_bytes(b"fixture")
    if case == "size":
        with path.open("wb") as output:
            output.truncate(20 * 1024 * 1024 + 1)
    if case == "symlink":
        link = tmp_path / "link.txt"
        link.symlink_to(path)
        path = link
    if case == "type":
        path = path.rename(tmp_path / "input.exe")
    attachment = conversation.Attachment(
        "media-source://authorized", "application/octet-stream", path
    )
    count = len(provider.requests)
    with pytest.raises(ApiError):
        await entry.runtime_data.attachments.parts(
            [attachment] * (6 if case == "count" else 1),
            "fixture",
            "deepseek-v4-pro" if case == "model" else "deepseek-flash",
        )
    assert len(provider.requests) == count


async def test_lost_upload_reply_recovered_without_deleting_other_files(
    hass, entry, provider, tmp_path
):
    path = tmp_path / "input.txt"
    path.write_text("private document")
    provider.queue.append(httpx.Response(503))
    manager = entry.runtime_data.attachments
    with pytest.raises(ApiError):
        await manager.parts(
            [conversation.Attachment("authorized", "text/plain", path)], "lost", "deepseek-flash"
        )
    owned_name = manager.owned[0]["filename"]
    # Simulate provider finishing parsing after a disconnected upload.
    original = manager.api.list_files

    async def listing():
        return [
            {"id": "file-api-ours", "filename": owned_name},
            {"id": "file-api-other", "filename": "user-personal.txt"},
        ]

    manager.api.list_files = listing
    provider.queue.append(httpx.Response(200, json={"deleted": True}))
    restored = Attachments(hass, entry.entry_id, manager.api)
    await restored.load()
    assert not restored.owned
    deletes = [r.url.path for r in provider.requests if r.method == "DELETE"]
    assert deletes == ["/files/file-api-ours"]
    manager.owned.clear()
    manager.api.list_files = original


async def test_cleanup_failure_retains_ownership_for_retry(hass, entry, provider, tmp_path):
    manager = entry.runtime_data.attachments
    manager.owned = [{"id": "file-api-owned", "filename": "ours.txt", "session": "x"}]
    provider.queue.append(httpx.Response(429))
    await manager.cleanup("x")
    assert manager.owned
    provider.queue.append(httpx.Response(200, json={"deleted": True}))
    await manager.cleanup("x")
    assert not manager.owned


async def test_native_camera_snapshot_media_resolution(hass, entry, provider):
    from homeassistant.components import camera
    from homeassistant.components.camera.const import DATA_COMPONENT as CAMERA_COMPONENT
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "camera", {})

    class Snapshot(camera.Camera):
        _attr_name = "Fixture camera"
        _attr_unique_id = "generated-snapshot"
        _attr_content_type = "image/png"

        async def async_camera_image(self, width=None, height=None):
            return PNG

    await hass.data[CAMERA_COMPONENT].async_add_entities([Snapshot()])
    provider.complete('{"present":true}')
    result = await hass.services.async_call(
        "ai_task",
        "generate_data",
        {
            "entity_id": entity_id(hass, entry, "ai_task"),
            "task_name": "Snapshot",
            "instructions": "Analyze",
            "attachments": [
                {
                    "media_content_id": "media-source://camera/camera.fixture_camera",
                    "media_content_type": "image/png",
                }
            ],
            "structure": {"present": {"required": True, "selector": {"boolean": {}}}},
        },
        blocking=True,
        return_response=True,
    )
    assert result["data"] == {"present": True}
    body = json.loads(provider.requests[-1].content)
    assert body["input"][-1]["content"][1]["image_url"].endswith(base64.b64encode(PNG).decode())
