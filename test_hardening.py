from case_parser import normalize_case_id
from security import validate_canonical_case_id, sanitize_case_number

print("=== 1. Normalization & Validation Tests ===")
test_cases = [
    ("CRL.M.C. 8148/2025", "CRLMC-8148-2025", True),
    ("CRL M C 8148 / 2025", "CRLMC-8148-2025", True),
    ("CRLMC-8148-2025", "CRLMC-8148-2025", True),
    ("Invalid Case", None, False),
    ("CRL.M.C. 8148", None, False), # Missing year
    ("8148/2025", None, False), # Missing type
]

for input_str, expected_norm, expected_valid in test_cases:
    norm = normalize_case_id(input_str)
    is_valid = validate_canonical_case_id(norm)
    
    status = "✅" if (norm == expected_norm and is_valid == expected_valid) else "❌"
    print(f"{status} Input: '{input_str}' -> Norm: '{norm}' -> Valid: {is_valid}")

print("\n=== 2. Sanitization Tests ===")
sanitization_cases = [
    ("CRL.M.C. 8148/2025", "CRL.M.C. 8148/2025"),
    ("CRL.M.C. 8148/2025; DROP TABLE", "CRL.M.C. 8148/2025 DROP TABLE"), # Sanitizer allows alphanumeric/spaces, but we want to see what it does
    # Wait, sanitize_case_number allows alphanumeric, dots, slashes, hyphens, spaces.
    # It removes others.
    ("CRL.M.C. 8148/2025 <script>", "CRL.M.C. 8148/2025 script"),
]

for input_str, expected_sanitized in sanitization_cases:
    sanitized = sanitize_case_number(input_str)
    print(f"Input: '{input_str}' -> Sanitized: '{sanitized}'")

print("\n=== 3. Strict Matching Verification ===")
# We verify that matching relies on normalization
tracked = "CRL.M.C. 8148/2025"
parsed = "CRL M C 8148 / 2025"

norm_tracked = normalize_case_id(tracked)
norm_parsed = normalize_case_id(parsed)

if norm_tracked and norm_parsed and norm_tracked == norm_parsed:
    print(f"✅ Strict Match Success: {norm_tracked} == {norm_parsed}")
else:
    print(f"❌ Strict Match Failed: {norm_tracked} != {norm_parsed}")
