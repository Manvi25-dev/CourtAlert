from case_parser import parse_case_number, normalize_case_id

inputs = [
    "CRL.M.C. 8148/2025",
    "Add case CRL.M.C. 8148/2025",
    "CRL.M.C. 8148 / 2025",
    "CRL.M.C. 8148" # Missing year input?
]

print("=== Parsing Debug ===")
for i in inputs:
    parsed = parse_case_number(i)
    print(f"Input: '{i}' -> Parsed: '{parsed}'")
    if parsed:
        norm = normalize_case_id(parsed)
        print(f"  Normalized: '{norm}'")
    else:
        # Try normalizing raw input directly (if parser fails but we want to test norm)
        norm = normalize_case_id(i)
        print(f"  Raw Normalized: '{norm}'")
