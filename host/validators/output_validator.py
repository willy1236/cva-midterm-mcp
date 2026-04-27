from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, ValidationError, field_validator


class SchemaType(str, Enum):
    TOOL_RESULT = "TOOL_RESULT"
    AGENT_RESPONSE = "AGENT_RESPONSE"
    PEER_REVIEW = "PEER_REVIEW"
    AUDIT_REPORT = "AUDIT_REPORT"


class ToolResultSchema(BaseModel):
    tool_name: str
    status: str
    output: Any | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in {"success", "error"}:
            raise ValueError(f"status must be 'success' or 'error', got {v}")
        return v


class AgentResponseSchema(BaseModel):
    answer: str = Field(validation_alias=AliasChoices("answer", "content"))
    sources: list[dict[str, Any]] = Field(default_factory=list)
    context_id: str | None = None
    available_tools: list[str] = Field(default_factory=list)


class PeerReviewSchema(BaseModel):
    content: str
    reviewer_id: str
    verdict: str
    criteria: dict[str, Any] = {}

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, v: str) -> str:
        if v not in {"pass", "revise", "reject"}:
            raise ValueError(f"verdict must be 'pass', 'revise', or 'reject', got {v}")
        return v


class AuditReportSchema(BaseModel):
    action: str
    trace_id: str
    context_id: str | None = None
    timestamp: str | None = None


SCHEMA_MAP = {
    SchemaType.TOOL_RESULT: ToolResultSchema,
    SchemaType.AGENT_RESPONSE: AgentResponseSchema,
    SchemaType.PEER_REVIEW: PeerReviewSchema,
    SchemaType.AUDIT_REPORT: AuditReportSchema,
}


class OutputValidationError(Exception):
    pass


def validate_output_structure(*, data: object, schema_type: SchemaType | str) -> tuple[bool, list[str]]:
    if isinstance(schema_type, str):
        try:
            schema_type = SchemaType(schema_type)
        except ValueError:
            return False, [f"Unknown schema_type: {schema_type}"]

    schema_cls = SCHEMA_MAP.get(schema_type)
    if schema_cls is None:
        return False, [f"Schema not found for {schema_type}"]

    try:
        schema_cls.model_validate(data)
        return True, []
    except ValidationError as exc:
        errors = [f"{'.'.join(str(e) for e in err['loc'])}: {err['msg']}" for err in exc.errors()]
        return False, errors
