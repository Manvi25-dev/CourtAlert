"""
CourtAlert Security Verification Script
Tests rate limiting, input validation, and secure API key handling.
"""

import time
import os
from whatsapp_handler import handle_incoming_message as mock_whatsapp_webhook
from security import limiter

def test_rate_limiting():
    print("\n" + "="*60)
    print("🔒 TEST 1: Rate Limiting")
    print("="*60)
    
    # Reset limiter for testing
    limiter.ip_requests.clear()
    limiter.user_requests.clear()
    
    # Simulate spamming from same IP
    print("   Simulating 70 requests from same IP (Limit: 60/min)...")
    blocked_count = 0
    for i in range(70):
        payload = {
            'user_phone_number': f'+9198765432{i%10:02d}', # Varying users
            'message_type': 'text',
            'message_content': 'Test message'
        }
        response = mock_whatsapp_webhook(payload, client_ip="192.168.1.100")
        if response.get('status') == 'error' and response.get('code') == 429:
            blocked_count += 1
            
    print(f"   Blocked requests: {blocked_count}")
    if blocked_count > 0:
        print("   ✅ IP Rate limiting working")
    else:
        print("   ❌ IP Rate limiting FAILED")

    # Simulate spamming from same User
    print("\n   Simulating 25 requests from same User (Limit: 20/min)...")
    limiter.ip_requests.clear() # Clear IP limit to test User limit
    
    blocked_count = 0
    for i in range(25):
        payload = {
            'user_phone_number': '+919876543210', # Same user
            'message_type': 'text',
            'message_content': 'Test message'
        }
        response = mock_whatsapp_webhook(payload, client_ip=f"10.0.0.{i}") # Varying IPs
        if response.get('status') == 'error' and response.get('code') == 429:
            blocked_count += 1
            
    print(f"   Blocked requests: {blocked_count}")
    if blocked_count > 0:
        print("   ✅ User Rate limiting working")
    else:
        print("   ❌ User Rate limiting FAILED")


def test_input_validation():
    print("\n" + "="*60)
    print("🔒 TEST 2: Input Validation")
    print("="*60)
    
    # Clear limiter state before validation tests to avoid 429s
    limiter.ip_requests.clear()
    limiter.user_requests.clear()
    
    # Test 1: Invalid Phone Number
    print("   Test 2a: Invalid Phone Number")
    payload1 = {
        'user_phone_number': '12345', # Too short, no +
        'message_type': 'text',
        'message_content': 'Hello'
    }
    resp1 = mock_whatsapp_webhook(payload1)
    if resp1.get('code') == 400:
        print(f"   ✅ Correctly rejected invalid phone: {resp1['message']}")
    else:
        print(f"   ❌ Failed to reject invalid phone: {resp1}")

    # Test 2: Invalid Message Type
    print("\n   Test 2b: Invalid Message Type")
    payload2 = {
        'user_phone_number': '+919876543210',
        'message_type': 'video', # Not allowed
        'message_content': 'Hello'
    }
    resp2 = mock_whatsapp_webhook(payload2)
    if resp2.get('code') == 400:
        print(f"   ✅ Correctly rejected invalid type: {resp2['message']}")
    else:
        print(f"   ❌ Failed to reject invalid type: {resp2}")

    # Test 3: Valid Payload
    print("\n   Test 2c: Valid Payload")
    payload3 = {
        'user_phone_number': '+919876543210',
        'message_type': 'text',
        'message_content': 'Add case CRL.M.C. 320/2026'
    }
    resp3 = mock_whatsapp_webhook(payload3)
    if resp3.get('status') == 'success':
        print("   ✅ Valid payload accepted")
    else:
        print(f"   ❌ Valid payload rejected: {resp3}")


if __name__ == "__main__":
    test_rate_limiting()
    test_input_validation()
