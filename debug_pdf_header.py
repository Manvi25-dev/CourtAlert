import os
from cause_list_fetcher import extract_text_from_pdf

PDF_DIR = "cause_lists"
filename = "combined_adv_list_23.01.2026.pdf"
filepath = os.path.join(PDF_DIR, filename)

if os.path.exists(filepath):
    print(f"Extracting text from {filepath}...")
    text = extract_text_from_pdf(filepath)
    header = text[:1000]
    print("-" * 20)
    print("HEADER TEXT (First 1000 chars):")
    print(header)
    print("-" * 20)
    
    # Test regex directly
    import re
    if "ADVANCE CAUSE LIST" in header.upper():
        print("FOUND 'ADVANCE CAUSE LIST'")
        date_match = re.search(r'(\d{2}[\.-]\d{2}[\.-]\d{4})', header)
        if date_match:
            print(f"MATCHED DATE: {date_match.group(1)}")
        else:
            print("NO DATE MATCHED")
    else:
        print("'ADVANCE CAUSE LIST' NOT FOUND IN HEADER")
else:
    print(f"File {filepath} not found.")
