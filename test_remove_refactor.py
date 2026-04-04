from models import remove_tracked_case, add_user, add_tracked_case

PHONE = "+919999999999"
CASE = "TEST-CASE-123"

def test_refactor():
    print("🧪 Testing remove_tracked_case refactor...")
    
    # Setup: Ensure user and case exist
    user_id = add_user(PHONE)
    add_tracked_case(user_id, CASE)
    
    # Test Removal using Phone Number
    print(f"Attempting to remove case {CASE} for phone {PHONE}...")
    result = remove_tracked_case(PHONE, CASE)
    
    if result:
        print("✅ PASS: Case removed successfully using phone number.")
    else:
        print("❌ FAIL: Failed to remove case.")
        
    # Test Idempotency (removing again)
    print("Attempting to remove same case again...")
    result_2 = remove_tracked_case(PHONE, CASE)
    
    if not result_2:
        print("✅ PASS: Idempotency check passed (returned False for non-existent case).")
    else:
        print("❌ FAIL: Idempotency check failed.")

if __name__ == "__main__":
    test_refactor()
