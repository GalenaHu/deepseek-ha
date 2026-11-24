"""Provider-reported counters; deliberately not an account bill estimate."""

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, NAME

DESCRIPTIONS = [SensorEntityDescription(key=key, translation_key=key, native_unit_of_measurement=unit, state_class=SensorStateClass.TOTAL_INCREASING if key != "latency_ms" else SensorStateClass.MEASUREMENT) for key, unit in (("requests", "requests"), ("input_tokens", "tokens"), ("output_tokens", "tokens"), ("cached_tokens", "tokens"), ("reasoning_tokens", "tokens"), ("searches", "searches"), ("stt_seconds", "s"), ("tts_characters", "characters"), ("latency_ms", "ms"))]


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([UsageSensor(entry, desc) for desc in DESCRIPTIONS])


class UsageSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = None

    def __init__(self, entry, description):
        self.entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": entry.title, "manufacturer": NAME}

    @property
    def native_value(self):
        return self.entry.runtime_data.metrics.values[self.entity_description.key]

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, self.entry.runtime_data.metrics.signal, self.async_write_ha_state))

