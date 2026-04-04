from cause_list_fetcher import fetch_cause_list_pdfs, extract_text_from_pdf, parse_cause_list_entries
import logging
import os

logging.basicConfig(level=logging.INFO)

files = fetch_cause_list_pdfs()
print("Downloaded files:")
for f in files:
    if "adv" in f.lower():
        print(f"Processing Advance List: {f}")
        text = extract_text_from_pdf(f)
        entries = parse_cause_list_entries(text)
        print(f"Found {len(entries)} entries.")
        if entries:
            print("Sample cases:")
            for e in entries[:5]:
                print(e['case_no'])
        break

