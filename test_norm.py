from case_parser import normalize_case_id

cases = [
    "CRL.M.C. 8148/2025",
    "CRL M C 8148 / 2025",
    "CRLMC 8148-2025",
    "W.P.(C) 1234/2025",
    "CS(COMM) 567/2024",
    "FAO(OS) 89/2023",
    "CRL.A. 12/2022",
    "CM(M) 45/2021"
]

for c in cases:
    print(f"'{c}' -> '{normalize_case_id(c)}'")
