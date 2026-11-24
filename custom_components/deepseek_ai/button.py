"""Local usage reset; does not contact a paid API."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, NAME


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ResetUsage(entry)])


class ResetUsage(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "reset_usage"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_reset_usage"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": entry.title, "manufacturer": NAME}

    async def async_press(self):
        await self.entry.runtime_data.metrics.reset()

