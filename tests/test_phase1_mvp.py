from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from host.audits.governance_logger import AuditAction, AuditEntry, GovernanceLogger
from host.validators.output_validator import SchemaType, validate_output_structure
from host.validators.tool_gatekeeper import secure_tool_call
from mcpServer.app import mcp


class TestToolGatekeeper:
    def test_allowed_tool_in_general_context(self) -> None:
        allowed, reason = secure_tool_call(
            tool_name="get_weather",
            context_id="general",
            arguments=None,
        )
        assert allowed is True
        assert reason == "allowed"

    def test_disallowed_tool_in_esg_context(self) -> None:
        allowed, reason = secure_tool_call(
            tool_name="get_weather",
            context_id="esg",
            arguments=None,
        )
        assert allowed is False
        assert "not in allowed scope" in reason

    def test_read_only_constraint_write_detection(self) -> None:
        allowed, reason = secure_tool_call(
            tool_name="get_weather",
            context_id="general",
            arguments={"delete_field": "value"},
        )
        assert allowed is False
        assert "read-only" in reason

    def test_unknown_context_id(self) -> None:
        allowed, reason = secure_tool_call(
            tool_name="get_weather",
            context_id="unknown_context",
            arguments=None,
        )
        assert allowed is False
        assert "Unknown context_id" in reason


class TestOutputValidator:
    def test_tool_result_schema_valid(self) -> None:
        data = {
            "tool_name": "get_weather",
            "status": "success",
            "output": {"temperature": 25},
        }
        valid, errors = validate_output_structure(data=data, schema_type=SchemaType.TOOL_RESULT)
        assert valid is True
        assert len(errors) == 0

    def test_tool_result_schema_invalid_status(self) -> None:
        data = {
            "tool_name": "get_weather",
            "status": "unknown",
            "output": None,
        }
        valid, errors = validate_output_structure(data=data, schema_type=SchemaType.TOOL_RESULT)
        assert valid is False
        assert len(errors) > 0

    def test_agent_response_schema_valid(self) -> None:
        data = {
            "content": "Hello, world!",
            "context_id": "general",
            "available_tools": ["get_weather"],
        }
        valid, errors = validate_output_structure(data=data, schema_type=SchemaType.AGENT_RESPONSE)
        assert valid is True
        assert len(errors) == 0

    def test_agent_response_schema_valid_structured_output(self) -> None:
        data = {
            "answer": "台北今天晴朗。",
            "sources": [
                {
                    "source_id": "tool-1",
                    "tool_name": "get_weather",
                }
            ],
            "context_id": "general",
            "available_tools": ["get_weather"],
        }
        valid, errors = validate_output_structure(data=data, schema_type=SchemaType.AGENT_RESPONSE)
        assert valid is True
        assert len(errors) == 0

    def test_peer_review_schema_invalid_verdict(self) -> None:
        data = {
            "content": "Review content",
            "reviewer_id": "reviewer-1",
            "verdict": "maybe",
            "criteria": {},
        }
        valid, errors = validate_output_structure(data=data, schema_type=SchemaType.PEER_REVIEW)
        assert valid is False
        assert len(errors) > 0


class TestGovernanceLogger:
    def test_log_and_retrieve_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test_audit.jsonl"
            logger = GovernanceLogger(log_file=log_file)

            entry = AuditEntry(
                trace_id="test-trace-1",
                action=AuditAction.TOOL_CALL_ALLOWED,
                timestamp="2026-04-23T10:00:00+00:00",
                context_id="general",
                tool_name="get_weather",
                reason="allowed",
            )
            logger.log(entry)

            entries = logger.get_entries()
            assert len(entries) == 1
            assert entries[0]["trace_id"] == "test-trace-1"
            assert entries[0]["action"] == "TOOL_CALL_ALLOWED"

    def test_summary_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test_audit.jsonl"
            logger = GovernanceLogger(log_file=log_file)

            logger.log(
                AuditEntry(
                    trace_id="test-1",
                    action=AuditAction.TOOL_CALL_ALLOWED,
                    timestamp="2026-04-23T10:00:00+00:00",
                    context_id="general",
                    tool_name="get_weather",
                    reason="allowed",
                )
            )
            logger.log(
                AuditEntry(
                    trace_id="test-2",
                    action=AuditAction.TOOL_CALL_REJECTED,
                    timestamp="2026-04-23T10:01:00+00:00",
                    context_id="esg",
                    tool_name="delete_record",
                    reason="not in allowed scope",
                )
            )

            summary = logger.summary()
            assert summary["total"] == 2
            assert summary["by_action"]["TOOL_CALL_ALLOWED"] == 1
            assert summary["by_action"]["TOOL_CALL_REJECTED"] == 1
            assert summary["by_context"]["general"] == 1
            assert summary["by_context"]["esg"] == 1

    def test_filter_by_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test_audit.jsonl"
            logger = GovernanceLogger(log_file=log_file)

            logger.log(
                AuditEntry(
                    trace_id="test-1",
                    action=AuditAction.TOOL_CALL_ALLOWED,
                    timestamp="2026-04-23T10:00:00+00:00",
                )
            )
            logger.log(
                AuditEntry(
                    trace_id="test-2",
                    action=AuditAction.TOOL_CALL_REJECTED,
                    timestamp="2026-04-23T10:01:00+00:00",
                )
            )

            rejections = logger.rejections()
            assert len(rejections) == 1
            assert rejections[0]["trace_id"] == "test-2"


# Note: MCP endpoint integration tests are performed via host_flow_cli.py
# These endpoints (secure_tool_call_endpoint, validate_output_structure_endpoint)
# are registered with FastMCP and available on the MCP server for client invocation
