import logging
import re
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
import requests

from cause_list_fetcher import fetch_gurugram_district_pdfs, parse_cause_list_pdf
from ecourts_api import (
    build_case_status_message,
    is_ecourts_api_configured,
    lookup_case_listings,
    match_case_listing,
    normalize_case,
    normalize_ecourts_response,
)
from ecourts_pipeline import fetch_ecourts_causelist

logger = logging.getLogger(__name__)


DELHI_HC_CASE_TYPES = {
    "WP",
    "WPC",
    "LPA",
    "CSOS",
    "CS",
}


def _compact_case_type(case_number: str | None) -> str:
    if not case_number:
        return ""
    first_part = str(case_number).split("/", 1)[0]
    return re.sub(r"[^A-Z0-9]", "", first_part.upper())


def resolve_court_from_case(case_number: str | None, message: str | None = None) -> dict[str, str]:
    """Resolve logical court routing for the pipeline.

    Priority:
    1) Explicit district mention in incoming message.
    2) Known Delhi High Court case types (WP, LPA, CS(OS)).
    3) Default to Delhi HC for unmapped case-type inputs.
    """
    message_text = (message or "").lower()
    case_type = _compact_case_type(case_number)

    if "gurugram" in message_text or "gurgaon" in message_text:
        return {
            "court_key": "gurugram",
            "court_name": "District and Sessions Courts, Gurugram",
        }

    if "sonipat" in message_text or "sonepat" in message_text:
        return {
            "court_key": "sonipat",
            "court_name": "District and Sessions Courts, Sonipat",
        }

    if case_type in DELHI_HC_CASE_TYPES:
        return {
            "court_key": "delhi_hc",
            "court_name": "Delhi High Court",
        }

    return {
        "court_key": "delhi_hc",
        "court_name": "Delhi High Court",
    }


def _normalize_case_number(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(
        r"\b([A-Z][A-Z\.\(\)\s-]*?)\s*[-/]?\s*(\d+)\s*(?:[-/]|OF)\s*(\d{4})\b",
        value.upper(),
    )
    if not match:
        return None
    case_type, number, year = match.groups()
    case_type = re.sub(r"[^A-Z0-9]", "", case_type)
    prefixes = ["WITH", "AND", "ITEM", "CASE"]
    changed = True
    while changed and case_type:
        changed = False
        for prefix in prefixes:
            if case_type.startswith(prefix) and len(case_type) > len(prefix):
                case_type = case_type[len(prefix):]
                changed = True
                break
    return f"{case_type}/{int(number)}/{year}"


class CourtSource(ABC):
    def __init__(self, name: str, source_type: str):
        self.name = name
        self.source_type = source_type
        self.last_fetch_meta: dict[str, Any] = {}

    @abstractmethod
    def fetch_cases(self, hearing_date: str) -> list[dict[str, Any]]:
        """Fetch and return normalized case dictionaries."""


class PDFCauseListSource(CourtSource):
    def __init__(self, name: str = "gurugram", district: str = "Gurugram"):
        super().__init__(name=name, source_type="pdf")
        self.district = district

    def fetch_cases(self, hearing_date: str) -> list[dict[str, Any]]:
        files = fetch_gurugram_district_pdfs()
        normalized_cases: list[dict[str, Any]] = []

        for filepath in files:
            entries, extracted_date = parse_cause_list_pdf(filepath)
            final_date = extracted_date or hearing_date

            for entry in entries:
                canonical_case = _normalize_case_number(entry.get("case_number") or entry.get("case_no"))
                if not canonical_case:
                    continue

                normalized_cases.append(
                    {
                        "case_number": canonical_case,
                        "title": entry.get("title") or "Unknown Title",
                        "court_number": entry.get("item") or "Unknown",
                        "judge": entry.get("judge") or "Unknown Judge",
                        "status": entry.get("status") or "Listed",
                        "hearing_date": entry.get("hearing_date") or final_date,
                        "district": self.district,
                        "court": entry.get("court") or f"District and Sessions Courts, {self.district}",
                        "advocate": entry.get("advocate") or "Unknown Advocate",
                        "raw": entry.get("raw") or "",
                    }
                )

        logger.info("PDF source '%s' fetched %d cases", self.name, len(normalized_cases))
        return normalized_cases


class HTMLCauseListSource(CourtSource):
    def __init__(
        self,
        name: str = "sonipat",
        district: str = "Sonipat",
        state_code: str = "HR",
        district_id: int = 13,
        base_url: str | None = None,
        timeout: int = 20,
        session: Any | None = None,
    ):
        super().__init__(name=name, source_type="html")
        self.district = district
        self.state_code = state_code
        self.district_id = int(district_id)
        self.base_url = base_url
        self.default_base_url = f"https://ecourtsindia.com/causelist/{self.state_code}/{self.district_id}"
        self.timeout = timeout
        self.session = session

    def _legacy_parse_table(self, html_text: str, hearing_date: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html_text or "", "html.parser")
        table = soup.find("table")
        if table is None:
            return []

        parsed: list[dict[str, Any]] = []
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if len(cells) < 8:
                continue
            if cells[0].lower().startswith("listing"):
                continue

            case_number = _normalize_case_number(cells[1])
            if not case_number:
                continue

            parsed.append(
                {
                    "case_number": case_number,
                    "title": cells[3],
                    "court_number": cells[4],
                    "judge": cells[6],
                    "status": cells[7],
                    "hearing_date": cells[2] or hearing_date,
                    "district": self.district,
                    "court": f"District and Sessions Courts, {self.district}",
                    "advocate": cells[5],
                    "raw": " | ".join(cells),
                }
            )

        return parsed

    def _legacy_fetch_cases(self, hearing_date: str) -> list[dict[str, Any]]:
        session = self.session or requests.Session()
        base_url = self.base_url or self.default_base_url
        candidate_dates = [hearing_date]
        try:
            candidate_dates.append(date.fromisoformat(hearing_date).strftime("%d-%m-%Y"))
        except Exception:
            pass

        try:
            root_response = session.get(base_url, timeout=self.timeout)
            root_response.raise_for_status()
        except Exception as exc:
            logger.exception("Legacy eCourts source root fetch failed: %s", exc)
            self.last_fetch_meta = {
                "api_status": "failure",
                "source_mode": "legacy_html",
                "error": str(exc),
                "cases_checked": 0,
                "matches_found": 0,
            }
            return []

        root_soup = BeautifulSoup(root_response.text or "", "html.parser")
        complex_ids = [opt.get("value") for opt in root_soup.select("select#complex option[value]") if opt.get("value")]
        if not complex_ids:
            complex_ids = [None]

        parsed_rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        for complex_id in complex_ids:
            complex_url = base_url if not complex_id else f"{base_url}/{complex_id}"
            try:
                complex_response = session.get(complex_url, timeout=self.timeout)
                complex_response.raise_for_status()
            except Exception:
                continue

            complex_soup = BeautifulSoup(complex_response.text or "", "html.parser")
            judge_ids = [opt.get("value") for opt in complex_soup.select("select#judge option[value]") if opt.get("value")]
            if not judge_ids:
                judge_ids = [None]

            for judge_id in judge_ids:
                candidate_urls = []
                if complex_id and judge_id:
                    for date_token in candidate_dates:
                        candidate_urls.append(f"{base_url}/{complex_id}/{judge_id}/{date_token}")
                        candidate_urls.append(f"{base_url}/{complex_id}/{judge_id}/4-30/{date_token}")
                elif complex_id:
                    candidate_urls.append(f"{base_url}/{complex_id}")

                for candidate_url in candidate_urls:
                    try:
                        response = session.get(candidate_url, timeout=self.timeout)
                        if response.status_code != 200:
                            continue
                    except Exception:
                        continue

                    for row in self._legacy_parse_table(response.text, hearing_date):
                        key = (row.get("case_number") or "", row.get("court_number") or "", row.get("judge") or "")
                        if key in seen:
                            continue
                        seen.add(key)
                        parsed_rows.append(row)

        self.last_fetch_meta = {
            "api_status": "disabled",
            "source_mode": "legacy_html",
            "cases_checked": len(parsed_rows),
            "matches_found": 0,
        }
        return parsed_rows

    def fetch_cases(self, hearing_date: str) -> list[dict[str, Any]]:
        if is_ecourts_api_configured():
            try:
                payload = lookup_case_listings([], court_id=self.district_id, hearing_date=hearing_date, court_label=self.district)
                api_payload = payload.get("entries") or []
                normalized_cases: list[dict[str, Any]] = []
                for row in api_payload:
                    canonical_case = _normalize_case_number(row.get("case_number"))
                    if not canonical_case:
                        continue
                    normalized_cases.append(
                        {
                            "case_number": canonical_case,
                            "title": (row.get("party_names") or row.get("case_number") or "Unknown Title").strip(),
                            "court_number": (row.get("court_number") or row.get("court_no") or "").strip() or "Unknown",
                            "judge": (row.get("judge") or "Unknown Judge").strip(),
                            "status": row.get("status") or "Listed",
                            "hearing_date": (row.get("hearing_date") or row.get("listing_date") or hearing_date).strip(),
                            "district": self.district,
                            "court": row.get("court") or f"District and Sessions Courts, {self.district}",
                            "advocate": row.get("advocate") or "Unknown Advocate",
                            "raw": row.get("raw") or row.get("party_names") or canonical_case,
                        }
                    )

                self.last_fetch_meta = {
                    "api_status": payload.get("api_status", "success"),
                    "source_mode": "api",
                    "cases_checked": len(normalized_cases),
                    "matches_found": payload.get("matches_found", 0),
                }
                logger.info(
                    "eCourts API source '%s' fetched %d cases api_status=%s",
                    self.name,
                    len(normalized_cases),
                    self.last_fetch_meta.get("api_status"),
                )
                return normalized_cases
            except Exception as exc:
                self.last_fetch_meta = {
                    "api_status": "failure",
                    "source_mode": "api",
                    "error": str(exc),
                    "cases_checked": 0,
                    "matches_found": 0,
                }
                logger.exception("eCourts API source '%s' failed: %s", self.name, exc)
                return []

        if self.session is not None or self.base_url is not None:
            legacy_rows = self._legacy_fetch_cases(hearing_date)
            logger.info("Legacy HTML source '%s' fetched %d cases", self.name, len(legacy_rows))
            return legacy_rows

        result = fetch_ecourts_causelist(
            state_code=self.state_code,
            district_id=self.district_id,
            hearing_date=hearing_date,
        )

        normalized_cases = []
        for row in result.get("entries") or []:
            canonical_case = _normalize_case_number(row.get("case_number"))
            if not canonical_case:
                continue
            normalized_cases.append(
                {
                    "case_number": canonical_case,
                    "title": (row.get("party_names") or "Unknown Title").strip(),
                    "court_number": (row.get("court_number") or "").strip() or "Unknown",
                    "judge": "Unknown Judge",
                    "status": "Listed" + (" (stale-cache)" if result.get("stale") else ""),
                    "hearing_date": (row.get("hearing_date") or hearing_date).strip(),
                    "district": self.district,
                    "court": f"District and Sessions Courts, {self.district}",
                    "advocate": "Unknown Advocate",
                    "raw": row.get("party_names") or canonical_case,
                }
            )

        self.last_fetch_meta = {
            "api_status": "disabled",
            "source_mode": "legacy_html",
            "cases_checked": len(normalized_cases),
            "matches_found": 0,
        }
        logger.info("HTML source '%s' fetched %d cases stale=%s", self.name, len(normalized_cases), result.get("stale"))
        return normalized_cases


class FormBasedSource(CourtSource):
    """Placeholder for court systems requiring form posts and sessions."""

    def __init__(self, name: str):
        super().__init__(name=name, source_type="form")

    def fetch_cases(self, hearing_date: str) -> list[dict[str, Any]]:
        logger.warning("FormBasedSource '%s' is not configured yet.", self.name)
        return []


court_sources: dict[str, CourtSource] = {
    "gurugram": HTMLCauseListSource(name="gurugram", district="Gurugram", state_code="HR", district_id=6),
    "sonipat": HTMLCauseListSource(name="sonipat", district="Sonipat", state_code="HR", district_id=13),
}


def today_iso() -> str:
    return date.today().isoformat()
