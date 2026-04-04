from case_matcher import process_matches_and_generate_alerts
from models import add_user, add_tracked_case

PHONE = "+917777777777"
CASE = "TEST-LOG-CASE/2026"

def test_matcher_logging():
    print("🧪 Testing Matcher Logging Directly...")
    
    # Setup
    user_id = add_user(PHONE)
    case_id = add_tracked_case(user_id, CASE)
    
    # Mock Match
    tracked_case = {
        'id': case_id,
        'user_id': user_id,
        'case_number': CASE,
        'status': 'active'
    }
    
    parsed_entry = {
        'case_number': CASE,
        'hearing_date': '22-01-2026',
        'bench': 'Test Bench',
        'judge': 'Justice Test',
        'list_type': 'Regular',
        'item_number': '101'
    }
    
    matches = [(tracked_case, parsed_entry)]
    
    # Run Processing
    print("Running process_matches_and_generate_alerts...")
    alerts = process_matches_and_generate_alerts(matches)
    
    print(f"\nGenerated {len(alerts)} alerts.")

if __name__ == "__main__":
    test_matcher_logging()
