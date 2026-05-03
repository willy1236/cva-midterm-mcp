"""
Module 3: Citation Verifier — 引用驗證與知識接地
驗證回應中的主張是否有可追溯的來源支持，降低幻覺與虛假引用。

驗證狀態：
  - VERIFIED: 主張完全符合來源內容
  - UNVERIFIED: 主張未找到對應來源
  - REJECTED: 主張與來源衝突（數值/語意不一致）
"""

from __future__ import annotations

import re
from typing import Any


def verify_citations(
    claims: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    strict_mode: bool = False,
    min_score: float = 0.5,
) -> dict[str, Any]:
    """
    驗證主張與來源之間的可追溯性。

    Args:
        claims: 主張清單，每筆包含 claim_id, text, cited_source_ids
        sources: 來源清單，每筆包含 source_id, content, locator_type, locator_value
        strict_mode: 若為 True，FAIL/REJECTED 時 blocking=True
        min_score: 相似度最小門檻 (0.0-1.0)

    Returns:
        {
            "overall_status": "PASS" | "PARTIAL" | "FAIL",
            "blocking": bool,
            "results": [
                {
                    "claim_id": str,
                    "status": "VERIFIED" | "REJECTED" | "UNVERIFIED",
                    "reason_codes": list[str],  # e.g. ["numeric_conflict", "semantic_mismatch"]
                    "score": float,             # 相似度分數
                    "matched_sources": list[str],  # 部分匹配的 source_id 清單
                }
            ],
            "summary": {
                "total_claims": int,
                "verified_count": int,
                "unverified_count": int,
                "rejected_count": int,
            },
            "blocking": bool,
        }
    """

    # 空主張集合 → 自動通過
    if not claims:
        return {
            "overall_status": "PASS",
            "blocking": False,
            "results": [],
            "summary": {
                "total_claims": 0,
                "verified_count": 0,
                "unverified_count": 0,
                "rejected_count": 0,
            },
        }

    # 驗證每個主張
    results = []
    verified_count = 0
    unverified_count = 0
    rejected_count = 0

    for claim in claims:
        claim_id = claim.get("claim_id", "unknown")
        claim_text = claim.get("text", "")
        cited_source_ids = claim.get("cited_source_ids", [])

        # 若未引用任何來源 → UNVERIFIED
        if not cited_source_ids:
            results.append(
                {
                    "claim_id": claim_id,
                    "status": "UNVERIFIED",
                    "reason_codes": ["no_source_cited"],
                    "score": 0.0,
                    "matched_sources": [],
                }
            )
            unverified_count += 1
            continue

        # 檢查引用的來源
        claim_result = {
            "claim_id": claim_id,
            "status": "UNVERIFIED",
            "reason_codes": [],
            "score": 0.0,
            "matched_sources": [],
        }

        best_score = 0.0
        conflict_detected = False

        for source_id in cited_source_ids:
            source = next((s for s in sources if s.get("source_id") == source_id), None)
            if source is None:
                continue

            source_content = source.get("content", "")

            # 檢查數值衝突
            if _detect_numeric_conflict(claim_text, source_content):
                conflict_detected = True
                if "numeric_conflict" not in claim_result["reason_codes"]:
                    claim_result["reason_codes"].append("numeric_conflict")
                continue

            # 計算相似度
            score = _calculate_semantic_similarity(claim_text, source_content)

            if score > best_score:
                best_score = score
                if score >= min_score:
                    claim_result["matched_sources"].append(source_id)

        # 決定狀態
        if conflict_detected:
            claim_result["status"] = "REJECTED"
            claim_result["score"] = best_score
            rejected_count += 1
        elif best_score >= min_score:
            claim_result["status"] = "VERIFIED"
            claim_result["score"] = best_score
            verified_count += 1
        else:
            # 沒有找到足夠相似的來源
            if not claim_result["reason_codes"]:
                claim_result["reason_codes"].append("semantic_mismatch")
            claim_result["status"] = "UNVERIFIED"
            claim_result["score"] = best_score
            unverified_count += 1

        results.append(claim_result)

    # 決定整體狀態
    total_claims = len(claims)
    if rejected_count > 0:
        overall_status = "FAIL"
        blocking = True
    elif unverified_count > 0:
        overall_status = "PARTIAL"
        blocking = strict_mode  # strict mode 下 PARTIAL 也會阻擋
    else:
        overall_status = "PASS"
        blocking = False

    return {
        "overall_status": overall_status,
        "blocking": blocking,
        "results": results,
        "summary": {
            "total_claims": total_claims,
            "verified_count": verified_count,
            "unverified_count": unverified_count,
            "rejected_count": rejected_count,
        },
    }


def validate_source_locator(source: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    驗證來源定位器的有效性。

    支援 locator_type:
      - "db_id": 資料庫 ID（格式 entity:id）
      - "page_number": 頁碼（1-9999）
      - "url_fragment": URL fragment（含 # 符號）
      - "timestamp": ISO 8601 時間戳
      - "other": 自由格式

    Args:
        source: 來源物件，包含 locator_type, locator_value

    Returns:
        (is_valid, error_list)
    """

    locator_type = source.get("locator_type", "")
    locator_value = source.get("locator_value", "")
    errors = []

    # 基礎檢查
    if not locator_type:
        errors.append("missing_locator_type")
        return False, errors

    if not locator_value or not isinstance(locator_value, str):
        errors.append("missing_locator_value")
        return False, errors

    # 根據 locator_type 驗證
    if locator_type == "db_id":
        # 格式：entity:id（無空格、特殊字符）
        if not re.match(r"^[a-zA-Z0-9_]+:[a-zA-Z0-9_]+$", locator_value):
            errors.append("invalid_db_id_locator")
            return False, errors

    elif locator_type == "page_number":
        # 格式：純數字，範圍 1-9999
        if not re.match(r"^[1-9]\d{0,3}$", locator_value):
            errors.append("invalid_page_number")
            return False, errors

    elif locator_type == "url_fragment":
        # 格式：#section-name
        if not locator_value.startswith("#"):
            errors.append("invalid_url_fragment_format")
            return False, errors

    elif locator_type == "timestamp":
        # 基礎 ISO 8601 格式檢查
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", locator_value):
            errors.append("invalid_timestamp_format")
            return False, errors

    # 若沒有錯誤，視為有效
    if not errors:
        return True, []

    return False, errors


def _detect_numeric_conflict(claim_text: str, source_text: str) -> bool:
    """
    檢測主張與來源之間是否存在數值衝突。

    例：
      - 主張說 120，來源說 100 → conflict
      - 主張說 25度，來源說 25度 → no conflict

    Args:
        claim_text: 主張文本
        source_text: 來源文本

    Returns:
        是否存在數值衝突
    """

    # 提取雙方的數值
    claim_numbers = re.findall(r"\d+(?:\.\d+)?", claim_text)
    source_numbers = re.findall(r"\d+(?:\.\d+)?", source_text)

    if not claim_numbers or not source_numbers:
        return False

    # 若有交集數值則無衝突
    claim_set = set(claim_numbers)
    source_set = set(source_numbers)

    if claim_set & source_set:
        return False

    # 檢查是否有相反的數值（例如 +100 vs -100）
    # 簡單實作：若主張與來源中都有數值但完全不重疊，視為潛在衝突
    # 為了避免過度誤判，只在以下情況判定衝突：
    #   1. 主張中有特定數值（如 "120"）
    #   2. 來源中有明確不同的數值（如 "100"）
    #   3. 兩個數值差異 > 10%

    if len(claim_numbers) == 1 and len(source_numbers) >= 1:
        claim_num = float(claim_numbers[0])
        for source_num_str in source_numbers:
            source_num = float(source_num_str)
            if source_num == 0:
                continue
            relative_diff = abs(claim_num - source_num) / source_num
            if relative_diff > 0.1:  # 超過 10% 差異
                return True

    return False


def _calculate_semantic_similarity(claim_text: str, source_text: str) -> float:
    """
    計算主張與來源之間的語意相似度。

    使用簡單詞集合重疊（Jaccard 相似度）+ TF-IDF 加權。

    Args:
        claim_text: 主張文本
        source_text: 來源文本

    Returns:
        相似度分數 0.0-1.0
    """

    # 簡單分詞（中文/英文）
    claim_tokens = _tokenize(claim_text)
    source_tokens = _tokenize(source_text)

    if not claim_tokens or not source_tokens:
        return 0.0

    # Jaccard 相似度：交集 / 聯集
    claim_set = set(claim_tokens)
    source_set = set(source_tokens)

    intersection = len(claim_set & source_set)
    union = len(claim_set | source_set)

    if union == 0:
        return 0.0

    jaccard_score = intersection / union

    # 調整：若来源明顯包含主張內容，增加分數
    if all(token in source_text for token in claim_tokens):
        jaccard_score = min(jaccard_score + 0.2, 1.0)

    return jaccard_score


def _tokenize(text: str) -> list[str]:
    """
    簡單分詞。

    支援中文與英文混合。

    Args:
        text: 待分詞文本

    Returns:
        詞元清單
    """

    # 轉小寫
    text = text.lower()

    # 移除標點符號但保留中文
    text = re.sub(r"[^\w\u4e00-\u9fff\s]", " ", text)

    # 分詞：英文詞 + 中文字
    tokens = []

    # 先用空格分割
    words = text.split()
    for word in words:
        if not word:
            continue

        # 如果是純英文或數字，保留
        if re.match(r"^[a-z0-9]+$", word):
            tokens.append(word)
        else:
            # 中文或混合，逐字分割
            for char in word:
                if re.match(r"[\u4e00-\u9fff]", char):
                    tokens.append(char)
                elif re.match(r"[a-z0-9]", char):
                    tokens.append(char)

    return [t for t in tokens if len(t) > 0]
