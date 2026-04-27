from __future__ import annotations

import pytest

from host.validators.resource_circuit_breaker import (
    ResourceBudget,
    ResourceCircuitBreaker,
    ResourceLimitExceeded,
    build_resource_budget,
)


def test_triggered_when_total_tokens_exceeded() -> None:
    breaker = ResourceCircuitBreaker(
        ResourceBudget(
            max_total_tokens=10,
            max_model_calls=5,
            max_tool_calls=5,
            max_tool_calls_per_tool=3,
            max_total_latency_ms=1000,
        )
    )

    breaker.record_model_response(total_tokens=11)
    with pytest.raises(ResourceLimitExceeded) as exc:
        breaker.check()

    assert "total_tokens_exceeded" in str(exc.value)


def test_triggered_when_tool_frequency_exceeded() -> None:
    breaker = ResourceCircuitBreaker(
        ResourceBudget(
            max_total_tokens=100,
            max_model_calls=10,
            max_tool_calls=10,
            max_tool_calls_per_tool=1,
            max_total_latency_ms=1000,
        )
    )

    breaker.record_tool_call(tool_name="get_weather")
    breaker.record_tool_call(tool_name="get_weather")
    with pytest.raises(ResourceLimitExceeded) as exc:
        breaker.check()

    assert "tool_frequency_exceeded:get_weather" in str(exc.value)


def test_triggered_when_latency_exceeded() -> None:
    breaker = ResourceCircuitBreaker(
        ResourceBudget(
            max_total_tokens=100,
            max_model_calls=10,
            max_tool_calls=10,
            max_tool_calls_per_tool=5,
            max_total_latency_ms=10,
        )
    )

    with pytest.raises(ResourceLimitExceeded) as exc:
        breaker.check(now=breaker.started_at + 0.02)

    assert "latency_exceeded" in str(exc.value)


def test_build_resource_budget_prefers_profile_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST_CB_MAX_TOTAL_TOKENS", "999")
    profile_data = {
        "resource_limits": {
            "max_total_tokens": 120,
            "max_model_calls": 3,
            "max_tool_calls": 4,
            "max_tool_calls_per_tool": 2,
            "max_total_latency_ms": 500,
        }
    }

    budget = build_resource_budget(profile_data)
    assert budget.max_total_tokens == 120
    assert budget.max_model_calls == 3
    assert budget.max_tool_calls == 4
    assert budget.max_tool_calls_per_tool == 2
    assert budget.max_total_latency_ms == 500
