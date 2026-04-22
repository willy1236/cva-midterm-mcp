from __future__ import annotations

from fastmcp import FastMCP

from policies.config_loader import get_context_profile, load_constraint_config
from server.response import ErrorCode, build_error, build_success

mcp = FastMCP("Trust Constraint MCP Server")


@mcp.tool()
def get_weather(city: str) -> dict:
    """Return a mocked weather response for quick end-to-end verification."""
    return build_success(data={"city": city, "weather": "sunny", "temperature_c": 25})


@mcp.tool()
def get_agent_profile(context_id: str = "") -> dict:
    """Load identity and boundary rules for the given context."""
    try:
        profile = get_context_profile(context_id)
        return build_success(data=profile)
    except KeyError as exc:
        return build_error(
            code=ErrorCode.NOT_FOUND,
            message="context profile not found",
            detail=str(exc),
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        return build_error(
            code=ErrorCode.INTERNAL_ERROR,
            message="failed to load profile",
            detail=str(exc),
        )


@mcp.tool()
def fetch_constraint_config() -> dict:
    """Return full policy config to ensure all agents share one rule source."""
    try:
        config = load_constraint_config()
        return build_success(data=config)
    except Exception as exc:  # pragma: no cover - defensive fallback
        return build_error(
            code=ErrorCode.INTERNAL_ERROR,
            message="failed to load constraint config",
            detail=str(exc),
        )
