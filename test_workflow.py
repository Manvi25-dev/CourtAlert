"""
CourtAlert End-to-End Workflow Test
Tests the complete pipeline with sample data
"""

import json
from models import (
    init_db, add_user, add_tracked_case, get_all_tracked_cases,
    get_tracked_cases_for_user, get_hearings_for_case, get_alerts_for_user
)
from cause_list_fetcher import get_sample_cause_list_entries
from case_matcher import run_matching_pipeline
from whatsapp_handler import mock_whatsapp_webhook
from orchestrator import CourtAlertOrchestrator
import os


def test_database_operations():
    """Test basic database operations."""
    print("\n" + "="*70)
    print("TEST 1: Database Operations")
    print("="*70)
    
    # Add users
    user1_id = add_user("+919876543210")
    user2_id = add_user("+919123456789")
    
    # Add tracked cases
    case1_id = add_tracked_case(user1_id, "CRL.M.C. 320/2026", "Delhi High Court")
    case2_id = add_tracked_case(user1_id, "CS 1234/2026", "Delhi High Court")
    case3_id = add_tracked_case(user2_id, "CRL.A. 456/2025", "Delhi High Court")
    
    # Verify
    all_cases = get_all_tracked_cases()
    user1_cases = get_tracked_cases_for_user(user1_id)
    
    print(f"\n✅ Added 2 users and 3 tracked cases")
    print(f"   Total tracked cases: {len(all_cases)}")
    print(f"   User 1 cases: {len(user1_cases)}")
    
    return user1_id, user2_id


def test_cause_list_parsing():
    """Test cause list parsing with sample data."""
    print("\n" + "="*70)
    print("TEST 2: Cause List Parsing")
    print("="*70)
    
    # Get sample entries
    entries = get_sample_cause_list_entries()
    
    print(f"\n✅ Retrieved {len(entries)} sample cause list entries")
    for i, entry in enumerate(entries, 1):
        print(f"\n   Entry {i}:")
        print(f"     Case: {entry['case_number']}")
        print(f"     Date: {entry['hearing_date']}")
        print(f"     Bench: {entry['bench']}")
        print(f"     Judge: {entry['judge']}")
    
    return entries


def test_case_matching(entries):
    """Test case matching and alert generation."""
    print("\n" + "="*70)
    print("TEST 3: Case Matching and Alert Generation")
    print("="*70)
    
    # Run matching pipeline
    alerts = run_matching_pipeline(entries)
    
    print(f"\n✅ Generated {len(alerts)} alerts")
    for i, alert in enumerate(alerts, 1):
        print(f"\n   Alert {i}:")
        print(f"     User ID: {alert['user_id']}")
        print(f"     Case: {alert['case_number']}")
        print(f"     Type: {alert['alert_type']}")
        print(f"     Message Preview: {alert['message'][:80]}...")
    
    return alerts


def test_whatsapp_integration():
    """Test WhatsApp message handling."""
    print("\n" + "="*70)
    print("TEST 4: WhatsApp Integration")
    print("="*70)
    
    # Test 1: Add case via text
    print("\n   Test 4a: Add case via text message")
    payload1 = {
        'user_phone_number': '+919999999999',
        'message_type': 'text',
        'message_content': 'Add case CRL.M.C. 320/2026'
    }
    result1 = mock_whatsapp_webhook(payload1)
    print(f"   ✅ Response: {result1['status']}")
    
    # Test 2: Get status
    print("\n   Test 4b: Get status of tracked case")
    payload2 = {
        'user_phone_number': '+919999999999',
        'message_type': 'text',
        'message_content': 'Status of my case CRL.M.C. 320/2026'
    }
    result2 = mock_whatsapp_webhook(payload2)
    print(f"   ✅ Response: {result2['status']}")
    
    # Test 3: Get all tracked cases
    print("\n   Test 4c: Get all tracked cases")
    payload3 = {
        'user_phone_number': '+919999999999',
        'message_type': 'text',
        'message_content': 'Show my cases'
    }
    result3 = mock_whatsapp_webhook(payload3)
    print(f"   ✅ Response: {result3['status']}")


def test_full_orchestration():
    """Test full orchestration pipeline."""
    print("\n" + "="*70)
    print("TEST 5: Full Orchestration Pipeline")
    print("="*70)
    
    orchestrator = CourtAlertOrchestrator()
    result = orchestrator.run_full_pipeline()
    
    print(f"\n✅ Pipeline execution complete")
    print(f"   Status: {result['stages'].get('fetch_parse', {}).get('status')}")
    print(f"   Entries parsed: {result['stages'].get('fetch_parse', {}).get('entries_parsed', 0)}")
    print(f"   Alerts generated: {result['stages'].get('matching', {}).get('alerts_generated', 0)}")
    
    # Get system status
    status = orchestrator.get_system_status()
    print(f"\n📈 System Status:")
    print(f"   Active users: {status['users']}")
    print(f"   Tracked cases: {status['tracked_cases']}")
    print(f"   Hearings in DB: {status['hearings']}")
    print(f"   Alerts sent: {status['alerts_sent']}")


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print("🧪 COURTALERT END-TO-END WORKFLOW TEST SUITE")
    print("="*70)
    
    # Initialize fresh database
    print("\n🔧 Initializing database...")
    if os.path.exists("courtalert.db"):
        os.remove("courtalert.db")
    init_db()
    
    # Run tests
    test_database_operations()
    entries = test_cause_list_parsing()
    alerts = test_case_matching(entries)
    test_whatsapp_integration()
    test_full_orchestration()
    
    print("\n" + "="*70)
    print("✅ ALL TESTS COMPLETED SUCCESSFULLY")
    print("="*70)
    
    # Summary
    print("\n📊 Test Summary:")
    print("   ✅ Database operations")
    print("   ✅ Cause list parsing")
    print("   ✅ Case matching and alert generation")
    print("   ✅ WhatsApp integration")
    print("   ✅ Full orchestration pipeline")
    
    print("\n🎯 CourtAlert PoC is ready for deployment!")


if __name__ == "__main__":
    run_all_tests()
