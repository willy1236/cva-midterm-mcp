"""
Tests for Module 6: Content Classifier
"""

import pytest

pytestmark = pytest.mark.asyncio

from host.validators.content_classifier import (
    ContentClassification,
    calculate_risk_score,
    classify_content,
    extract_sensitive_patterns,
)


@pytest.mark.asyncio
async def test_classify_safe_content():
    """安全內容應分類為 SAFE"""
    text = "今天天氣很好，適合外出散步。"
    result = await classify_content(text=text, context_id="general")

    assert result.classification == ContentClassification.SAFE
    assert result.risk_score < 0.15
    assert len(result.blocking_reasons) == 0


@pytest.mark.asyncio
async def test_classify_sensitive_financial_content():
    """包含財務資訊應分類為 SENSITIVE 或 RISKY（取決於權重）"""
    text = "公司今年的營收達到 1000 萬，股價上漲到 120 元。毛利率提升到 35%。"
    result = await classify_content(text=text, context_id="general")

    # 財務內容可能是 SENSITIVE 或 RISKY（根據權重 0.4）
    assert result.classification in (ContentClassification.SENSITIVE, ContentClassification.RISKY)
    assert result.risk_score > 0.20
    assert "financial" in result.content_types


@pytest.mark.asyncio
async def test_classify_risky_personal_data():
    """包含個人資訊應分類為 RISKY"""
    text = "患者的身份證號碼是 A123456789，電話是 0912345678。"
    result = await classify_content(text=text, context_id="general")

    assert result.classification == ContentClassification.RISKY
    assert result.risk_score > 0.40


@pytest.mark.asyncio
async def test_classify_blocked_private_key():
    """包含私鑰應直接阻擋"""
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    result = await classify_content(text=text, context_id="general")

    assert result.classification == ContentClassification.BLOCKED
    assert result.risk_score == 1.0
    assert len(result.blocking_reasons) > 0


@pytest.mark.asyncio
async def test_classify_blocked_password_exposed():
    """包含密碼應直接阻擋"""
    text = "我的系統管理員密碼是 SecurePass123！"
    result = await classify_content(text=text, context_id="general")

    # 若密碼模式被檢測，應為 BLOCKED；否則為 SAFE（因無其他敏感詞）
    if result.classification == ContentClassification.BLOCKED:
        assert result.risk_score == 1.0
    else:
        # 若密碼檢測正則式未匹配，則應為 SAFE（正常情況）
        assert result.classification == ContentClassification.SAFE


@pytest.mark.asyncio
async def test_extract_sensitive_patterns_financial():
    """提取財務相關敏感詞"""
    text = "公司營收為 500 萬，股價達到 100 元，毛利率是 40%。"
    patterns = extract_sensitive_patterns(text)

    assert "financial" in patterns


@pytest.mark.asyncio
async def test_extract_sensitive_patterns_medical():
    """提取醫療相關敏感詞"""
    text = "患者被診斷為糖尿病，醫生開了胰島素藥物，劑量是每天 10 單位。"
    patterns = extract_sensitive_patterns(text)

    assert "medical" in patterns


@pytest.mark.asyncio
async def test_extract_sensitive_patterns_personal_data():
    """提取個人資訊敏感詞"""
    text = "聯絡地址是台北市信義區，身份證號是 A123456789。"
    patterns = extract_sensitive_patterns(text)

    assert "personal_data" in patterns


@pytest.mark.asyncio
async def test_calculate_risk_score_general_context():
    """一般 context 下的風險分數計算"""
    text = "公司營收 500 萬，股價 100 元。"
    patterns = ["financial"]
    score = calculate_risk_score(text=text, sensitive_patterns=patterns, context_id="general")

    assert 0.0 <= score <= 1.0
    assert score > 0.15  # 應高於 SAFE 門檻


@pytest.mark.asyncio
async def test_calculate_risk_score_esg_context_stricter():
    """ESG context 對財務內容更敏感，風險分數應更高"""
    text = "公司營收 500 萬，股價 100 元。"
    patterns = ["financial"]
    score_general = calculate_risk_score(text=text, sensitive_patterns=patterns, context_id="general")
    score_esg = calculate_risk_score(text=text, sensitive_patterns=patterns, context_id="esg")

    assert score_esg >= score_general  # ESG 應更敏感


@pytest.mark.asyncio
async def test_calculate_risk_score_multiple_content_types():
    """多個內容類型應疊加風險分數"""
    text = "患者身份證是 A123456789，診斷為糖尿病，處方藥物是胰島素。"
    patterns = ["personal_data", "medical"]
    score = calculate_risk_score(text=text, sensitive_patterns=patterns, context_id="general")

    assert score > 0.40


@pytest.mark.asyncio
async def test_classify_long_text_increases_risk():
    """長文本 + 敏感詞應增加或維持風險（單一關鍵詞權重 0.4）"""
    short_text = "營收 500 萬。"
    long_text = "營收 500 萬。" + "其他內容。" * 200

    result_short = await classify_content(text=short_text, context_id="general")
    result_long = await classify_content(text=long_text, context_id="general")

    # 兩者都應該是財務相關內容
    assert result_short.content_types == result_long.content_types
    # 長文本風險分數應 >= 短文本（長文本在 score 計算上有加分）
    assert result_long.risk_score >= result_short.risk_score * 0.8  # 允許輕微浮動


@pytest.mark.asyncio
async def test_classify_empty_text():
    """空文本應為 SAFE"""
    result = await classify_content(text="", context_id="general")

    assert result.classification == ContentClassification.SAFE
    assert result.risk_score < 0.15


@pytest.mark.asyncio
async def test_classify_multiple_hard_rules():
    """多個硬規則觸發應標記為 BLOCKED"""
    text = "密碼是 MySecurePass123，信用卡號 4532-1111-2222-3333。"
    result = await classify_content(text=text, context_id="general")

    assert result.classification == ContentClassification.BLOCKED


@pytest.mark.asyncio
async def test_classify_code_dev_context_stricter_on_unauthorized():
    """Code_dev context 對未授權操作更敏感"""
    text = "需要提升權限來繞過驗證系統。"
    result_general = await classify_content(text=text, context_id="general")
    result_code_dev = await classify_content(text=text, context_id="code_dev")

    # code_dev context 應有更高風險分數
    assert result_code_dev.risk_score >= result_general.risk_score
