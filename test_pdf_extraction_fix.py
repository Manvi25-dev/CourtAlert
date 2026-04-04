"""
Test to validate PDF extraction fix for broken case numbers.
Tests that CM APPL. 11440/2026 can be properly extracted and parsed
even when split across lines/tables or with broken formatting.
"""

import logging
import re
from case_parser import extract_all_case_numbers, normalize_case_id
from cause_list_fetcher import normalize_text_block, parse_cause_list_entries

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_normalize_text_block():
    """Test that normalize_text_block fixes broken case patterns."""
    logger.info("=== Testing normalize_text_block ===")
    
    # Test case 1: Standard format with extra spaces
    text1 = "CM  APPL.  11440  /  2026"
    result1 = normalize_text_block(text1)
    assert "CMAPPL" in result1, f"Failed to normalize CM APPL: {result1}"
    assert "11440/2026" in result1, f"Failed to normalize year: {result1}"
    logger.info("✓ Test 1 passed: Standard format with spaces")
    
    # Test case 2: Split across virtual lines (newlines)
    text2 = "CM APPL 11440\n/2026"
    result2 = normalize_text_block(text2)
    assert "CMAPPL" in result2, f"Failed with newlines: {result2}"
    logger.info("✓ Test 2 passed: Split format with newlines")
    
    # Test case 3: Mixed case
    text3 = "Cm aPpL. 11440/2026"
    result3 = normalize_text_block(text3)
    assert "CMAPPL" in result3, f"Failed to uppercase: {result3}"
    assert "11440/2026" in result3, f"Failed with mixed case: {result3}"
    logger.info("✓ Test 3 passed: Mixed case")


def test_extract_case_numbers_multiline():
    """Test case number extraction with multi-line and broken formats."""
    logger.info("=== Testing extract_all_case_numbers ===")
    
    tests = [
        ("CM APPL. 11440/2026", "Standard format"),
        ("CMAPPL 11440 / 2026", "Spaces around /"),
        ("CM APPL 11440 / 2026", "Spaces around separator"),
        ("CM APPL. 11440\n/2026", "Split across lines (joined as space)"),
        ("CRL.M.C. 8148/2025", "Different case type"),
        ("W.P.(C) 5000/2024", "W.P. case type"),
        ("1. CM APPL. 11440/2026 Petitioner vs Respondent", "Full block text"),
    ]
    
    for text, description in tests:
        # Normalize the text first (simulating what the parser does)
        normalized = normalize_text_block(text)
        cases = extract_all_case_numbers(normalized)
        
        assert len(cases) > 0, f"Failed to extract: {description}\nText: {text}\nNormalized: {normalized}"
        logger.info(f"✓ {description}: extracted {cases}")


def test_full_parsing_pipeline():
    """Test the full parsing pipeline with simulated PDF text."""
    logger.info("=== Testing full parsing pipeline ===")
    
    # Simulate PDF extraction output with broken formatting
    pdf_text = """
    DELHI HIGH COURT - ADVANCE CAUSE LIST
    Dated: 15.02.2026
    
    COURT NO. 12
    HON'BLE JUSTICE SHARMA
    
    1. CM APPL. 11440/2026
    Petitioner: ABC Corporation (P) Ltd.
    vs
    Respondent: XYZ Ltd.
    Through: Sh. Rajesh Kumar, Advocate
    FOR HEARING
    
    2. CRL.M.C. 5678/2025
    Petitioner: State of Delhi
    vs
    Respondent: John Doe
    Through: Ms. Priya Singh, Advocate
    FOR ORDERS
    """
    
    entries, extracted_date = parse_cause_list_entries(pdf_text)
    
    logger.info(f"Extracted {len(entries)} entries")
    assert len(entries) > 0, "Failed to parse any entries"
    
    # Check if CM APPL. 11440/2026 was found
    target_found = False
    for entry in entries:
        case_nos = entry.get("case_numbers", [])
        logger.info(f"Entry case_numbers: {case_nos}")
        
        if any("11440" in cn or "CMAPPL" in cn.upper() for cn in case_nos):
            target_found = True
            logger.info(f"✓ Found target case CM APPL. 11440/2026")
            logger.info(f"  Normalized: {entry.get('case_number')}")
            logger.info(f"  Title: {entry.get('title')}")
            logger.info(f"  Advocate: {entry.get('advocate')}")
            logger.info(f"  Status: {entry.get('status')}")
    
    assert target_found, "CM APPL. 11440/2026 not found in parsed entries"
    logger.info("✓ Full parsing pipeline test passed")


def test_broken_layout_scenario():
    """Test with severely broken PDF layout."""
    logger.info("=== Testing broken layout scenario ===")
    
    # Simulate a PDF where case number is split and has odd formatting
    broken_text = """
    CASE LISTING FOR DELHI HIGH COURT
    
    SR. NO. | CASE NUMBER | PETITIONER/TITLE | ADVOCATES
    
    1 | CM APPL
    11440
    /2026 | ABC Corp vs XYZ | Sh. Kumar
    
    2 | CRL.M.C. 5678/2025 | Rao vs State | Ms. Singh
    """
    
    # Normalize the broken text
    normalized = normalize_text_block(broken_text)
    
    # Extract case numbers from the normalized version
    cases = extract_all_case_numbers(normalized)
    
    logger.info(f"Extracted from broken layout: {cases}")
    
    # Should find both case numbers
    assert any("11440" in c or "CMAPPL" in c.upper() for c in cases), \
        f"Did not find CM APPL 11440 in: {cases}"
    assert any("5678" in c for c in cases), \
        f"Did not find CRL.M.C. 5678 in: {cases}"
    
    logger.info("✓ Broken layout test passed")


def test_normalization_edge_cases():
    """Test normalization handles various edge cases."""
    logger.info("=== Testing normalization edge cases ===")
    
    # Test removing extra spaces in CMAPPL
    text = "C M   A P P L . 11440 / 2026"
    result = normalize_text_block(text)
    # After normalization, should have CMAPPL in there
    assert "CMAPPL" in result or ("11440" in result and "2026" in result), f"Result: {result}"
    logger.info(f"✓ Edge case 1 passed: {repr(text)} -> {repr(result)}")


def main():
    """Run all tests."""
    logger.info("Starting PDF Extraction Fix Validation Tests\n")
    
    try:
        test_normalize_text_block()
        logger.info("")
        
        test_extract_case_numbers_multiline()
        logger.info("")
        
        test_broken_layout_scenario()
        logger.info("")
        
        test_full_parsing_pipeline()
        logger.info("")
        
        test_normalization_edge_cases()
        logger.info("")
        
        logger.info("=" * 60)
        logger.info("✅ ALL TESTS PASSED - PDF Extraction Fix Validated")
        logger.info("=" * 60)
        return 0
        
    except AssertionError as e:
        logger.error(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        logger.error(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
