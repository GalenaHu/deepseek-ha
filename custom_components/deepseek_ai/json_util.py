"""JSON accepted by the provider and HA must contain finite, unambiguous values."""

import json
import math
from typing import Any


def _constant(value: str) -> Any:
    raise ValueError("Non-JSON numeric constant")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def decode_json(value: str | bytes | bytearray) -> Any:
    return json.loads(
        value, parse_constant=_constant, parse_float=_float, object_pairs_hook=_object
    )
