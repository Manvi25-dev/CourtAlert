import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import PyPDF2
except ImportError:  # pragma: no cover - optional in some local setups
    PyPDF2 = None

try:
    import pdfplumber
except ImportError:  # pragma: no cover - optional structured table parsing
    pdfplumber = None

try:
    import pytesseract
    from pdf2image import convert_from_path
except ImportError:  # pragma: no cover - optional OCR fallback
    pytesseract = None
    convert_from_path = None

from case_parser import extract_all_case_numbers

logger = logging.getLogger(__name__)

CAUSE_LIST_URL = "https://delhihighcourt.nic.in/web/cause-lists/cause-list"
GURUGRAM_CAUSE_LIST_URL = "https://highcourtchd.gov.in/3_har/district/gurugram/clc_dist.php"

PDF_DIR = "cause_lists"
os.makedirs(PDF_DIR, exist_ok=True)

HTTP_TIMEOUT_SECONDS = 15
MAX_PARSE_LINES = 50000
MAX_PDF_PAGES = 1200
GURUGRAM_COURT_NAME = "District and Sessions Courts, Gurugram"


class ParseResult:
    """Compatibility return type supporting both tuple-unpack and list-like use."""

    def __init__(self, entries: list[dict], extracted_date: str | None):
        self.entries = entries
        self.extracted_date = extracted_date

    def __iter__(self):
        yield self.entries
        yield self.extracted_date

    def __len__(self):
        return len(self.entries)

    def __bool__(self):
        return bool(self.entries)

    def __getitem__(self, item):
        return self.entries[item]


def fetch_cause_list_pdfs() -> list[str]:
    """Fetch available PDFs from Delhi HC and Gurugram sources."""
    downloaded_files: list[str] = []
    fetch_start = time.perf_counter()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml",
        }
    )

    try:
        logger.info("Fetching PDFs: Delhi High Court source")
        response = session.get(CAUSE_LIST_URL, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if not href.lower().endswith(".pdf"):
                continue

            full_url = href if href.startswith("http") else f"https://delhihighcourt.nic.in{href}"
            filename = full_url.split("/")[-1]
            filepath = os.path.join(PDF_DIR, filename)

            if not os.path.exists(filepath):
                dl = session.get(full_url, timeout=HTTP_TIMEOUT_SECONDS)
                dl.raise_for_status()
                with open(filepath, "wb") as f:
                    f.write(dl.content)
                logger.info("PDF downloaded: %s", filename)

            downloaded_files.append(filepath)
    except Exception as exc:
        logger.error("DHC fetch failed: %s", exc)

    try:
        logger.info("Fetching PDFs: Gurugram source")
        downloaded_files.extend(fetch_gurugram_district_pdfs())
    except Exception as exc:
        logger.error("Gurugram fetch failed: %s", exc)
    logger.info("Fetching PDFs finished in %.2fs (total=%d)", time.perf_counter() - fetch_start, len(downloaded_files))
    return downloaded_files


def fetch_gurugram_district_pdfs(download_dir: str = PDF_DIR, days: int = 3) -> list[str]:
    """Fetch recent Gurugram district cause list PDFs."""
    base_url = GURUGRAM_CAUSE_LIST_URL
    out_dir = Path(download_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[str] = []

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml",
        }
    )

    try:
        session.get(base_url, timeout=HTTP_TIMEOUT_SECONDS).raise_for_status()
        response = session.post(
            base_url,
            data={"t_f_date": "", "submit": "View"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.error("Gurugram request failed: %s", exc)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    date_links: list[str] = []

    for row in soup.find_all("tr")[:MAX_PARSE_LINES]:
        cols = row.find_all("td")
        if not cols:
            continue

        a_tag = cols[0].find("a", href=True)
        if not a_tag:
            continue

        date_text = a_tag.get_text(strip=True)
        if not re.match(r"\d{2}/\d{2}/\d{4}", date_text):
            continue

        href = a_tag["href"]
        if href.lower().startswith("javascript"):
            match = re.search(r"'(.+?\.pdf)'", href)
            if not match:
                continue
            full_url = urljoin(base_url, match.group(1))
        else:
            full_url = urljoin(base_url, href)
        date_links.append(full_url)

    for pdf_url in date_links[:days]:
        try:
            r = session.get(pdf_url, timeout=HTTP_TIMEOUT_SECONDS)
            r.raise_for_status()
            filename = pdf_url.split("/")[-1]
            path = out_dir / filename
            path.write_bytes(r.content)
            saved_files.append(str(path))
            logger.info("PDF downloaded: %s", filename)
        except Exception as exc:
            logger.error("Failed downloading %s: %s", pdf_url, exc)

    return saved_files


def extract_text_from_pdf(filepath: str) -> str:
    """Extract text from PDF and optionally fall back to OCR when available."""
    extract_start = time.perf_counter()
    text = ""

    if PyPDF2 is not None:
        try:
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for idx, page in enumerate(reader.pages):
                    if idx >= MAX_PDF_PAGES:
                        logger.warning("Page limit reached while parsing %s", filepath)
                        break
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
        except Exception as exc:
            logger.error("PyPDF2 failed for %s: %s", filepath, exc)

    if len(text.strip()) < 100 and convert_from_path and pytesseract:
        try:
            try:
                images = convert_from_path(filepath, timeout=HTTP_TIMEOUT_SECONDS)
            except TypeError:
                images = convert_from_path(filepath)
            for idx, img in enumerate(images):
                if idx >= MAX_PDF_PAGES:
                    logger.warning("OCR image limit reached while parsing %s", filepath)
                    break
                text += pytesseract.image_to_string(img) + "\n"
        except Exception as exc:
            logger.error("OCR failed for %s: %s", filepath, exc)

    logger.info("Parsing PDF completed: %s in %.2fs", filepath, time.perf_counter() - extract_start)
    return text


def _extract_advance_date(text: str) -> str | None:
    header_text = text[:2000].upper()
    if not re.search(r"ADVANCE\s+CAUSE\s+LIST", header_text):
        return None

    date_match = re.search(r"(\d{2}[\.-]\d{2}[\.-]\d{4})", header_text)
    if not date_match:
        return None

    normalized = date_match.group(1).replace("-", ".")
    try:
        return datetime.strptime(normalized, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def _extract_gurugram_date(text: str) -> str | None:
    match = re.search(
        r"CAUSE\s+LIST\s+DATED\s*:\s*(\d{1,2}\s+[A-Za-z]+\s*,\s*\d{4})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    try:
        return datetime.strptime(match.group(1), "%d %B, %Y").date().isoformat()
    except ValueError:
        return None


def _normalize_case_number(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b([A-Z.]+)[\s/\-]+(\d+)[\s/\-]+(\d{4})\b", value.upper())
    if not match:
        return None
    case_type, number, year = match.groups()
    case_type = re.sub(r"[^A-Z0-9]", "", case_type)
    return f"{case_type}/{int(number)}/{year}"


def _clean_title_and_advocate(
    title: str | None,
    advocate: str | None,
    case_number: str,
) -> tuple[str, str]:
    title_text = re.sub(r"\s+", " ", (title or "").strip())
    advocate_text = re.sub(r"\s+", " ", (advocate or "").strip())

    title_text = re.sub(r"\bADD\s+CASE\b", "", title_text, flags=re.IGNORECASE).strip()
    title_text = re.sub(re.escape(case_number), "", title_text, flags=re.IGNORECASE).strip()
    title_text = re.sub(r"^\d+\s*", "", title_text).strip()

    advocate_text = re.sub(r"^\d+\s*", "", advocate_text).strip()

    return title_text or "Unknown Title", advocate_text or "Unknown Advocate"


def parse_cause_list_pdf(filepath: str) -> ParseResult:
    """Parse cause list PDF with table extraction first, then fallback to text parser."""
    if pdfplumber is None:
        logger.warning("pdfplumber unavailable. Falling back to text parser for %s", filepath)
        text = extract_text_from_pdf(filepath)
        return parse_cause_list_entries(text)

    entries: list[dict] = []
    extracted_date: str | None = None
    start = time.perf_counter()

    try:
        with pdfplumber.open(filepath) as pdf:
            for page_index, page in enumerate(pdf.pages):
                if page_index >= MAX_PDF_PAGES:
                    logger.warning("Page limit reached while table parsing %s", filepath)
                    break

                page_text = page.extract_text() or ""
                if not extracted_date:
                    extracted_date = _extract_gurugram_date(page_text) or _extract_advance_date(page_text)

                tables = page.extract_tables() or []
                for table in tables:
                    for row in table[:MAX_PARSE_LINES]:
                        if not row:
                            continue

                        cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in row]
                        if len(cells) < 5:
                            cells = cells + [""] * (5 - len(cells))

                        sr_no, case_cell, _doi, title_cell, advocate_cell = cells[:5]
                        if not case_cell:
                            continue

                        header_key = f"{sr_no} {case_cell} {title_cell}".upper()
                        if "CASE TYPE" in header_key or "SR NO" in header_key:
                            continue

                        case_number = _normalize_case_number(case_cell)
                        if not case_number:
                            continue

                        title, advocate = _clean_title_and_advocate(title_cell, advocate_cell, case_number)
                        item_no = re.sub(r"\D", "", sr_no or "") or "Unknown"

                        entries.append(
                            {
                                "case_no": case_number,
                                "case_number": case_number,
                                "title": title,
                                "advocate": advocate,
                                "court": GURUGRAM_COURT_NAME,
                                "hearing_date": extracted_date,
                                "item": item_no,
                                "raw": title,
                            }
                        )
    except Exception as exc:
        logger.error("Structured PDF parse failed for %s: %s", filepath, exc)

    # Fallback for non-tabular PDFs or failed extraction.
    if not entries:
        text = extract_text_from_pdf(filepath)
        fallback_entries, fallback_date = parse_cause_list_entries(text)
        extracted_date = extracted_date or fallback_date
        entries = list(fallback_entries)

    logger.info(
        "Structured PDF parse completed: %s entries=%d date=%s in %.2fs",
        filepath,
        len(entries),
        extracted_date,
        time.perf_counter() - start,
    )
    return ParseResult(entries, extracted_date)


def parse_cause_list_entries(text: str) -> ParseResult:
    """Parse raw cause list text into entry dicts and extracted doc date."""
    parse_start = time.perf_counter()
    entries: list[dict] = []
    extracted_date = _extract_advance_date(text) or _extract_gurugram_date(text)

    lines = text.splitlines()
    current_court_parts: list[str] = []

    for raw_line in lines[:MAX_PARSE_LINES]:
        line = raw_line.strip()
        if not line:
            continue

        upper = line.upper()
        if "COURT NO" in upper:
            current_court_parts = [line]
            continue

        if "HON'BLE" in upper:
            if current_court_parts:
                current_court_parts.append(line)
            else:
                current_court_parts = [line]
            continue

        cases = extract_all_case_numbers(line)
        if not cases:
            continue

        court_label = " | ".join(current_court_parts) if current_court_parts else "Unknown Court"
        item_match = re.match(r"^(\d+)\.", line)
        item_no = item_match.group(1) if item_match else "Unknown"

        for case in cases:
            normalized_case = _normalize_case_number(case)
            logger.info("PARSE NORMALIZATION: raw_case=%s normalized_case=%s", case, normalized_case)
            entries.append(
                {
                    "case_no": case,
                    "court": court_label,
                    "item": item_no,
                    "raw": line,
                }
            )

    parsed_preview = []
    for entry in entries[:20]:
        candidate = entry.get("case_no") or entry.get("case_number")
        canonical = _normalize_case_number(candidate)
        if canonical:
            parsed_preview.append(canonical)
    logger.info("Parsed cases (first 20): %s", ", ".join(parsed_preview) if parsed_preview else "none")

    logger.info(
        "Entries extracted: count=%d, date=%s, parse_time=%.2fs",
        len(entries),
        extracted_date,
        time.perf_counter() - parse_start,
    )
    return ParseResult(entries, extracted_date)


def parse_case_entries(text: str, list_type: str, hearing_date: str) -> list[dict]:
    """Legacy parser helper retained for older tests/scripts."""
    extracted_cases = extract_all_case_numbers(text)
    parsed: list[dict] = []
    for idx, case_number in enumerate(extracted_cases):
        parsed.append(
            {
                "case_number": case_number,
                "original_case_number": case_number,
                "hearing_date": hearing_date,
                "list_type": list_type,
                "item_number": str(idx + 1),
                "match_type": "PRIMARY_LISTING" if idx == 0 else "SECONDARY_REFERENCE",
                "bench": "Unknown Bench",
                "judge": "Unknown Judge",
            }
        )
    return parsed


def fetch_and_parse_cause_lists() -> list[dict]:
    """Fetch all PDFs and return normalized pipeline entries."""
    parsed_entries: list[dict] = []
    for pdf_path in fetch_cause_list_pdfs():
        entries, extracted_date = parse_cause_list_pdf(pdf_path)
        for idx, entry in enumerate(entries):
            parsed_entries.append(
                {
                    "case_number": entry.get("case_number") or entry["case_no"],
                    "original_case_number": entry.get("case_number") or entry["case_no"],
                    "hearing_date": entry.get("hearing_date") or extracted_date,
                    "bench": entry.get("court"),
                    "judge": entry.get("court"),
                    "list_type": "Unknown",
                    "item_number": entry.get("item", str(idx + 1)),
                    "match_type": "PRIMARY_LISTING",
                    "raw": entry.get("raw", ""),
                    "title": entry.get("title"),
                    "advocate": entry.get("advocate"),
                    "court": entry.get("court"),
                }
            )
    return parsed_entries


def get_sample_cause_list_entries() -> list[dict]:
    """Static sample entries used by workflow demos/tests."""
    return [
        {
            "case_number": "CRL.M.C. 320/2026",
            "original_case_number": "CRL.M.C. 320/2026",
            "hearing_date": "2026-01-22",
            "bench": "Court No. 01",
            "judge": "Hon'ble Chief Justice",
            "list_type": "Regular",
            "item_number": "1",
            "match_type": "PRIMARY_LISTING",
        },
        {
            "case_number": "CS 1234/2026",
            "original_case_number": "CS 1234/2026",
            "hearing_date": "2026-01-22",
            "bench": "Court No. 05",
            "judge": "Hon'ble Mr. Justice Sample",
            "list_type": "Regular",
            "item_number": "2",
            "match_type": "PRIMARY_LISTING",
        },
    ]
