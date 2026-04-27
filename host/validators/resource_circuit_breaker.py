from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any


def _as_non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


@dataclass(frozen=True)
class ResourceBudget:
    max_total_tokens: int
    max_model_calls: int
    max_tool_calls: int
    max_tool_calls_per_tool: int
    max_total_latency_ms: int


class ResourceLimitExceeded(Exception):
    def __init__(self, reasons: list[str], metrics: dict[str, Any]) -> None:
        self.reasons = reasons
        self.metrics = metrics
        super().__init__("; ".join(reasons))


class ResourceCircuitBreaker:
    def __init__(self, budget: ResourceBudget) -> None:
        self.budget = budget
        self.total_tokens = 0
        self.model_calls = 0
        self.tool_calls = 0
        self.tool_calls_by_name: dict[str, int] = {}
        self.started_at = time.perf_counter()

    def record_model_response(self, *, total_tokens: int = 0) -> None:
        self.model_calls += 1
        self.total_tokens += max(0, int(total_tokens))

    def record_tool_call(self, *, tool_name: str) -> None:
        self.tool_calls += 1
        self.tool_calls_by_name[tool_name] = self.tool_calls_by_name.get(tool_name, 0) + 1

    def _elapsed_ms(self, now: float | None = None) -> int:
        current = now if now is not None else time.perf_counter()
        return int((current - self.started_at) * 1000)

    def metrics(self, *, now: float | None = None) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "tool_calls_by_name": dict(self.tool_calls_by_name),
            "elapsed_ms": self._elapsed_ms(now=now),
        }

    def check(self, *, now: float | None = None) -> None:
        reasons: list[str] = []
        elapsed_ms = self._elapsed_ms(now=now)

        if self.total_tokens > self.budget.max_total_tokens:
            reasons.append(f"total_tokens_exceeded:{self.total_tokens}>{self.budget.max_total_tokens}")

        if self.model_calls > self.budget.max_model_calls:
            reasons.append(f"model_calls_exceeded:{self.model_calls}>{self.budget.max_model_calls}")

        if self.tool_calls > self.budget.max_tool_calls:
            reasons.append(f"tool_calls_exceeded:{self.tool_calls}>{self.budget.max_tool_calls}")

        if self.budget.max_tool_calls_per_tool >= 0:
            for tool_name, count in self.tool_calls_by_name.items():
                if count > self.budget.max_tool_calls_per_tool:
                    reasons.append(f"tool_frequency_exceeded:{tool_name}:{count}>{self.budget.max_tool_calls_per_tool}")

        if elapsed_ms > self.budget.max_total_latency_ms:
            reasons.append(f"latency_exceeded:{elapsed_ms}>{self.budget.max_total_latency_ms}")

        if reasons:
            raise ResourceLimitExceeded(reasons, self.metrics(now=now))


def build_resource_budget(profile_data: dict[str, Any] | None = None) -> ResourceBudget:
    env_defaults = {
        "max_total_tokens": _as_non_negative_int(os.getenv("HOST_CB_MAX_TOTAL_TOKENS"), 8000),
        "max_model_calls": _as_non_negative_int(os.getenv("HOST_CB_MAX_MODEL_CALLS"), 8),
        "max_tool_calls": _as_non_negative_int(os.getenv("HOST_CB_MAX_TOOL_CALLS"), 8),
        "max_tool_calls_per_tool": _as_non_negative_int(os.getenv("HOST_CB_MAX_TOOL_CALLS_PER_TOOL"), 4),
        "max_total_latency_ms": _as_non_negative_int(os.getenv("HOST_CB_MAX_TOTAL_LATENCY_MS"), 30000),
    }

    profile_limits: dict[str, Any] = {}
    if isinstance(profile_data, dict):
        maybe_limits = profile_data.get("resource_limits", {})
        if isinstance(maybe_limits, dict):
            profile_limits = maybe_limits

    effective = {**env_defaults, **profile_limits}
    return ResourceBudget(
        max_total_tokens=_as_non_negative_int(effective.get("max_total_tokens"), env_defaults["max_total_tokens"]),
        max_model_calls=_as_non_negative_int(effective.get("max_model_calls"), env_defaults["max_model_calls"]),
        max_tool_calls=_as_non_negative_int(effective.get("max_tool_calls"), env_defaults["max_tool_calls"]),
        max_tool_calls_per_tool=_as_non_negative_int(
            effective.get("max_tool_calls_per_tool"),
            env_defaults["max_tool_calls_per_tool"],
        ),
        max_total_latency_ms=_as_non_negative_int(
            effective.get("max_total_latency_ms"),
            env_defaults["max_total_latency_ms"],
        ),
    )
