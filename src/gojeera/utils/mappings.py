from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def get_nested(mapping: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested mapping keys and return a default when any key is missing."""
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return default
        if key not in current:
            return default
        current = current[key]
        if current is None:
            return default
    return current
