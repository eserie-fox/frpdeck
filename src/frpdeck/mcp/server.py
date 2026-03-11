"""Thin stdio MCP server for proxy facade and instance status resources."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from frpdeck.facade.proxy_facade import ProxyFacade
from frpdeck.mcp.resources import register_resources
from frpdeck.mcp.tools import register_tools
from frpdeck.services.status_service import StatusService


def create_mcp_server() -> FastMCP:
    """Create the MCP server with tools and resources registered."""
    server = FastMCP(
        "frpdeck",
        instructions=(
            "Thin local MCP wrapper over frpdeck structured proxy management and read-only instance status. "
            "Use tools for proxy operations and resources for status snapshots."
        ),
        json_response=True,
    )
    facade = ProxyFacade()
    status_service = StatusService()
    register_tools(server, facade=facade)
    register_resources(server, status_service=status_service)
    return server


mcp = create_mcp_server()


def main() -> None:
    """Run the stdio MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()