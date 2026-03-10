"""Lightweight FRP version normalization and comparison helpers."""

from __future__ import annotations

import re


_VERSION_RE = re.compile(r"^v?(?P<core>\d+(?:\.\d+)*)(?P<suffix>[-+][0-9A-Za-z.-]+)?$")


def normalize_version(value: str | None) -> str | None:
    """Normalize common FRP version strings by stripping a leading v."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    match = _VERSION_RE.fullmatch(stripped)
    if not match:
        return stripped[1:] if stripped.startswith("v") else stripped
    core = match.group("core")
    suffix = match.group("suffix") or ""
    return f"{core}{suffix}"


def compare_versions(left: str | None, right: str | None) -> int | None:
    """Compare two FRP version strings.

    Returns -1, 0, 1 when a safe comparison is possible, otherwise None.
    """
    normalized_left = normalize_version(left)
    normalized_right = normalize_version(right)
    if not normalized_left or not normalized_right:
        return None

    left_match = _VERSION_RE.fullmatch(normalized_left)
    right_match = _VERSION_RE.fullmatch(normalized_right)
    if not left_match or not right_match:
        return None

    left_core = [int(part) for part in left_match.group("core").split(".")]
    right_core = [int(part) for part in right_match.group("core").split(".")]
    max_len = max(len(left_core), len(right_core))
    left_core.extend([0] * (max_len - len(left_core)))
    right_core.extend([0] * (max_len - len(right_core)))

    if left_core < right_core:
        return -1
    if left_core > right_core:
        return 1

    left_suffix = left_match.group("suffix")
    right_suffix = right_match.group("suffix")
    if left_suffix == right_suffix:
        return 0
    if left_suffix and not right_suffix:
        return -1
    if right_suffix and not left_suffix:
        return 1
    return None
