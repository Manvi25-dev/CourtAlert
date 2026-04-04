import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except Exception:  # pragma: no cover - optional dependency failures at runtime
    pdfplumber = None

try:
    import fitz  # type: ignore[import-not-found]  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    from rapidfuzz import fuzz  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    fuzz = None


LOGGER = logging.getLogger("cause_list_pipeline")

DEFAULT_TIMEOUT_SECONDS = 20
PDF_EXTENSIONS = (".pdf",)

CASE_REGEX = re.compile(
    r"\b(?:[A-Z]{1,6}[\./\(\)\-\s]*){1,4}\s*\d{1,6}\s*/\s*\d{4}\b",
    re.IGNORECASE,
)

ITEM_REGEX = re.compile(r"\b(?:ITEM\s*NO\.?|ITEM)\s*[:\-]?\s*(\d{1,4})\b", re.IGNORECASE)
COURT_REGEX = re.compile(r"\b(?:COURT\s*NO\.?|COURT\s*ROOM)\s*[:\-]?\s*(\d{1,3})\b", re.IGNORECASE)

HEADER_FOOTER_PATTERNS = [
    re.compile(r"^\s*DELHI\s+HIGH\s+COURT.*$", re.IGNORECASE),
    re.compile(r"^\s*CAUSE\s+LIST.*$", re.IGNORECASE),
    re.compile(r"^\s*PAGE\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*DATE\s*[:\-].*$", re.IGNORECASE),
]

VS_PATTERN = re.compile(r"\b(vs\.?|v\.?|versus)\b", re.IGNORECASE)
NON_ALNUM_SPACE = re.compile(r"[^a-z0-9\s]")
MULTISPACE = re.compile(r"\s+")


@dataclass
class CauseListEntry:
    case_number: str
    party_names: str
    court_number: str
    item_number: str
    source_url: Optional[str] = None


@dataclass
class MatchResult:
    tracked_case_id: str
    confidence: str
    confidence_score: int
    reason: str
    entry: Dict[str, Any]


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _is_pdf_url(url: str) -> bool:
    return url.lower().endswith(PDF_EXTENSIONS)


def _safe_get(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> requests.Response:
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "CourtAlert/1.0 (+cause-list-ingestion)"},
        )
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        LOGGER.warning("Fetch failed for url=%s error=%s", url, exc)
        raise


def fetch_cause_list(base_url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """
    Detect and fetch cause list payload from a URL.

    Returns:
      {
        "type": "html" | "pdf",
        "source_url": str,
        "html": str | None,
        "pdf_links": list[str],
        "pdf_bytes": bytes | None,
      }
    """
    response = _safe_get(base_url, timeout=timeout)
    content_type = (response.headers.get("Content-Type") or "").lower()

    if _is_pdf_url(base_url) or "application/pdf" in content_type:
        LOGGER.info("Detected PDF source: %s", base_url)
        return {
            "type": "pdf",
            "source_url": base_url,
            "html": None,
            "pdf_links": [base_url],
            "pdf_bytes": response.content,
        }

    html = response.text or ""
    if not html.strip():
        LOGGER.warning("Empty HTML response for url=%s", base_url)
        return {
            "type": "html",
            "source_url": base_url,
            "html": "",
            "pdf_links": [],
            "pdf_bytes": None,
        }

    soup = BeautifulSoup(html, "html.parser")
    pdf_links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if _is_pdf_url(full_url):
            pdf_links.append(full_url)

    deduped_links = sorted(set(pdf_links))
    LOGGER.info(
        "Detected HTML source: %s pdf_links=%d",
        base_url,
        len(deduped_links),
    )
    return {
        "type": "html",
        "source_url": base_url,
        "html": html,
        "pdf_links": deduped_links,
        "pdf_bytes": None,
    }


def _cleanup_lines(raw_text: str) -> List[str]:
    cleaned: List[str] = []
    for line in raw_text.splitlines():
        line = MULTISPACE.sub(" ", line).strip()
        if not line:
            continue
        if any(pattern.match(line) for pattern in HEADER_FOOTER_PATTERNS):
            continue
        cleaned.append(line)
    return cleaned


def _merge_broken_case_lines(lines: List[str]) -> List[str]:
    """Merge lines when case number is split across adjacent lines."""
    merged: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if CASE_REGEX.search(line):
            merged.append(line)
            i += 1
            continue

        if i + 1 < len(lines):
            candidate = f"{line} {lines[i + 1]}"
            if CASE_REGEX.search(candidate):
                merged.append(candidate)
                i += 2
                continue

        merged.append(line)
        i += 1
    return merged


def extract_text(payload: Dict[str, Any], download_dir: str = "downloads/cause_lists") -> List[Dict[str, str]]:
    """
    Extract raw text from html/pdf payload.

    Returns list of dicts: [{"source_url": ..., "text": ...}, ...]
    """
    outputs: List[Dict[str, str]] = []

    if payload.get("type") == "html":
        html = payload.get("html") or ""
        if html.strip():
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text("\n", strip=True)
            cleaned = "\n".join(_merge_broken_case_lines(_cleanup_lines(text)))
            if cleaned.strip():
                outputs.append({"source_url": payload.get("source_url", ""), "text": cleaned})

        for link in payload.get("pdf_links", []):
            try:
                pdf_payload = fetch_cause_list(link)
                outputs.extend(extract_text(pdf_payload, download_dir=download_dir))
            except Exception as exc:
                LOGGER.warning("Skipping pdf link=%s due to error=%s", link, exc)
        return outputs

    pdf_bytes = payload.get("pdf_bytes")
    source_url = payload.get("source_url", "")
    if not pdf_bytes:
        LOGGER.warning("Empty PDF payload for source=%s", source_url)
        return outputs

    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)
    filename = source_url.split("/")[-1] or f"cause_list_{datetime.utcnow().timestamp()}.pdf"
    local_pdf = download_path / filename
    local_pdf.write_bytes(pdf_bytes)

    extracted_text = ""

    # Preferred: pdfplumber
    if pdfplumber is not None:
        try:
            pages: List[str] = []
            with pdfplumber.open(str(local_pdf)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        pages.append(page_text)
            extracted_text = "\n".join(pages)
        except Exception as exc:
            LOGGER.warning("pdfplumber extraction failed source=%s error=%s", source_url, exc)

    # Fallback: PyMuPDF
    if not extracted_text.strip() and fitz is not None:
        try:
            doc = fitz.open(str(local_pdf))
            pages = [p.get_text("text") for p in doc]
            extracted_text = "\n".join(pages)
            doc.close()
        except Exception as exc:
            LOGGER.warning("PyMuPDF extraction failed source=%s error=%s", source_url, exc)

    if not extracted_text.strip():
        LOGGER.warning(
            "Empty or scanned PDF with no extractable text source=%s; OCR fallback not enabled",
            source_url,
        )
        return outputs

    cleaned_lines = _merge_broken_case_lines(_cleanup_lines(extracted_text))
    cleaned_text = "\n".join(cleaned_lines)
    if not cleaned_text.strip():
        LOGGER.warning("No usable text after cleanup for source=%s", source_url)
        return outputs

    outputs.append({"source_url": source_url, "text": cleaned_text})
    return outputs


def normalize_case(case_number: str) -> str:
    if not case_number:
        return ""
    text = case_number.upper()
    text = re.sub(r"\s+", "", text)
    text = text.replace("..", ".")
    text = text.replace("-", "")
    text = text.replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    return text


def normalize_party_name(party_names: str) -> str:
    if not party_names:
        return ""
    text = party_names.lower()
    text = VS_PATTERN.sub(" ", text)
    text = NON_ALNUM_SPACE.sub(" ", text)
    text = MULTISPACE.sub(" ", text).strip()
    return text


def _extract_item_number(line: str) -> str:
    match = ITEM_REGEX.search(line)
    return match.group(1) if match else ""


def _extract_court_number(line: str) -> str:
    match = COURT_REGEX.search(line)
    return match.group(1) if match else ""


def _extract_party_names(line: str, case_number: str) -> str:
    # Party names are often between case id and trailing metadata.
    start = line.find(case_number)
    tail = line[start + len(case_number):] if start >= 0 else line
    tail = re.sub(r"\bITEM\b.*$", "", tail, flags=re.IGNORECASE)
    tail = re.sub(r"\bCOURT\b.*$", "", tail, flags=re.IGNORECASE)
    return MULTISPACE.sub(" ", tail).strip(" :-")


def parse_entries(text_blocks: List[Dict[str, str]]) -> Tuple[List[CauseListEntry], List[str]]:
    parsed: List[CauseListEntry] = []
    failed_lines: List[str] = []

    for block in text_blocks:
        source_url = block.get("source_url")
        for line in (block.get("text") or "").splitlines():
            case_match = CASE_REGEX.search(line)
            if not case_match:
                continue

            case_number = case_match.group(0).strip()
            party_names = _extract_party_names(line, case_number)
            court_number = _extract_court_number(line)
            item_number = _extract_item_number(line)

            if not case_number:
                failed_lines.append(line)
                continue

            parsed.append(
                CauseListEntry(
                    case_number=case_number,
                    party_names=party_names,
                    court_number=court_number,
                    item_number=item_number,
                    source_url=source_url,
                )
            )

    return parsed, failed_lines


def _entry_key(entry: CauseListEntry) -> Tuple[str, str, str]:
    return (
        normalize_case(entry.case_number),
        normalize_party_name(entry.party_names),
        entry.item_number.strip(),
    )


def deduplicate_entries(entries: List[CauseListEntry]) -> List[CauseListEntry]:
    seen: set[Tuple[str, str, str]] = set()
    deduped: List[CauseListEntry] = []
    for entry in entries:
        key = _entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def match_cases(
    tracked_cases: List[Dict[str, Any]],
    parsed_entries: List[CauseListEntry],
    fuzzy_threshold: int = 85,
) -> Tuple[List[MatchResult], List[Dict[str, Any]]]:
    """
    Matching strategy:
      1) Exact case-number match => HIGH confidence (100)
      2) Fuzzy party-name match > threshold => MEDIUM confidence (score)
    """
    if fuzz is None:
        raise RuntimeError("rapidfuzz is required for fuzzy matching. Install rapidfuzz.")

    results: List[MatchResult] = []
    unmatched_tracked: List[Dict[str, Any]] = []

    normalized_entries = [
        {
            "entry": entry,
            "case_number": normalize_case(entry.case_number),
            "party_names": normalize_party_name(entry.party_names),
        }
        for entry in parsed_entries
    ]

    for tracked in tracked_cases:
        tracked_case_raw = str(tracked.get("case_number") or tracked.get("normalized_case_id") or "")
        tracked_party_raw = str(tracked.get("party_names") or tracked.get("title") or "")

        tracked_case = normalize_case(tracked_case_raw)
        tracked_party = normalize_party_name(tracked_party_raw)

        matched = False

        # 1) Exact case-number match (HIGH)
        if tracked_case:
            for norm_entry in normalized_entries:
                if tracked_case and tracked_case == norm_entry["case_number"]:
                    entry: CauseListEntry = norm_entry["entry"]
                    results.append(
                        MatchResult(
                            tracked_case_id=str(tracked.get("id") or tracked_case_raw),
                            confidence="HIGH",
                            confidence_score=100,
                            reason="Exact normalized case number match",
                            entry={
                                "case_number": entry.case_number,
                                "party_names": entry.party_names,
                                "court_number": entry.court_number,
                                "item_number": entry.item_number,
                                "source_url": entry.source_url,
                            },
                        )
                    )
                    matched = True
                    break

        if matched:
            continue

        # 2) Fuzzy party-name match (MEDIUM)
        if tracked_party:
            best_score = -1
            best_entry: Optional[CauseListEntry] = None
            for norm_entry in normalized_entries:
                if not norm_entry["party_names"]:
                    continue
                score = fuzz.token_sort_ratio(tracked_party, norm_entry["party_names"])
                if score > best_score:
                    best_score = score
                    best_entry = norm_entry["entry"]

            if best_entry is not None and best_score >= fuzzy_threshold:
                results.append(
                    MatchResult(
                        tracked_case_id=str(tracked.get("id") or tracked_case_raw),
                        confidence="MEDIUM",
                        confidence_score=int(best_score),
                        reason=f"Fuzzy party-name match >= {fuzzy_threshold}",
                        entry={
                            "case_number": best_entry.case_number,
                            "party_names": best_entry.party_names,
                            "court_number": best_entry.court_number,
                            "item_number": best_entry.item_number,
                            "source_url": best_entry.source_url,
                        },
                    )
                )
                matched = True

        if not matched:
            unmatched_tracked.append(tracked)

    return results, unmatched_tracked


def run_pipeline(
    base_url: str,
    tracked_cases: List[Dict[str, Any]],
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    fuzzy_threshold: int = 85,
) -> Dict[str, Any]:
    payload = fetch_cause_list(base_url, timeout=timeout)
    text_blocks = extract_text(payload)

    if not text_blocks:
        return {
            "matched_cases": [],
            "parsed_entries": [],
            "failed_parses": ["No extractable cause-list text found"],
            "unmatched_tracked_cases": tracked_cases,
            "stats": {
                "total_entries_parsed": 0,
                "failed_parses": 1,
                "unmatched_tracked_cases": len(tracked_cases),
            },
        }

    parsed_entries, failed_parses = parse_entries(text_blocks)
    parsed_entries = deduplicate_entries(parsed_entries)

    matches, unmatched = match_cases(
        tracked_cases=tracked_cases,
        parsed_entries=parsed_entries,
        fuzzy_threshold=fuzzy_threshold,
    )

    LOGGER.info("Total entries parsed: %d", len(parsed_entries))
    LOGGER.info("Failed parses: %d", len(failed_parses))
    LOGGER.info("Unmatched tracked cases: %d", len(unmatched))

    for idx, entry in enumerate(parsed_entries[:5], start=1):
        LOGGER.info(
            "Sample parsed entry %d: case=%s party=%s court=%s item=%s",
            idx,
            entry.case_number,
            entry.party_names,
            entry.court_number,
            entry.item_number,
        )

    return {
        "matched_cases": [m.__dict__ for m in matches],
        "parsed_entries": [e.__dict__ for e in parsed_entries],
        "failed_parses": failed_parses,
        "unmatched_tracked_cases": unmatched,
        "stats": {
            "total_entries_parsed": len(parsed_entries),
            "failed_parses": len(failed_parses),
            "unmatched_tracked_cases": len(unmatched),
        },
    }


if __name__ == "__main__":
    setup_logging(logging.INFO)

    BASE_URL = "https://delhihighcourt.nic.in/web/cause-lists/cause-list"
    TRACKED_CASES = [
        {"id": 1, "case_number": "W.P.(C) 1234/2024", "party_names": "ABC Pvt Ltd vs State"},
        {"id": 2, "case_number": "CM APPL. 11440/2026", "party_names": "John Doe versus Union of India"},
    ]

    output = run_pipeline(BASE_URL, TRACKED_CASES)
    LOGGER.info("Pipeline complete: matches=%d", len(output["matched_cases"]))
