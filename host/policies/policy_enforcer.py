"""
Module 6: Policy Enforcer — 動態政策執行引擎
根據內容分類結果與 context 政策決定是否允許、修改或阻擋輸出。
"""

from __future__ import annotations

from typing import Any

from host.audits.governance_logger import GovernanceLogger
from host.policies.config_loader import get_context_profile
from host.validators.content_classifier import ClassificationResult, ContentClassification


class PolicyLevel(str):
    """政策等級"""

    GENERAL = "general"
    SENSITIVE = "sensitive"
    RISKY = "risky"


async def enforce_policy(
    classification: ClassificationResult,
    context_id: str,
    profile_data: dict[str, Any] | None = None,
    logger: GovernanceLogger | None = None,
) -> dict[str, Any]:
    """
    根據分類結果與 context 政策決定是否阻擋、修改或允許輸出。

    Args:
        classification: ClassificationResult 物件（包含分類、風險分數等）
        context_id: 上下文 ID
        profile_data: context 的 profile 資料（若為 None 則自動讀取）
        logger: 審計記錄器

    Returns:
        {
            "allowed": bool,                      # 是否允許輸出
            "reason": str,                        # 若拒絕則提供原因
            "modified_text": str | None,          # 若修改則提供修改後文本
            "policy_level": str,                  # 應用的政策等級
            "audit_action": str,                  # 審計動作
            "details": dict[str, Any] | None,     # 額外詳情
        }

    流程:
        1. 根據 context 取得政策規則
        2. 根據分類結果決定是否直接阻擋
        3. 若允許，根據風險等級決定是否需要修改（免責聲明等）
        4. 返回最終決定
    """

    if profile_data is None:
        profile_data = get_context_profile(context_id)

    policy_rules = get_policy_rules(context_id, profile_data)
    policy_level = policy_rules.get("policy_level", PolicyLevel.GENERAL)

    # 決定是否阻擋
    if _should_block(classification, policy_rules):
        reason = f"內容被分類為 {classification.classification.value}，違反 {policy_level} 政策"
        if classification.blocking_reasons:
            reason += f"。原因：{'; '.join(classification.blocking_reasons)}"

        return {
            "allowed": False,
            "reason": reason,
            "modified_text": None,
            "policy_level": policy_level,
            "audit_action": "CONTENT_BLOCKED_BY_POLICY",
            "details": {
                "classification": classification.classification.value,
                "risk_score": classification.risk_score,
                "blocking_reasons": classification.blocking_reasons,
            },
        }

    # 決定是否需要修改（添加免責聲明等）
    modification_needed = classification.classification in (
        ContentClassification.SENSITIVE,
        ContentClassification.RISKY,
    )

    modified_text = None
    audit_action = "CONTENT_POLICY_APPLIED"

    if modification_needed:
        modified_text = apply_policy_mitigation(
            text="",  # 這裡傳空字符串，因為修改是在回應層進行的
            classification=classification,
            policy_level=policy_level,
        )
        audit_action = "CONTENT_MODIFIED_BY_POLICY"

    return {
        "allowed": True,
        "reason": None,
        "modified_text": modified_text,
        "policy_level": policy_level,
        "audit_action": audit_action,
        "details": {
            "classification": classification.classification.value,
            "risk_score": classification.risk_score,
            "content_types": classification.content_types,
            "sensitive_patterns": classification.sensitive_patterns,
        },
    }


def get_policy_rules(
    context_id: str,
    profile_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    從 context profile 取得已合併好的政策規則。
    """

    if profile_data is None:
        profile_data = get_context_profile(context_id)

    policy_rules = profile_data.get("policy_rules", {})
    if not isinstance(policy_rules, dict):
        return {}

    return policy_rules


def apply_policy_mitigation(
    text: str,
    classification: ClassificationResult,
    policy_level: str,
) -> str:
    """
    根據政策等級對文本進行修正（添加免責聲明、模糊敏感資訊等）。

    當前實作：
      - SENSITIVE 分類 + 金融/醫療內容 → 添加免責聲明
      - RISKY 分類 → 添加風險警告

    Args:
        text: 原始文本（通常為空，因為修改是在回應生成前進行的）
        classification: ClassificationResult
        policy_level: 政策等級

    Returns:
        修改後的文本前綴或免責聲明字符串
    """

    disclaimers = []

    if classification.classification == ContentClassification.SENSITIVE:
        if "financial" in classification.content_types:
            disclaimers.append("【免責聲明】本回覆涉及財務資訊，僅供參考，不構成投資建議。")
        if "medical" in classification.content_types:
            disclaimers.append("【免責聲明】本回覆涉及醫療資訊，不替代專業醫療意見。")

    if classification.classification == ContentClassification.RISKY:
        if "unauthorized_operations" in classification.content_types:
            disclaimers.append("【風險警告】本回覆涉及潛在未授權操作，請確保合規使用。")

    # 如果有多個 content_type，添加通用聲明
    if len(classification.content_types) > 1:
        disclaimers.append(f"【內容標記】本回覆包含 {', '.join(classification.content_types)} 相關內容。")

    return "\n".join(disclaimers) if disclaimers else ""


def _should_block(
    classification: ClassificationResult,
    policy_rules: dict[str, Any],
) -> bool:
    """
    判斷是否應該阻擋回應

    阻擋條件：
      1. 分類為 BLOCKED（硬規則觸發）
      2. 分類為 RISKY 且 policy_level >= "sensitive"
      3. 風險分數超過政策門檻

    Args:
        classification: ClassificationResult
        policy_level: 政策等級（"general", "sensitive", "risky"）

    Returns:
        是否應阻擋
    """

    # 條件 1：硬規則直接阻擋
    if classification.classification == ContentClassification.BLOCKED:
        return True

    content_type_policy = policy_rules.get("content_type_policy", {})
    if isinstance(content_type_policy, dict):
        for content_type in classification.content_types:
            if content_type_policy.get(content_type) == "blocked":
                return True

    policy_level = policy_rules.get("policy_level", PolicyLevel.GENERAL)

    # 條件 2：RISKY + 嚴格政策
    if classification.classification == ContentClassification.RISKY and policy_level in ("general", "sensitive"):
        return True

    # 條件 3：風險分數超過政策門檻（可選，未來強化）
    # （暫時不使用，因為分類已經基於分數決定）

    return False
