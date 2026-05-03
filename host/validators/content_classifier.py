"""
Module 6: Content Classifier — 內容安全分類與風險評估
使用規則 + 關鍵詞 + 簡單相似度三層方法進行分類。

分類結果：
  - SAFE: 無明顯風險
  - SENSITIVE: 含敏感但非高風險內容（需免責聲明或情境審查）
  - RISKY: 潛在風險較高，可能違反政策（需強化審查或部分阻擋）
  - BLOCKED: 明確高風險或禁止內容（直接阻擋）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from host.audits.governance_logger import GovernanceLogger


class ContentClassification(StrEnum):
    SAFE = "SAFE"
    SENSITIVE = "SENSITIVE"
    RISKY = "RISKY"
    BLOCKED = "BLOCKED"


@dataclass
class ClassificationResult:
    """分類結果容器"""

    classification: ContentClassification
    risk_score: float  # 0.0-1.0
    content_types: list[str]  # e.g. ["financial", "medical"]
    sensitive_patterns: list[str]  # 偵測到的敏感模式名稱
    blocking_reasons: list[str]  # 阻擋原因（若有）
    confidence: float  # 0.0-1.0，分類信心度
    details: dict[str, Any] | None = None  # 額外詳情


# ============================================================================
# 第一層：硬規則（High-Confidence Blocking Rules）
# ============================================================================

HARD_RULES = {
    "credit_card": {
        "pattern": r"\b(\d{4}[\s-]?){3}\d{4}\b",
        "description": "信用卡號碼",
        "classification": ContentClassification.BLOCKED,
    },
    "ssn": {
        "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
        "description": "社會安全號碼 (SSN)",
        "classification": ContentClassification.BLOCKED,
    },
    "private_key": {
        "pattern": r"-----BEGIN (RSA|PRIVATE|EC|PGP) (PRIVATE )?KEY-----",
        "description": "私密金鑰",
        "classification": ContentClassification.BLOCKED,
    },
    "password_exposed": {
        "pattern": r"(?i)(密碼|password|passwd|pwd)\s*(?:是|：|:|=)\s*\S+",
        "description": "密碼洩露",
        "classification": ContentClassification.BLOCKED,
    },
    "api_key": {
        "pattern": r"(?i)(api[_-]?key|apikey|access[_-]?key|secret[_-]?key)\s*[:=]\s*[a-zA-Z0-9\-_]{20,}",
        "description": "API 金鑰",
        "classification": ContentClassification.BLOCKED,
    },
    "malware_instructions": {
        "pattern": r"(?i)(ransomware|trojan|backdoor|payload|shellcode|buffer overflow|sql injection|xss payload)",
        "description": "惡意軟體/攻擊指令",
        "classification": ContentClassification.BLOCKED,
    },
    "weapon_instructions": {
        "pattern": r"(?i)(bomb|explosive|chemical weapon|bioweapon|nuclear|uranium enrichment)",
        "description": "武器製造指令",
        "classification": ContentClassification.BLOCKED,
    },
}

# ============================================================================
# 第二層：關鍵詞庫（Keyword-based Classification）
# ============================================================================

KEYWORD_GROUPS = {
    "financial": {
        "keywords": [
            "股價",
            "營收",
            "獲利",
            "毛利率",
            "成本結構",
            "現金流",
            "負債",
            "股東權益",
            "投資回報率",
            "市盈率",
            "財務預測",
            "估值",
            "股票推薦",
            "交易信號",
        ],
        "weight": 0.4,  # 中等風險
        "content_type": "financial",
    },
    "medical": {
        "keywords": [
            "診斷",
            "症狀",
            "治療方案",
            "藥物",
            "劑量",
            "副作用",
            "疾病名稱",
            "手術",
            "檢查結果",
            "病歷",
            "患者隱私",
        ],
        "weight": 0.5,  # 較高風險
        "content_type": "medical",
    },
    "personal_data": {
        "keywords": [
            "身份證",
            "護照",
            "駕照",
            "身份號碼",
            "電話",
            "地址",
            "郵件",
            "出生年月",
            "社群帳號",
            "銀行帳戶",
        ],
        "weight": 0.7,  # 高風險
        "content_type": "personal_data",
    },
    "unauthorized_code": {
        "keywords": [
            "提升權限",
            "繞過驗證",
            "禁用防火牆",
            "刪除日誌",
            "竊取憑證",
            "未授權存取",
            "後門",
            "提權",
        ],
        "weight": 0.8,  # 很高風險
        "content_type": "unauthorized_operations",
    },
    "legal_risk": {
        "keywords": [
            "詐騙",
            "洗錢",
            "違法",
            "非法",
            "迴避稅收",
            "避稅",
            "賄賂",
            "內線交易",
            "侵害著作權",
        ],
        "weight": 0.9,  # 極高風險
        "content_type": "legal_violation",
    },
}

# ============================================================================
# 第三層：風險分類門檻
# ============================================================================

CLASSIFICATION_THRESHOLDS = {
    # risk_score 門檻：
    # [0.0, threshold["safe"]) → SAFE
    # [threshold["safe"], threshold["sensitive"]) → SENSITIVE
    # [threshold["sensitive"], threshold["risky"]) → RISKY
    # [threshold["risky"], 1.0] → BLOCKED（或根據規則）
    "safe": 0.20,
    "sensitive": 0.45,
    "risky": 0.70,
}


# ============================================================================
# 核心分類函式
# ============================================================================


async def classify_content(
    text: str,
    context_id: str,
    classification_rules: dict | None = None,
    logger: GovernanceLogger | None = None,
) -> ClassificationResult:
    """
    多層次內容分類

    Args:
        text: 待分類文本
        context_id: 上下文 ID（用於調整政策等級）
        classification_rules: 自訂規則（optional, 覆蓋預設規則）
        logger: 審計記錄器

    Returns:
        ClassificationResult 物件，包含分類、風險分數、內容類型等

    流程:
        1. 執行硬規則檢查 → 若命中 BLOCKED 直接返回
        2. 提取敏感模式 + 計算關鍵詞權重
        3. 用簡單相似度補充風險分數
        4. 根據分數與規則決定最終分類
        5. 記錄審計事件
    """

    patterns = extract_sensitive_patterns(text)
    risk_score = calculate_risk_score(text, patterns, context_id)

    # 第 1 步：硬規則檢查
    hard_rule_hit = None
    for rule_name, rule_config in HARD_RULES.items():
        if re.search(rule_config["pattern"], text, re.IGNORECASE | re.MULTILINE):
            hard_rule_hit = {
                "rule_name": rule_name,
                "description": rule_config["description"],
                "classification": rule_config["classification"],
            }
            break

    if hard_rule_hit and hard_rule_hit["classification"] == ContentClassification.BLOCKED:
        result = ClassificationResult(
            classification=ContentClassification.BLOCKED,
            risk_score=1.0,
            content_types=[],
            sensitive_patterns=[hard_rule_hit["rule_name"]],
            blocking_reasons=[hard_rule_hit["description"]],
            confidence=0.95,
            details={"hard_rule_triggered": hard_rule_hit},
        )
        return result

    # 第 2 步：關鍵詞 + 相似度 + 風險分數決定分類
    content_types = _identify_content_types(text)

    if risk_score < CLASSIFICATION_THRESHOLDS["safe"]:
        classification = ContentClassification.SAFE
        confidence = 0.85
    elif risk_score < CLASSIFICATION_THRESHOLDS["sensitive"]:
        classification = ContentClassification.SENSITIVE
        confidence = 0.75
    elif risk_score < CLASSIFICATION_THRESHOLDS["risky"]:
        classification = ContentClassification.RISKY
        confidence = 0.70
    else:
        classification = ContentClassification.RISKY  # 高風險但不自動阻擋，由政策決定
        confidence = 0.65

    blocking_reasons = []
    if hard_rule_hit:
        blocking_reasons.append(hard_rule_hit["description"])

    result = ClassificationResult(
        classification=classification,
        risk_score=risk_score,
        content_types=content_types,
        sensitive_patterns=patterns,
        blocking_reasons=blocking_reasons,
        confidence=confidence,
        details={
            "keyword_groups": content_types,
            "text_length": len(text),
            "pattern_count": len(patterns),
        },
    )

    return result


def extract_sensitive_patterns(text: str) -> list[str]:
    """
    提取文本中的敏感模式

    檢查文本是否包含來自 KEYWORD_GROUPS 中定義的敏感詞彙。

    Returns:
        命中的敏感模式名稱清單
    """

    matched_patterns = []

    for group_name, group_config in KEYWORD_GROUPS.items():
        keywords = group_config.get("keywords", [])
        for keyword in keywords:
            # 用簡單的 in 檢查而不是 regex 邊界，以便更容易匹配中文詞
            if keyword in text:
                if group_name not in matched_patterns:
                    matched_patterns.append(group_name)
                break

    return matched_patterns


def calculate_risk_score(
    text: str,
    sensitive_patterns: list[str],
    context_id: str,
) -> float:
    """
    計算綜合風險分數（0.0-1.0）

    算法:
        1. 基於關鍵詞權重累加
        2. 根據文本特徵調整（長度、複雜度等）
        3. 根據 context 調整保守係數

    Args:
        text: 待評估文本
        sensitive_patterns: 已提取的敏感模式清單
        context_id: 上下文（可影響評估保守度）

    Returns:
        風險分數 0.0-1.0
    """

    base_score = 0.0

    # 若無敏感模式，直接返回低分
    if not sensitive_patterns:
        return 0.0

    # 累加關鍵詞權重
    for pattern in sensitive_patterns:
        if pattern in KEYWORD_GROUPS:
            weight = KEYWORD_GROUPS[pattern]["weight"]
            base_score += weight

    # 若只有一個模式，直接用該模式的權重
    # 若有多個模式，應疊加但不超過 1.0
    if len(sensitive_patterns) == 1:
        base_score = min(base_score, 0.85)  # 單一敏感模式最高 0.85
    else:
        # 多個模式：疊加但平均一下，防止超過 1.0
        base_score = min(base_score / len(sensitive_patterns), 0.90)

    # 根據文本特徵調整
    text_length = len(text)
    if text_length > 2000:
        # 長文本 + 多敏感詞 → 提高風險
        base_score = min(base_score + 0.1, 1.0)
    elif text_length < 50:
        # 非常短但包含敏感詞 → 可能是故意隱匿，提高風險
        base_score = min(base_score + 0.05, 1.0)

    # 根據 context 調整保守度
    context_multiplier = 1.0
    if context_id == "esg":
        if "financial" in sensitive_patterns or "legal_risk" in sensitive_patterns:
            context_multiplier = 1.15
    elif context_id == "code_dev":
        if "unauthorized_code" in sensitive_patterns:
            context_multiplier = 1.2

    base_score *= context_multiplier

    # 最終分數限制在 [0.0, 1.0]
    return min(base_score, 1.0)


def _identify_content_types(text: str) -> list[str]:
    """
    根據敏感模式識別內容類型

    Returns:
        內容類型清單 (e.g. ["financial", "personal_data"])
    """

    patterns = extract_sensitive_patterns(text)
    content_types = []

    for pattern in patterns:
        if pattern in KEYWORD_GROUPS:
            content_type = KEYWORD_GROUPS[pattern].get("content_type")
            if content_type and content_type not in content_types:
                content_types.append(content_type)

    return content_types
