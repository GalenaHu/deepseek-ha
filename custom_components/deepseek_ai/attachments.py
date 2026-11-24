"""Bounded HA attachments and durable ownership of provider-uploaded files."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from homeassistant.components.conversation import Attachment
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api import ApiError, DeepSeekClient
from .const import DOMAIN, FILE_EXTENSIONS, IMAGE_MIMES, MAX_ATTACHMENTS, MAX_FILE_BYTES


class Attachments:
    """Only IDs or pending filenames explicitly recorded by this entry are owned."""

    def __init__(self, hass: HomeAssistant, entry_id: str, api: DeepSeekClient) -> None:
        self.hass, self.api = hass, api
        self.store: Store[list[dict[str, Any]]] = Store(hass, 1, f"{DOMAIN}.{entry_id}.files")
        self.owned: list[dict[str, Any]] = []
        self.lock = asyncio.Lock()
        self.cache: dict[tuple[str, str], str] = {}

    async def load(self) -> None:
        self.owned = await self.store.async_load() or []
        # Sessions don't survive HA restart. Recover also uploads whose response
        # was lost: filenames were persisted before sending any file bytes.
        await self.cleanup(None)

    async def cleanup(self, session: str | None) -> None:
        async with self.lock:
            targets = [item for item in self.owned if session is None or item["session"] == session]
            if not targets:
                return
            try:
                listing = await self.api.list_files() if any(not item.get("id") for item in targets) else []
                by_name = {row.get("filename"): row.get("id") for row in listing}
                for item in targets:
                    file_id = item.get("id") or by_name.get(item["filename"])
                    if file_id:
                        await self.api.delete_file(file_id)
                        self.owned.remove(item)
                    # Unknown pending uploads remain journaled for restart/retry;
                    # provider parsing can continue after the request disconnects.
                await self.store.async_save(self.owned)
            except ApiError:
                # Keep ownership records for a later retry; never log payloads.
                return
            if session is None:
                self.cache.clear()
            else:
                self.cache = {key: val for key, val in self.cache.items() if key[0] != session}

    @staticmethod
    def _read(path: Path, mime: str | None) -> tuple[bytes, str]:
        # File paths are provided by HA after media permission resolution, not
        # arbitrary service filename strings. Reject symlinks and oversized input.
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ApiError("invalid_or_oversized_attachment")
        with path.open("rb") as file:
            data = file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ApiError("attachment_too_large")
        return data, mime or mimetypes.guess_type(path)[0] or "application/octet-stream"

    async def parts(self, attachments: list[Attachment] | None, session: str, model: str) -> list[dict[str, Any]]:
        if not attachments:
            return []
        if model != "deepseek-flash":
            raise ApiError("model_does_not_support_attachments")
        if len(attachments) > MAX_ATTACHMENTS:
            raise ApiError("too_many_attachments")
        parts: list[dict[str, Any]] = []
        total = 0
        for attachment in attachments:
            path = Path(attachment.path)
            data, mime = await self.hass.async_add_executor_job(self._read, path, attachment.mime_type)
            total += len(data)
            if total > MAX_FILE_BYTES:
                raise ApiError("attachments_too_large")
            if mime in IMAGE_MIMES:
                parts.append({"type": "input_image", "image_url": f"data:{mime};base64," + base64.b64encode(data).decode()})
                continue
            suffix = path.suffix.lower()
            # HA media-source temp names may lack a suffix; map known MIME types.
            if suffix not in FILE_EXTENSIONS:
                suffix = {"application/pdf": ".pdf", "text/plain": ".txt", "text/csv": ".csv", "application/json": ".json", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx", "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx"}.get(mime, "")
            if not suffix:
                raise ApiError("unsupported_attachment_type")
            key = (session, str(path))
            if key not in self.cache:
                filename = "deepseek-ai-" + uuid.uuid4().hex + suffix
                record: dict[str, Any] = {"session": session, "filename": filename}
                async with self.lock:
                    self.owned.append(record)
                    await self.store.async_save(self.owned)
                purpose = "rich_layout_recognition" if suffix in {".pdf", ".doc", ".docx", ".ppt", ".pptx"} else "user_data"
                file_id = await self.api.upload(filename, data, mime, purpose)
                async with self.lock:
                    record["id"] = file_id
                    await self.store.async_save(self.owned)
                self.cache[key] = file_id
            parts.append({"type": "input_file", "file_id": self.cache[key]})
        return parts
