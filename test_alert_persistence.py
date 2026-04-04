from models import init_db, add_user, add_tracked_case, get_connection
from case_matcher import process_matches_and_generate_alerts

def test_persistence():
    init_db()
    
    # Setup data
    user_id = add_user("8888888888")
    case_number = "CRLMC-9999-2026"
    add_tracked_case(user_id, case_number)
    
    # Mock tracked case object
    tracked_case = {
        'id': 1, # Dummy ID
        'user_id': user_id,
        'case_number': case_number
    }
    
    # Mock parsed entry
    parsed_entry = {
        'case_number': case_number,
        'hearing_date': '25/01/2026',
        'bench': 'Test Bench',
        'judge': 'Test Judge',
        'list_type': 'Regular',
        'item_number': '10',
        'match_type': 'PRIMARY_LISTING'
    }
    
    matches = [(tracked_case, parsed_entry)]
    
    print("\nRunning alert generation...")
    process_matches_and_generate_alerts(matches)
    
    # Verify DB
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM alerts WHERE case_number = ?", (case_number,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print("\n✅ Alert persistence verified!")
        print(dict(row))
    else:
        print("\n❌ Alert persistence FAILED!")

if __name__ == "__main__":
    test_persistence()
