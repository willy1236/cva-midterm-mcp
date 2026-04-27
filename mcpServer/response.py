from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(str, Enum):
    SUCCESS = "OK_0000"
    INVALID_REQUEST = "REQ_0400"
    NOT_FOUND = "REQ_0404"
    POLICY_VIOLATION = "POL_0403"
    VALIDATION_ERROR = "VAL_0422"
    INTERNAL_ERROR = "SYS_0500"


class ErrorPayload(BaseModel):
    detail: Any | None = None


class ResponseBase(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    ok: bool
    code: ErrorCode
    message: str
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


T = TypeVar("T")


class SuccessResponse(ResponseBase, Generic[T]):
    ok: bool = True
    data: T
    error: None = None


class ErrorResponse(ResponseBase):
    ok: bool = False
    data: None = None
    error: ErrorPayload


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_success(
    *,
    data: T,
    message: str = "success",
    code: ErrorCode = ErrorCode.SUCCESS,
    trace_id: str | None = None,
) -> SuccessResponse[T]:
    payload = SuccessResponse[T](
        code=code,
        message=message,
        trace_id=trace_id or str(uuid4()),
        timestamp=_now_iso(),
        data=data,
    )
    return payload


def build_error(
    *,
    code: ErrorCode,
    message: str,
    detail: object | None = None,
    trace_id: str | None = None,
) -> ErrorResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        trace_id=trace_id or str(uuid4()),
        timestamp=_now_iso(),
        error=ErrorPayload(detail=detail),
    )
    return payload
