"""Local usage reset; does not contact a paid API."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeepSeekEntry
from .const import DOMAIN, NAME


async def async_setup_entry(
    hass: HomeAssistant, entry: DeepSeekEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ResetUsage(entry)])


class ResetUsage(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "reset_usage"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: DeepSeekEntry) -> None:
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_reset_usage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer=NAME
        )

    async def async_press(self) -> None:
        await self.entry.runtime_data.metrics.reset()
