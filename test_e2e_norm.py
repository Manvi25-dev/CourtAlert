from case_parser import normalize_case_id
from case_matcher import match_case_number

# 1. User Input Simulation
user_input = "CRL.M.C. 8148/2025"
norm_user = normalize_case_id(user_input)
print(f"User Input: '{user_input}' -> Normalized: '{norm_user}'")

# 2. PDF Parsing Simulation
pdf_entry = "CRL.M.C. 8148/2025"
norm_pdf = normalize_case_id(pdf_entry)
print(f"PDF Entry: '{pdf_entry}' -> Normalized: '{norm_pdf}'")

# 3. Matching
match = match_case_number(user_input, pdf_entry)
print(f"Match Result: {'✅ MATCH' if match else '❌ NO MATCH'}")

# 4. Test with variations
variants = [
    "CRL M C 8148 / 2025",
    "CRLMC 8148-2025",
    "CRLMC8148/2025"
]

print("\n=== Variation Tests ===")
for v in variants:
    norm_v = normalize_case_id(v)
    match_v = match_case_number(user_input, v)
    print(f"Variant: '{v}' -> Normalized: '{norm_v}' -> Match: {'✅' if match_v else '❌'}")
