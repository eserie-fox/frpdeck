"""Stable facade result models for programmatic callers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FacadeResult(BaseModel):
    """Stable facade envelope for Python-level tool adapters."""

    schema_version: str = "frpdeck.proxy.v1"
    ok: bool
    operation: str
    instance: str
    data: Any = None
    error_code: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)