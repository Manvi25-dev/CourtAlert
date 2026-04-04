import os
from cause_list_fetcher import extract_text_from_pdf
import re
from datetime import datetime

PDF_DIR = "cause_lists"
filename = "combined_adv_list_23.01.2026.pdf"
filepath = os.path.join(PDF_DIR, filename)

if os.path.exists(filepath):
    print(f"Extracting text from {filepath}...")
    text = extract_text_from_pdf(filepath)
    header_text = text[:1000].upper()
    print("-" * 20)
    print("HEADER TEXT (First 1000 chars):")
    print(header_text)
    print("-" * 20)
    
    # Test regex directly
    if re.search(r"ADVANCE\s+CAUSE\s+LIST", header_text):
        print("FOUND 'ADVANCE CAUSE LIST' (with regex)")
        date_match = re.search(r'(\d{2}[\.-]\d{2}[\.-]\d{4})', header_text)
        if date_match:
            raw_date = date_match.group(1)
            print(f"MATCHED DATE: {raw_date}")
            try:
                normalized_date = raw_date.replace('-', '.')
                dt_obj = datetime.strptime(normalized_date, "%d.%m.%Y")
                extracted_date = dt_obj.date().isoformat()
                print(f"PARSED DATE: {extracted_date}")
            except ValueError as e:
                print(f"DATE PARSE ERROR: {e}")
        else:
            print("NO DATE MATCHED")
    else:
        print("'ADVANCE CAUSE LIST' NOT FOUND IN HEADER")
else:
    print(f"File {filepath} not found.")
