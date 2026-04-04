from case_matcher import match_case_number

tracked = "CRL.M.C. 8148/2025"
parsed_variants = [
    "CRL.M.C. 8148/2025",
    "CRL. M. C. 8148 / 2025",
    "CRLMC 8148-2025",
    "CRLMC8148/2025"
]

print(f"Testing matching for tracked case: '{tracked}'")
for parsed in parsed_variants:
    match = match_case_number(tracked, parsed)
    result = "✅ MATCH" if match else "❌ NO MATCH"
    print(f"  vs '{parsed}': {result}")
