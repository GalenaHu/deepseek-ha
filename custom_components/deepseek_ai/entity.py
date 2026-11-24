"""Shared identity of functional subentries."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, NAME
from .settings import agent_settings


class AgentEntity(Entity):
    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(self, entry, subentry):
        self.entry, self.subentry = entry, subentry
        self.options = agent_settings(subentry.subentry_type, subentry.data)
        self._attr_unique_id = subentry.subentry_id
        self._attr_name = subentry.title
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, manufacturer=NAME, name=entry.title, entry_type=DeviceEntryType.SERVICE)

