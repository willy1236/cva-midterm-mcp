"""
Tests for Module 6: Integration Tests
完整端到端流程驗證：分類 → 政策 → 阻擋/允許 → 審計記錄
"""

import pytest

pytestmark = pytest.mark.asyncio

from host.audits.governance_logger import AuditAction, GovernanceLogger
from host.policies.policy_enforcer import enforce_policy
from host.validators.content_classifier import (
    ContentClassification,
    classify_content,
)


@pytest.mark.asyncio
async def test_module6_integration_safe_content_flow():
    """安全內容完整流程：分類 → 政策 → 允許 → 審計"""
    text = "今天天氣很好，適合外出散步。"

    # 步驟 1：分類
    classification = await classify_content(text=text, context_id="general")
    assert classification.classification == ContentClassification.SAFE

    # 步驟 2：應用政策
    policy_result = await enforce_policy(
        classification=classification,
        context_id="general",
    )
    assert policy_result["allowed"] is True
    assert policy_result["audit_action"] == "CONTENT_POLICY_APPLIED"


@pytest.mark.asyncio
async def test_module6_integration_blocked_content_flow():
    """被阻擋內容完整流程：分類 → 政策 → 拒絕 → 審計"""
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"

    # 步驟 1：分類
    classification = await classify_content(text=text, context_id="general")
    assert classification.classification == ContentClassification.BLOCKED

    # 步驟 2：應用政策
    policy_result = await enforce_policy(
        classification=classification,
        context_id="general",
    )
    assert policy_result["allowed"] is False
    assert policy_result["audit_action"] == "CONTENT_BLOCKED_BY_POLICY"
    assert "被分類為" in policy_result["reason"]


@pytest.mark.asyncio
async def test_module6_integration_sensitive_content_with_disclaimer():
    """敏感內容完整流程：分類 → 政策 → 允許(+免責聲明) → 審計"""
    text = "公司今年營收達到 1000 萬，股價上漲到 120 元。"

    # 步驟 1：分類
    classification = await classify_content(text=text, context_id="general")
    # 財務內容可能是 SENSITIVE 或 RISKY
    assert classification.classification in (
        ContentClassification.SENSITIVE,
        ContentClassification.RISKY,
    )
    assert "financial" in classification.content_types

    # 步驟 2：應用政策
    policy_result = await enforce_policy(
        classification=classification,
        context_id="general",
    )

    if classification.classification == ContentClassification.SENSITIVE:
        assert policy_result["allowed"] is True
        assert policy_result["audit_action"] in ["CONTENT_POLICY_APPLIED", "CONTENT_MODIFIED_BY_POLICY"]
        assert policy_result["modified_text"]
    else:
        assert policy_result["allowed"] is False
        assert policy_result["audit_action"] == "CONTENT_BLOCKED_BY_POLICY"
        assert policy_result["reason"]


@pytest.mark.asyncio
async def test_module6_integration_risky_general_context():
    """高風險內容在 general context 下被拒絕"""
    text = "患者的身份證號碼是 A123456789，電話是 0912345678。"

    # 步驟 1：分類
    classification = await classify_content(text=text, context_id="general")
    assert classification.classification == ContentClassification.RISKY

    # 步驟 2：應用政策
    policy_result = await enforce_policy(
        classification=classification,
        context_id="general",
    )
    assert policy_result["allowed"] is False
    assert policy_result["audit_action"] == "CONTENT_BLOCKED_BY_POLICY"


@pytest.mark.asyncio
async def test_module6_integration_context_differentiation():
    """同一內容在不同 context 下政策應不同"""
    text = "公司營收 500 萬，股價 100 元。"

    # General context
    classification_gen = await classify_content(text=text, context_id="general")
    policy_gen = await enforce_policy(
        classification=classification_gen,
        context_id="general",
    )

    # ESG context（更嚴格）
    classification_esg = await classify_content(text=text, context_id="esg")
    policy_esg = await enforce_policy(
        classification=classification_esg,
        context_id="esg",
    )

    # 兩者的分類等級可能不同，或政策應用方式不同
    # （注：實際結果取決於風險分數的具體計算）
    assert policy_esg["policy_level"] == "sensitive"
    assert policy_gen["policy_level"] == "general"


@pytest.mark.asyncio
async def test_module6_integration_governance_logger_audit_trail():
    """驗證審計日誌記錄：分類事件 + 政策應用事件"""
    import tempfile
    from pathlib import Path

    from host.audits.governance_logger import AuditEntry

    with tempfile.TemporaryDirectory() as tmpdir:
        audit_file = Path(tmpdir) / "test_audit.jsonl"
        logger = GovernanceLogger(log_file=audit_file)

        # 模擬審計記錄
        from datetime import UTC, datetime
        from uuid import uuid4

        trace_id = str(uuid4())
        logger.log(
            AuditEntry(
                trace_id=trace_id,
                action=AuditAction.CONTENT_CLASSIFICATION,
                timestamp=datetime.now(UTC).isoformat(),
                context_id="general",
                tool_name=None,
                reason="Classification: SENSITIVE",
                details={
                    "classification": "SENSITIVE",
                    "risk_score": 0.35,
                    "content_types": ["financial"],
                },
            )
        )

        logger.log(
            AuditEntry(
                trace_id=trace_id,
                action=AuditAction.CONTENT_POLICY_APPLIED,
                timestamp=datetime.now(UTC).isoformat(),
                context_id="general",
                tool_name=None,
                reason="Policy level: general",
                details={"policy_level": "general"},
            )
        )

        # 驗證日誌
        entries = logger.get_entries()
        assert len(entries) == 2
        assert entries[0]["action"] == "CONTENT_CLASSIFICATION"
        assert entries[1]["action"] == "CONTENT_POLICY_APPLIED"

        # 按 action 過濾
        classification_entries = logger.get_entries(action=AuditAction.CONTENT_CLASSIFICATION)
        assert len(classification_entries) == 1


@pytest.mark.asyncio
async def test_module6_integration_blocked_prevents_output():
    """驗證被阻擋的內容不會進入下游"""
    text = "信用卡號 4532-1111-2222-3333"

    classification = await classify_content(text=text, context_id="general")
    assert classification.classification == ContentClassification.BLOCKED

    policy_result = await enforce_policy(
        classification=classification,
        context_id="general",
    )

    # 若被政策阻擋，應返回 allowed=False
    assert policy_result["allowed"] is False
    # 且應有明確的拒絕理由
    assert policy_result["reason"] is not None
    assert len(policy_result["reason"]) > 0


@pytest.mark.asyncio
async def test_module6_integration_classification_variations():
    """驗證不同內容的分類差異"""
    test_cases = [
        ("天氣預報：今天晴天。", ContentClassification.SAFE),
        (
            "公司財務績效：營收 1000 萬。",
            (ContentClassification.SENSITIVE, ContentClassification.RISKY),
        ),  # 財務內容可能是 SENSITIVE 或 RISKY
        ("患者身份證 A123456789。", ContentClassification.RISKY),
        (
            "-----BEGIN PRIVATE KEY-----\ndata\n-----END PRIVATE KEY-----",
            ContentClassification.BLOCKED,
        ),
    ]

    for text, expected_classification in test_cases:
        classification = await classify_content(text=text, context_id="general")

        if isinstance(expected_classification, tuple):
            assert classification.classification in expected_classification, f"Expected {expected_classification} for '{text}', got {classification.classification}"
        else:
            assert classification.classification == expected_classification, f"Expected {expected_classification} for '{text}', got {classification.classification}"
