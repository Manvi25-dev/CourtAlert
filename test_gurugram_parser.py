from cause_list_fetcher import fetch_gurugram_district_pdfs, extract_text_from_pdf, parse_cause_list_entries

print("Testing Gurugram PDF parser...")

files = fetch_gurugram_district_pdfs()

for file in files:
    print(f"Processing {file}")

    text = extract_text_from_pdf(file)
    entries, _ = parse_cause_list_entries(text)

    print(f"Entries found: {len(entries)}")

    if entries:
        print("Sample cases:")
        for e in entries[:5]:
            print(e["case_no"])
