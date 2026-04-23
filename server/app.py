from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from audits.governance_logger import AuditAction, AuditEntry, GovernanceLogger
from policies.config_loader import get_context_profile, load_constraint_config
from server.response import ErrorCode, ErrorResponse, SuccessResponse, build_error, build_success
from validators.output_validator import SchemaType, validate_output_structure
from validators.tool_gatekeeper import ToolAccessDeniedError, secure_tool_call

mcp = FastMCP("Trust Constraint MCP Server")
governance_logger = GovernanceLogger(log_file=Path("audits/logs/governance_audit.jsonl"))


@mcp.tool()
def get_weather(city: str) -> SuccessResponse[dict[str, Any]]:
    """Return a mocked weather response for quick end-to-end verification."""
    return build_success(data={"city": city, "weather": "sunny", "temperature_c": 25})


@mcp.resource("resource://profile/{context_id}")
def get_agent_profile(context_id: str = "") -> str:
    """Load identity and boundary rules for the given context."""
    try:
        profile = get_context_profile(context_id)
        return build_success(data=profile).model_dump_json()
    except KeyError as exc:
        return build_error(
            code=ErrorCode.NOT_FOUND,
            message="context profile not found",
            detail=str(exc),
        ).model_dump_json()
    except Exception as exc:  # pragma: no cover - defensive fallback
        return build_error(
            code=ErrorCode.INTERNAL_ERROR,
            message="failed to load profile",
            detail=str(exc),
        ).model_dump_json()


@mcp.tool()
def fetch_constraint_config() -> SuccessResponse[dict[str, Any]] | ErrorResponse:
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


@mcp.tool()
def secure_tool_call_endpoint(tool_name: str, context_id: str = "general", arguments: dict[str, Any] | None = None) -> SuccessResponse[dict[str, Any]] | ErrorResponse:
    """
    Check if a tool call is authorized for the given context.
    Returns ok=True if allowed, with audit log.
    """
    from uuid import uuid4

    trace_id = str(uuid4())

    allowed, reason = secure_tool_call(
        tool_name=tool_name,
        context_id=context_id,
        arguments=arguments,
    )

    action = AuditAction.TOOL_CALL_ALLOWED if allowed else AuditAction.TOOL_CALL_REJECTED
    entry = AuditEntry(
        trace_id=trace_id,
        action=action,
        timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        context_id=context_id,
        tool_name=tool_name,
        reason=reason,
        details={"arguments": arguments or {}},
    )
    governance_logger.log(entry)

    if not allowed:
        return build_error(
            code=ErrorCode.POLICY_VIOLATION,
            message="tool call not authorized",
            detail=reason,
            trace_id=trace_id,
        )

    return build_success(
        data={"allowed": True, "tool_name": tool_name, "context_id": context_id},
        message="tool call authorized",
        trace_id=trace_id,
    )


@mcp.tool()
def validate_output_structure_endpoint(data: dict[str, Any] | list[dict[str, Any]], schema_type: str) -> SuccessResponse[dict[str, Any]] | ErrorResponse:
    """
    Validate output against a schema (TOOL_RESULT, AGENT_RESPONSE, PEER_REVIEW, AUDIT_REPORT).
    Returns ok=True if valid, with audit log.
    """
    from uuid import uuid4

    trace_id = str(uuid4())

    valid, errors = validate_output_structure(data=data, schema_type=schema_type)

    action = AuditAction.OUTPUT_VALIDATION_PASS if valid else AuditAction.OUTPUT_VALIDATION_FAIL
    entry = AuditEntry(
        trace_id=trace_id,
        action=action,
        timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        context_id=None,
        tool_name=None,
        reason="; ".join(errors) if errors else "validation passed",
        details={"schema_type": schema_type, "errors": errors},
    )
    governance_logger.log(entry)

    if not valid:
        return build_error(
            code=ErrorCode.VALIDATION_ERROR,
            message="output validation failed",
            detail="; ".join(errors),
            trace_id=trace_id,
        )

    return build_success(
        data={"valid": True, "schema_type": schema_type},
        message="output validation passed",
        trace_id=trace_id,
    )
