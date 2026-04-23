from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from server.response import ErrorCode, ErrorResponse, SuccessResponse, build_error, build_success

mcp = FastMCP("Trust Constraint MCP Server")


@mcp.tool()
def get_weather(city: str) -> SuccessResponse[dict[str, Any]]:
    """Return a mocked weather response for quick end-to-end verification."""
    return build_success(data={"city": city, "weather": "sunny", "temperature_c": 25})
