"""Persistent operational counters, with no prompts, identities or payloads."""

import math
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN

COUNTERS = (
    "requests",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "searches",
    "stt_seconds",
    "tts_characters",
)


class Metrics:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry_id}.metrics")
        self.signal = f"{DOMAIN}_{entry_id}_metrics"
        self.values: dict[str, float] = {key: 0 for key in (*COUNTERS, "latency_ms")}

    async def load(self) -> None:
        if previous := await self.store.async_load():
            for key in self.values:
                value = previous.get(key)
                if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                    self.values[key] = value

    def add(self, **values: float) -> None:
        for key, value in values.items():
            if not math.isfinite(value):
                continue
            if key in COUNTERS and value >= 0:
                self.values[key] += value
            elif key == "latency_ms":
                self.values[key] = max(0, value)
        async_dispatcher_send(self.hass, self.signal)
        self.store.async_delay_save(lambda: self.values.copy(), 2)

    def response(self, usage: Any, latency: float) -> None:
        usage = usage if isinstance(usage, dict) else {}

        def count(parent: Any, key: str) -> float:
            value = parent.get(key, 0) if isinstance(parent, dict) else 0
            return (
                float(value)
                if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
                else 0
            )

        self.add(
            requests=1,
            input_tokens=count(usage, "input_tokens"),
            output_tokens=count(usage, "output_tokens"),
            cached_tokens=count(usage.get("input_tokens_details"), "cached_tokens"),
            reasoning_tokens=count(usage.get("output_tokens_details"), "reasoning_tokens"),
            latency_ms=latency * 1000,
        )

    async def reset(self) -> None:
        self.values = dict.fromkeys(self.values, 0)
        await self.save()
        async_dispatcher_send(self.hass, self.signal)

    async def save(self) -> None:
        await self.store.async_save(self.values)
