from models import add_user, add_tracked_case, remove_tracked_case
from ingestion_service import run_cause_list_check

PHONE = "+919999999999"
CASE = "CMAPPL. 2757/2026"  # Known case from cache

def test_alert_logging():
    print("🧪 Testing Alert Logging...")
    
    # Setup: Ensure user exists and case is tracked
    user_id = add_user(PHONE)
    
    # Remove first to ensure clean state (and avoid duplicate alert check skipping it if I ran this before)
    # Actually, duplicate alert check is based on hearing_id. If hearing exists, it returns ID.
    # If alert exists for that hearing_id, it skips.
    # So I need to clear the alert for this case/hearing if it exists?
    # Or just use a new user?
    # Let's use a new user phone to be safe.
    NEW_PHONE = "+918888888888"
    user_id = add_user(NEW_PHONE)
    add_tracked_case(user_id, CASE)
    
    print(f"Added case {CASE} for user {NEW_PHONE}")
    
    # Run Ingestion
    print("Running ingestion service...")
    alerts = run_cause_list_check()
    
    print(f"\nGenerated {len(alerts)} alerts.")
    
    # Verify output manually in logs

if __name__ == "__main__":
    test_alert_logging()
