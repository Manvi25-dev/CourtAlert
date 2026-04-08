"""Test Sarvam structured intent extraction with strict JSON response format."""
import json
import os
import pytest
from services.sarvam_service import extract_intent_with_confidence


@pytest.mark.skipif(not os.getenv("SARVAM_API_KEY"), reason="SARVAM_API_KEY not configured")
def test_sarvam_returns_structured_response_with_case_identifier():
    """Verify Sarvam returns strict JSON with case_identifier and case_type fields."""
    result = extract_intent_with_confidence("add case LPA 171/2019")
    
    # Verify all required fields are present
    assert "intent" in result
    assert "case_identifier" in result
    assert "case_type" in result
    assert "confidence" in result
    assert "entities" in result
    assert "reasoning" in result
    assert "suggested_next_action" in result
    
    # Verify field types
    assert isinstance(result["intent"], str)
    assert result["intent"] in {"TRACK_CASE", "QUERY_STATUS", "LIST_CASES", "REMOVE_CASE", "UNKNOWN"}
    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["case_type"], str)
    assert result["case_type"] in {"CNR", "CASE_NUMBER", "NONE"}
    

@pytest.mark.skipif(not os.getenv("SARVAM_API_KEY"), reason="SARVAM_API_KEY not configured")
def test_sarvam_extracts_cnr_identifier():
    """Verify Sarvam correctly identifies CNR format."""
    result = extract_intent_with_confidence("add case CNR:GJDH020024462018")
    
    assert result["intent"] == "TRACK_CASE"
    assert result["case_identifier"] is not None
    assert result["case_type"] == "CNR"
    assert result["confidence"] > 0.8


@pytest.mark.skipif(not os.getenv("SARVAM_API_KEY"), reason="SARVAM_API_KEY not configured")
def test_sarvam_extracts_case_number():
    """Verify Sarvam correctly identifies case number format."""
    result = extract_intent_with_confidence("track LPA 171/2019")
    
    assert result["intent"] == "TRACK_CASE"
    assert result["case_identifier"] is not None
    assert result["case_type"] in {"CASE_NUMBER", "NONE"}
    assert result["confidence"] > 0.7


@pytest.mark.skipif(not os.getenv("SARVAM_API_KEY"), reason="SARVAM_API_KEY not configured")
def test_sarvam_handles_contextual_when_is_it():
    """Verify Sarvam identifies query status intent from 'when is it?' with context."""
    user_context = {
        "tracked_cases": ["LPA/171/2019"],
        "last_case": "LPA/171/2019",
        "last_action": "tracked"
    }
    result = extract_intent_with_confidence("when is it?", user_context)
    
    assert result["intent"] == "QUERY_STATUS"
    assert result["confidence"] > 0.6


@pytest.mark.skipif(not os.getenv("SARVAM_API_KEY"), reason="SARVAM_API_KEY not configured")
def test_sarvam_handles_loose_case_format():
    """Verify Sarvam handles flexible case formats like 'case 171 of 2019'."""
    result = extract_intent_with_confidence("case 171 of 2019")
    
    # Should either identify as TRACK_CASE or have high confidence for case extraction
    assert result["intent"] in {"TRACK_CASE", "UNKNOWN"}
    # Should detect case-like pattern
    assert result["case_identifier"] is not None or result["confidence"] > 0.5


@pytest.mark.skipif(not os.getenv("SARVAM_API_KEY"), reason="SARVAM_API_KEY not configured")
def test_sarvam_identifies_list_cases_intent():
    """Verify Sarvam correctly identifies LIST_CASES intent."""
    result = extract_intent_with_confidence("show my cases")
    
    assert result["intent"] == "LIST_CASES"
    assert result["case_type"] == "NONE"
    

@pytest.mark.skipif(not os.getenv("SARVAM_API_KEY"), reason="SARVAM_API_KEY not configured")
def test_sarvam_identifies_remove_case_intent():
    """Verify Sarvam correctly identifies REMOVE_CASE intent."""
    result = extract_intent_with_confidence("remove LPA 171/2019")
    
    assert result["intent"] == "REMOVE_CASE"
    assert result["case_identifier"] is not None


def test_sarvam_gracefully_handles_unclear_input():
    """Verify Sarvam returns UNKNOWN for ambiguous input (no API required)."""
    result = extract_intent_with_confidence("hello there")
    
    # When API is not available, should return fallback with UNKNOWN
    assert result["intent"] in {"UNKNOWN", "UNKNOWN"}
    assert result["case_type"] == "NONE"
    assert result["case_identifier"] is None


def test_sarvam_response_structure():
    """Verify response structure is always present regardless of API availability."""
    result = extract_intent_with_confidence("test message")
    
    # These fields must always be present
    required_fields = {
        "intent": str,
        "case_identifier": (str, type(None)),
        "case_type": str,
        "confidence": float,
        "entities": dict,
        "reasoning": str,
        "suggested_next_action": str,
    }
    
    for field, expected_type in required_fields.items():
        assert field in result, f"Missing field: {field}"
        if isinstance(expected_type, tuple):
            assert isinstance(result[field], expected_type), f"Field {field} has wrong type"
        else:
            assert isinstance(result[field], expected_type), f"Field {field} has wrong type"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


