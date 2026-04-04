import sys
import os
from whatsapp_handler import handle_add_case

# Mock user
USER_ID = 1
USER_PHONE = "+919999999999"

def test_add_case():
    print("🧪 Testing Add Case Logic...")
    
    # Test 1: Case that exists in cache
    # CMAPPL. 2757/2026
    print("\n[Test 1] Adding case present in cache: CMAPPL. 2757/2026")
    case_info_1 = {'case_number': 'CMAPPL. 2757/2026', 'court': 'Delhi High Court'}
    response_1 = handle_add_case(USER_ID, USER_PHONE, case_info_1)
    print(f"Response:\n{response_1.message_text}")
    
    if "HEARING FOUND" in response_1.message_text:
        print("✅ PASS: Correctly identified listed case.")
    else:
        print("❌ FAIL: Did not identify listed case.")

    # Test 2: Case that does NOT exist
    print("\n[Test 2] Adding case NOT in cache: W.P.(C) 9999/2099")
    case_info_2 = {'case_number': 'W.P.(C) 9999/2099', 'court': 'Delhi High Court'}
    response_2 = handle_add_case(USER_ID, USER_PHONE, case_info_2)
    print(f"Response:\n{response_2.message_text}")
    
    if "Tracking Active" in response_2.message_text:
        print("✅ PASS: Correctly identified unlisted case.")
    else:
        print("❌ FAIL: Incorrect response for unlisted case.")

if __name__ == "__main__":
    test_add_case()
