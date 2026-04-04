import requests
import json

URL = "http://localhost:8000/webhook"

def test_json():
    print("Testing JSON Payload...")
    payload = {
        "user_phone_number": "+919999999999",
        "message_type": "text",
        "message_content": "Status"
    }
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(URL, json=payload, headers=headers)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")
        if resp.status_code == 200:
            print("✅ JSON Test Passed")
        else:
            print("❌ JSON Test Failed")
    except Exception as e:
        print(f"❌ Error: {e}")

def test_text():
    print("\nTesting Plain Text Payload...")
    text = "Add case CRL.M.C. 1234/2026"
    headers = {"Content-Type": "text/plain"}
    try:
        resp = requests.post(URL, data=text, headers=headers)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")
        if resp.status_code == 200:
            print("✅ Text Test Passed")
        else:
            print("❌ Text Test Failed")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_json()
    test_text()
