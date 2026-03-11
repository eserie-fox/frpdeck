"""Thin stdio MCP server for proxy facade and instance status resources."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from mcp.server.fastmcp import FastMCP

from frpdeck.facade.proxy_facade import ProxyFacade
from frpdeck.mcp.resources import register_resources
from frpdeck.mcp.serialization import resolve_instance_dir
from frpdeck.mcp.tools import register_tools
from frpdeck.services.status_service import StatusService


SERVER_NAME = "frpdeck"


def create_mcp_server(instance_dir: str | Path | None = None) -> FastMCP:
    """Create the MCP server with tools and resources registered."""
    bound_instance_dir = None if instance_dir is None else resolve_instance_dir(instance_dir)
    mode = "bound" if bound_instance_dir is not None else "generic"
    server = FastMCP(
        SERVER_NAME,
        instructions=(
            "Thin local MCP wrapper over frpdeck structured proxy management and read-only instance status. "
            "Use tools for proxy operations and resources for status snapshots."
        ),
        json_response=True,
    )
    facade = ProxyFacade()
    status_service = StatusService()
    register_tools(server, facade=facade, mode=mode, bound_instance_dir=bound_instance_dir, server_name=SERVER_NAME)
    register_resources(server, status_service=status_service, mode=mode, bound_instance_dir=bound_instance_dir)
    return server


mcp = create_mcp_server()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse MCP server startup arguments without routing through the main CLI."""
    parser = argparse.ArgumentParser(description="Run the frpdeck MCP stdio server.")
    parser.add_argument("--instance-dir", help="Bind the stdio MCP server to a single instance directory.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the stdio MCP server."""
    args = parse_args(argv)
    create_mcp_server(instance_dir=args.instance_dir).run()


if __name__ == "__main__":
    main()