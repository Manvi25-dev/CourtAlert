import os
import re
import requests
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup


GURUGRAM_CAUSE_LIST_URL = (
    "https://highcourtchd.gov.in/3_har/district/gurugram/clc_dist.php"
)


def fetch_gurugram_district_pdfs(
    download_dir: str | Path = "downloads/gurugram",
    base_url: str = GURUGRAM_CAUSE_LIST_URL,
    days: int = 3,
    timeout: int = 30,
) -> list[str]:
    """
    Fetch Gurugram District Court cause list PDFs.

    Flow:
    1. Fetch landing page
    2. Extract date links from table
    3. Download latest N PDFs
    """

    out_dir = Path(download_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        response = requests.get(base_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Failed to fetch landing page: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    # Match dates like 23/02/2026
    date_pattern = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")

    pdf_links = []

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]

        if date_pattern.search(text):
            full_url = urljoin(base_url, href)
            pdf_links.append(full_url)

    if not pdf_links:
        print("No date links found.")
        return []

    # Only latest N
    pdf_links = pdf_links[:days]

    saved_files = []

    for pdf_url in pdf_links:
        try:
            pdf_response = requests.get(pdf_url, timeout=timeout)
            pdf_response.raise_for_status()
        except requests.RequestException as e:
            print(f"Failed to download {pdf_url}: {e}")
            continue

        filename = pdf_url.split("/")[-1]
        filepath = out_dir / filename

        filepath.write_bytes(pdf_response.content)
        saved_files.append(str(filepath))

    return saved_files
