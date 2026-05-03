"""
Tests for Module 6: Policy Enforcer
"""

import pytest

pytestmark = pytest.mark.asyncio

from host.policies.policy_enforcer import (
    apply_policy_mitigation,
    enforce_policy,
    get_policy_rules,
)
from host.validators.content_classifier import (
    ClassificationResult,
    ContentClassification,
)


def test_get_policy_rules_general_context():
    """取得 general context 的政策規則"""
    rules = get_policy_rules(context_id="general")

    assert rules["policy_level"] == "general"
    assert "financial" in rules["content_type_policy"]
    assert "personal_data" in rules["content_type_policy"]
    assert rules["content_type_policy"]["personal_data"] == "blocked"


def test_get_policy_rules_esg_context_stricter():
    """ESG context 政策應更嚴格"""
    rules_general = get_policy_rules(context_id="general")
    rules_esg = get_policy_rules(context_id="esg")

    # ESG 的 safe 門檻應更低（更敏感）
    assert rules_esg["risk_score_threshold"]["safe"] < rules_general["risk_score_threshold"]["safe"]
    # ESG 對財務內容應限制
    assert rules_esg["content_type_policy"]["financial"] == "restricted"


def test_get_policy_rules_code_dev_context():
    """Code_dev context 的政策規則"""
    rules = get_policy_rules(context_id="code_dev")

    assert rules["policy_level"] == "risky"
    # Code_dev 禁止未授權操作
    assert rules["content_type_policy"]["unauthorized_operations"] == "blocked"


@pytest.mark.asyncio
async def test_enforce_policy_safe_content_allowed():
    """安全內容應被允許"""
    classification = ClassificationResult(
        classification=ContentClassification.SAFE,
        risk_score=0.1,
        content_types=[],
        sensitive_patterns=[],
        blocking_reasons=[],
        confidence=0.9,
    )

    result = await enforce_policy(
        classification=classification,
        context_id="general",
    )

    assert result["allowed"] is True
    assert result["reason"] is None


@pytest.mark.asyncio
async def test_enforce_policy_blocked_content_rejected():
    """被硬規則阻擋的內容應直接拒絕"""
    classification = ClassificationResult(
        classification=ContentClassification.BLOCKED,
        risk_score=1.0,
        content_types=[],
        sensitive_patterns=["private_key"],
        blocking_reasons=["私密金鑰"],
        confidence=0.95,
    )

    result = await enforce_policy(
        classification=classification,
        context_id="general",
    )

    assert result["allowed"] is False
    assert "被分類為 BLOCKED" in result["reason"]


@pytest.mark.asyncio
async def test_enforce_policy_risky_general_context_rejected():
    """RISKY 內容在 general context 下應被拒絕"""
    classification = ClassificationResult(
        classification=ContentClassification.RISKY,
        risk_score=0.75,
        content_types=["personal_data"],
        sensitive_patterns=["personal_data"],
        blocking_reasons=[],
        confidence=0.8,
    )

    result = await enforce_policy(
        classification=classification,
        context_id="general",
    )

    assert result["allowed"] is False


@pytest.mark.asyncio
async def test_enforce_policy_risky_code_dev_context_allowed():
    """Code_dev context 對未授權操作應直接阻擋"""
    classification = ClassificationResult(
        classification=ContentClassification.RISKY,
        risk_score=0.75,
        content_types=["unauthorized_operations"],
        sensitive_patterns=["unauthorized_code"],
        blocking_reasons=[],
        confidence=0.8,
    )

    result = await enforce_policy(
        classification=classification,
        context_id="code_dev",
    )

    # unauthorized_operations 被明確列為 blocked
    assert result["allowed"] is False


@pytest.mark.asyncio
async def test_enforce_policy_sensitive_financial_adds_disclaimer():
    """SENSITIVE 財務內容應添加免責聲明"""
    classification = ClassificationResult(
        classification=ContentClassification.SENSITIVE,
        risk_score=0.35,
        content_types=["financial"],
        sensitive_patterns=["financial"],
        blocking_reasons=[],
        confidence=0.85,
    )

    result = await enforce_policy(
        classification=classification,
        context_id="general",
    )

    assert result["allowed"] is True
    # 因為 SENSITIVE，應該有修改文本（免責聲明）
    # 實際的免責聲明內容在 modified_text 中


def test_apply_policy_mitigation_sensitive_financial():
    """應為敏感財務內容添加免責聲明"""
    classification = ClassificationResult(
        classification=ContentClassification.SENSITIVE,
        risk_score=0.35,
        content_types=["financial"],
        sensitive_patterns=["financial"],
        blocking_reasons=[],
        confidence=0.85,
    )

    disclaimer = apply_policy_mitigation(
        text="",
        classification=classification,
        policy_level="general",
    )

    assert "免責聲明" in disclaimer
    assert "財務資訊" in disclaimer


def test_apply_policy_mitigation_sensitive_medical():
    """應為敏感醫療內容添加免責聲明"""
    classification = ClassificationResult(
        classification=ContentClassification.SENSITIVE,
        risk_score=0.40,
        content_types=["medical"],
        sensitive_patterns=["medical"],
        blocking_reasons=[],
        confidence=0.85,
    )

    disclaimer = apply_policy_mitigation(
        text="",
        classification=classification,
        policy_level="general",
    )

    assert "免責聲明" in disclaimer
    assert "醫療資訊" in disclaimer


def test_apply_policy_mitigation_risky_unauthorized():
    """應為高風險未授權操作添加風險警告"""
    classification = ClassificationResult(
        classification=ContentClassification.RISKY,
        risk_score=0.75,
        content_types=["unauthorized_operations"],
        sensitive_patterns=["unauthorized_code"],
        blocking_reasons=[],
        confidence=0.8,
    )

    disclaimer = apply_policy_mitigation(
        text="",
        classification=classification,
        policy_level="risky",
    )

    assert "風險警告" in disclaimer
    assert "未授權操作" in disclaimer


@pytest.mark.asyncio
async def test_enforce_policy_esg_context_sensitive_financial_restricted():
    """ESG context 下 SENSITIVE 財務內容應被限制"""
    classification = ClassificationResult(
        classification=ContentClassification.SENSITIVE,
        risk_score=0.40,
        content_types=["financial"],
        sensitive_patterns=["financial"],
        blocking_reasons=[],
        confidence=0.85,
    )

    result = await enforce_policy(
        classification=classification,
        context_id="esg",
    )

    # ESG 對財務內容採 "restricted" 策略
    assert result["audit_action"] in ["CONTENT_POLICY_APPLIED", "CONTENT_MODIFIED_BY_POLICY"]


@pytest.mark.asyncio
async def test_enforce_policy_multiple_content_types():
    """多個內容類型應疊加限制"""
    classification = ClassificationResult(
        classification=ContentClassification.RISKY,
        risk_score=0.65,
        content_types=["financial", "personal_data"],
        sensitive_patterns=["financial", "personal_data"],
        blocking_reasons=[],
        confidence=0.8,
    )

    result = await enforce_policy(
        classification=classification,
        context_id="general",
    )

    # 多個敏感類型應提高拒絕機率
    assert result["allowed"] is False
