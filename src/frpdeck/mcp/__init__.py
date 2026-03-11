"""Thin MCP server exports."""

from __future__ import annotations

from typing import Any


__all__ = ["create_mcp_server", "mcp", "main"]


def __getattr__(name: str) -> Any:
	if name in __all__:
		from frpdeck.mcp import server

		return getattr(server, name)
	raise AttributeError(name)
