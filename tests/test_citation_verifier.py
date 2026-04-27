from __future__ import annotations

from host.validators.citation_verifier import validate_source_locator, verify_citations


def test_verify_all_claims_verified() -> None:
    claims = [
        {"claim_id": "c1", "text": "台北今天溫度是25度", "cited_source_ids": ["s1"]},
    ]
    sources = [
        {
            "source_id": "s1",
            "content": "台北今天溫度是25度，天氣晴朗",
            "locator_type": "db_id",
            "locator_value": "weather:001",
        }
    ]

    result = verify_citations(claims=claims, sources=sources, strict_mode=True, min_score=0.5)
    assert result["overall_status"] == "PASS"
    assert result["blocking"] is False
    assert result["summary"]["verified_count"] == 1


def test_verify_partial_with_unverified() -> None:
    claims = [
        {"claim_id": "c1", "text": "台北今天溫度是25度", "cited_source_ids": ["s1"]},
        {"claim_id": "c2", "text": "高雄今天下雪", "cited_source_ids": ["s1"]},
    ]
    sources = [
        {
            "source_id": "s1",
            "content": "台北今天溫度是25度，天氣晴朗",
            "locator_type": "db_id",
            "locator_value": "weather:001",
        }
    ]

    result = verify_citations(claims=claims, sources=sources, strict_mode=False, min_score=0.5)
    assert result["overall_status"] == "PARTIAL"
    assert result["blocking"] is False
    assert result["summary"]["verified_count"] == 1
    assert result["summary"]["unverified_count"] == 1


def test_verify_rejected_on_numeric_conflict() -> None:
    claims = [
        {"claim_id": "c1", "text": "營收是120", "cited_source_ids": ["s1"]},
    ]
    sources = [
        {
            "source_id": "s1",
            "content": "營收是100，較去年成長",
            "locator_type": "db_id",
            "locator_value": "finance:001",
        }
    ]

    result = verify_citations(claims=claims, sources=sources, strict_mode=True, min_score=0.4)
    assert result["overall_status"] == "FAIL"
    assert result["blocking"] is True
    assert result["results"][0]["status"] == "REJECTED"
    assert "numeric_conflict" in result["results"][0]["reason_codes"]


def test_invalid_source_locator_rejected() -> None:
    source = {
        "source_id": "s1",
        "content": "台北今天溫度是25度",
        "locator_type": "db_id",
        "locator_value": "invalid value with spaces",
    }
    valid, errors = validate_source_locator(source)
    assert valid is False
    assert "invalid_db_id_locator" in errors


def test_strict_mode_blocks_on_rejected() -> None:
    claims = [{"claim_id": "c1", "text": "營收是120", "cited_source_ids": ["s1"]}]
    sources = [
        {
            "source_id": "s1",
            "content": "營收是100",
            "locator_type": "db_id",
            "locator_value": "finance:001",
        }
    ]

    result = verify_citations(claims=claims, sources=sources, strict_mode=True, min_score=0.4)
    assert result["blocking"] is True


def test_non_strict_mode_allows_partial() -> None:
    claims = [{"claim_id": "c1", "text": "高雄今天下雪", "cited_source_ids": ["s1"]}]
    sources = [
        {
            "source_id": "s1",
            "content": "台北今天溫度是25度",
            "locator_type": "db_id",
            "locator_value": "weather:001",
        }
    ]

    result = verify_citations(claims=claims, sources=sources, strict_mode=False, min_score=0.6)
    assert result["overall_status"] == "PARTIAL"
    assert result["blocking"] is False


def test_empty_claims_deterministic_result() -> None:
    result = verify_citations(claims=[], sources=[], strict_mode=True, min_score=0.5)
    assert result["overall_status"] == "PASS"
    assert result["blocking"] is False
    assert result["summary"]["total_claims"] == 0
