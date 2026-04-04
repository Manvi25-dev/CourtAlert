from case_parser import normalize_case_id
from case_matcher import match_case_number

cases = [
    "CRL.M.C. 8148/2025",
    "CRL M C 8148 / 2025",
    "CRLMC 8148-2025",
    "W.P.(C) 1234/2025",
    "CS(COMM) 567/2024",
    "FAO(OS) 89/2023",
    "CRL.A. 12/2022",
    "CM(M) 45/2021",
    "CRL.M.C. 8148/2025" # Duplicate to check consistency
]

print("=== Normalization Tests ===")
for c in cases:
    print(f"'{c}' -> '{normalize_case_id(c)}'")

print("\n=== Matching Tests ===")
tracked = "CRL.M.C. 8148/2025"
parsed_variants = [
    "CRL.M.C. 8148/2025",
    "CRL M C 8148 / 2025",
    "CRLMC 8148-2025",
    "CRLMC8148/2025", # This one might fail if it doesn't have separators? No, regex handles it?
    "CRLMC-8148-2025"
]

print(f"Tracked: '{tracked}' -> '{normalize_case_id(tracked)}'")
for parsed in parsed_variants:
    match = match_case_number(tracked, parsed)
    result = "✅ MATCH" if match else "❌ NO MATCH"
    print(f"vs '{parsed}' -> '{normalize_case_id(parsed)}': {result}")
