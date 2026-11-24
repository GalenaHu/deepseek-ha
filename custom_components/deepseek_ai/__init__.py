"""DeepSeek AI: native Home Assistant AI platforms on official provider APIs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.httpx_client import get_async_client

from .api import ApiError, DeepSeekClient
from .attachments import Attachments
from .const import DOMAIN, MIN_HA, PLATFORMS
from .metrics import Metrics
from .privacy import install
from .settings import agent_settings

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class Runtime:
    hass: HomeAssistant
    entry: ConfigEntry
    api: DeepSeekClient
    attachments: Attachments
    metrics: Metrics
    gate: asyncio.Semaphore
    sessions: set[str] = field(default_factory=set)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    closing: bool = False
    jobs: set[asyncio.Task[Any]] = field(default_factory=set)

    @asynccontextmanager
    async def job(self) -> AsyncIterator[None]:
        if self.closing:
            raise ApiError("integration_unloading")
        task = asyncio.current_task()
        assert task is not None
        nested = task in self.jobs
        self.jobs.add(task)
        try:
            yield
        finally:
            if not nested:
                self.jobs.discard(task)

    async def shutdown(self) -> None:
        self.closing = True
        tasks = self.jobs - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def handle_error(self, err: ApiError) -> None:
        if err.status in (401, 403):
            self.entry.async_start_reauth(self.hass)


type DeepSeekEntry = ConfigEntry[Runtime]


async def async_setup_entry(hass: HomeAssistant, entry: DeepSeekEntry) -> bool:
    if AwesomeVersion(HA_VERSION) < AwesomeVersion(MIN_HA):
        raise ConfigEntryError(f"Home Assistant {MIN_HA} or later is required")
    try:
        concurrent = entry.data.get("max_concurrent", 2)
        if type(concurrent) is not int or not 1 <= concurrent <= 8:
            raise ValueError("invalid_concurrency")
        for subentry in entry.subentries.values():
            agent_settings(subentry.subentry_type, subentry.data)
            if subentry.subentry_type == "evaluation" and not subentry.data.get(
                "acknowledge_experimental"
            ):
                raise ValueError("experimental_required")
        api = DeepSeekClient(
            get_async_client(hass), entry.data[CONF_API_KEY], async_get_clientsession(hass)
        )
        await api.validate_key()
    except ValueError:
        raise ConfigEntryError("Invalid DeepSeek agent configuration") from None
    except ApiError as err:
        if err.status in (401, 403):
            raise ConfigEntryAuthFailed("DeepSeek credentials rejected") from None
        raise ConfigEntryNotReady(str(err)) from None
    metrics = Metrics(hass, entry.entry_id)
    files = Attachments(hass, entry.entry_id, api)
    await metrics.load()
    await files.load()
    entry.runtime_data = Runtime(hass, entry, api, files, metrics, asyncio.Semaphore(concurrent))
    entry.async_on_unload(install())
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_update))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DeepSeekEntry) -> bool:
    await entry.runtime_data.shutdown()
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.attachments.cleanup(None)
        await entry.runtime_data.metrics.save()
        return True
    entry.runtime_data.closing = False
    return False


async def _update(hass: HomeAssistant, entry: DeepSeekEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
