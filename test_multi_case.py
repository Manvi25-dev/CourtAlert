from case_parser import extract_all_case_numbers, normalize_case_id
from cause_list_fetcher import parse_case_entries

# Test 1: Extraction Logic
print("=== 1. Extraction Logic Test ===")
text = "1. CRL.M.C. 8148/2025 Other Case Filed Against Same FIR No. W.P.(C) 1234/2026"
extracted = extract_all_case_numbers(text)
print(f"Input: '{text}'")
print(f"Extracted: {extracted}")

expected = ["CRL.M.C. 8148/2025", "W.P.(C) 1234/2026"]
if extracted == expected:
    print("✅ Extraction Success")
else:
    print(f"❌ Extraction Failed. Expected {expected}")

# Test 2: Parsing & Tagging Logic
print("\n=== 2. Parsing & Tagging Test ===")
# Mock parse_case_entries behavior (since it depends on imports inside the function)
# We'll just run the function with the text.
entries = parse_case_entries(text, "Regular", "21/01/2026")

for entry in entries:
    print(f"Case: {entry['case_number']} | Type: {entry['match_type']} | Original: {entry['original_case_number']}")

if len(entries) == 2:
    if entries[0]['match_type'] == 'PRIMARY_LISTING' and entries[1]['match_type'] == 'SECONDARY_REFERENCE':
        print("✅ Tagging Success")
    else:
        print("❌ Tagging Failed (Wrong types)")
else:
    print(f"❌ Tagging Failed (Wrong count: {len(entries)})")

# Test 3: Normalization Check
print("\n=== 3. Normalization Check ===")
norm1 = normalize_case_id(entries[0]['original_case_number'])
norm2 = normalize_case_id(entries[1]['original_case_number'])
print(f"Norm 1: {norm1}")
print(f"Norm 2: {norm2}")

if norm1 == "CRLMC-8148-2025" and norm2 == "WPC-1234-2026":
    print("✅ Normalization Success")
else:
    print("❌ Normalization Failed")
