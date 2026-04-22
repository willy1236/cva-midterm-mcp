from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class ErrorCode(str, Enum):
    SUCCESS = "OK_0000"
    INVALID_REQUEST = "REQ_0400"
    NOT_FOUND = "REQ_0404"
    POLICY_VIOLATION = "POL_0403"
    VALIDATION_ERROR = "VAL_0422"
    INTERNAL_ERROR = "SYS_0500"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_success(
    *,
    data: Any,
    message: str = "success",
    code: ErrorCode = ErrorCode.SUCCESS,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "code": code.value,
        "message": message,
        "trace_id": trace_id or str(uuid4()),
        "timestamp": _now_iso(),
        "data": data,
        "error": None,
    }


def build_error(
    *,
    code: ErrorCode,
    message: str,
    detail: Any | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "code": code.value,
        "message": message,
        "trace_id": trace_id or str(uuid4()),
        "timestamp": _now_iso(),
        "data": None,
        "error": {
            "detail": detail,
        },
    }
