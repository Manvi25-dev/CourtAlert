import logging
from cause_list_fetcher import parse_cause_list_entries, extract_text_from_pdf
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_advance_list_date_extraction():
    pdf_path = "cause_lists/combined_adv_list_23.01.2026.pdf"
    if not os.path.exists(pdf_path):
        print(f"Error: {pdf_path} not found")
        return

    print(f"Testing extraction from {pdf_path}...")
    text = extract_text_from_pdf(pdf_path)
    
    entries, doc_date = parse_cause_list_entries(text)
    
    print("-" * 30)
    print(f"Extracted Date: {doc_date}")
    print(f"Total Entries: {len(entries)}")
    print("-" * 30)
    
    if doc_date == "2026-01-23":
        print("SUCCESS: Date correctly extracted as 2026-01-23")
    else:
        print(f"FAILURE: Expected 2026-01-23, got {doc_date}")

if __name__ == "__main__":
    test_advance_list_date_extraction()
