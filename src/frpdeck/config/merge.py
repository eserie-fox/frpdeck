"""Reusable helpers for merging formal configuration mappings."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def config_deep_merge(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge defaults and overrides with strict, predictable semantics."""

    merged: dict[str, Any] = {key: deepcopy(value) for key, value in base.items()}

    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(value, Mapping):
            merged[key] = config_deep_merge(base_value, value)
        else:
            merged[key] = deepcopy(value)

    return merged


__all__ = ["config_deep_merge"]
