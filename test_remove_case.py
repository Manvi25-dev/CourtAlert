"""
Test script for Remove Case functionality
"""
import json
from whatsapp_handler import mock_whatsapp_webhook, handle_incoming_message

def test_remove_case():
    phone = "+919999988888"
    case_num = "CRL.M.C. 999/2026"
    
    print("--- Step 1: Add Case ---")
    payload_add = {
        'user_phone_number': phone,
        'message_type': 'text',
        'message_content': f'Add case {case_num}'
    }
    # We use handle_incoming_message directly to simulate the webhook logic
    # mock_whatsapp_webhook is likely a wrapper or alias, let's check imports
    # Actually whatsapp_handler.py has handle_incoming_message as the main entry point
    
    # Note: In the file content I read earlier, I didn't see mock_whatsapp_webhook defined, 
    # but I saw handle_incoming_message. Let's use handle_incoming_message.
    
    resp_add = handle_incoming_message(payload_add)
    print(f"Add Response: {resp_add['response']['message_text']}")
    
    print("\n--- Step 2: Remove Case ---")
    payload_remove = {
        'user_phone_number': phone,
        'message_type': 'text',
        'message_content': f'Remove case {case_num}'
    }
    resp_remove = handle_incoming_message(payload_remove)
    print(f"Remove Response: {resp_remove['response']['message_text']}")
    
    print("\n--- Step 3: Remove Case Again (Should fail) ---")
    resp_remove_again = handle_incoming_message(payload_remove)
    print(f"Remove Again Response: {resp_remove_again['response']['message_text']}")

if __name__ == "__main__":
    test_remove_case()
