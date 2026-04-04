import logging
from cause_list_fetcher import parse_cause_list_entries

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_advance_list_parsing():
    # Mock text simulating an Advance Cause List
    mock_text = """
    23.01.2026
    ADVANCE CAUSE LIST
    
    COURT NO. 01
    HON'BLE THE CHIEF JUSTICE
    HON'BLE MR. JUSTICE NAVIN CHAWLA
    HON'BLE MR. JUSTICE TUSHAR RAO GEDELA
    
    1. W.P.(C) 1234/2024 vs STATE
    2. CRL.M.C. 5678/2024 vs ABC
    
    COURT NO. 02
    HON'BLE MR. JUSTICE SUBRAMONIUM PRASAD
    
    3. W.P.(C) 9999/2024 vs XYZ
    """
    
    print("Testing Advance Cause List Parsing...")
    entries, extracted_date = parse_cause_list_entries(mock_text)
    
    print(f"Extracted Date: {extracted_date}")
    print(f"Total Entries: {len(entries)}")
    
    for entry in entries:
        print("-" * 30)
        print(f"Case: {entry['case_no']}")
        print(f"Court: {entry['court']}")
        
    # Assertions
    assert extracted_date == "2026-01-23", "Date extraction failed"
    assert len(entries) == 3, "Entry count mismatch"
    
    # Check Court 1
    assert "COURT NO. 01" in entries[0]['court'], "Court 1 number missing"
    assert "CHIEF JUSTICE" in entries[0]['court'], "Court 1 judge missing"
    assert "NAVIN CHAWLA" in entries[0]['court'], "Court 1 judge missing"
    
    # Check Court 2
    assert "COURT NO. 02" in entries[2]['court'], "Court 2 number missing"
    assert "SUBRAMONIUM PRASAD" in entries[2]['court'], "Court 2 judge missing"
    
    print("\nSUCCESS: Advance Cause List parsing verified.")

def test_regular_list_parsing():
    # Mock text simulating a Regular Cause List (no date header)
    mock_text = """
    CAUSE LIST FOR 22.01.2026
    
    COURT NO. 05
    HON'BLE MR. JUSTICE SOMEONE
    
    1. W.P.(C) 1111/2024
    """
    
    print("\nTesting Regular Cause List Parsing...")
    entries, extracted_date = parse_cause_list_entries(mock_text)
    
    print(f"Extracted Date: {extracted_date}")
    print(f"Total Entries: {len(entries)}")
    
    for entry in entries:
        print("-" * 30)
        print(f"Case: {entry['case_no']}")
        print(f"Court: {entry['court']}")
        
    # Assertions
    assert extracted_date is None, "Regular list should not extract date via this method"
    assert len(entries) == 1, "Entry count mismatch"
    # Legacy logic just takes the last header line seen
    assert "HON'BLE MR. JUSTICE SOMEONE" in entries[0]['court'] or "COURT NO. 05" in entries[0]['court']
    
    print("\nSUCCESS: Regular Cause List parsing verified (Legacy behavior preserved).")

if __name__ == "__main__":
    test_advance_list_parsing()
    test_regular_list_parsing()
