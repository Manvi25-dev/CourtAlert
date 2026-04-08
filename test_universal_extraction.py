"""Test universal extraction function for CNR and case numbers."""
import re
from case_matcher import normalize_case_number


def extract_identifiers_universal(message_text: str) -> dict | None:
    """Universal extraction for CNR and case numbers. NEVER rejects valid identifiers."""
    msg = (message_text or "").upper().strip()
    print(f"RAW_MESSAGE: {msg}")
    
    # Try CNR first: 4-letter prefix + 12-13 digits (16 total)
    cnr_match = re.search(r"([A-Z]{4}\d{12,13})", msg)
    if cnr_match:
        cnr = cnr_match.group(1)
        print(f"✅ DETECTED_CNR: {cnr}")
        return {"type": "CNR", "value": cnr}
    
    # Try case number: handles dots (CRL.M.C., CS.OS., etc.)
    case_match = re.search(
        r"([A-Z][A-Z\.]{1,8})[\s\-/]?(\d{1,7})(?:[\s\-/]*(?:OF)?[\s\-/]*(\d{2,4}))?",
        msg
    )
    if case_match:
        case_type = case_match.group(1)
        case_no = case_match.group(2)
        case_year = case_match.group(3) or ""
        
        if len(case_no) >= 2:
            case_type_clean = case_type.replace(".", "")
            case_value_clean = f"{case_type_clean}/{case_no}" + (f"/{case_year}" if case_year else "")
            normalized = normalize_case_number(case_value_clean) or normalize_case_number(case_type + "/" + case_no + (f"/{case_year}" if case_year else ""))
            if normalized:
                case_value = normalized
            else:
                case_value = case_value_clean
            
            print(f"✅ DETECTED_CASE: {case_value}")
            return {"type": "CASE_NUMBER", "value": case_value}
    
    print(f"❌ NO_IDENTIFIER_FOUND")
    return None


if __name__ == "__main__":
    test_inputs = [
        "CNR:GJDH020024462018",
        "add case GJDH020024462018",
        "LPA 171/2019",
        "case 171 of 2019",
        "CRL.M.C. 123/2024",
        "HRS0010076892025",
        "add case CNR GJDH020024462018",
        "track lpa/171/2019",
    ]

    print("=" * 70)
    print("UNIVERSAL EXTRACTION VALIDATION")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    for test_input in test_inputs:
        print(f"\n📝 Input: '{test_input}'")
        result = extract_identifiers_universal(test_input)
        if result:
            print(f"   Type: {result['type']}")
            print(f"   Value: {result['value']}")
            passed += 1
        else:
            print(f"   ❌ FAILED: Could not extract")
            failed += 1
        print("-" * 70)
    
    print(f"\n✅ PASSED: {passed}/{len(test_inputs)}")
    if failed > 0:
        print(f"❌ FAILED: {failed}/{len(test_inputs)}")
