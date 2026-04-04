import logging
import re
from abc import ABC, abstractmethod
from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from cause_list_fetcher import fetch_gurugram_district_pdfs, parse_cause_list_pdf

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
        base_url: str = "https://ecourtsindia.com/causelist/HR/13",
        judge_ids: list[str] | None = None,
        court_range: str = "4-30",
        timeout: int = 20,
    ):
        super().__init__(name=name, source_type="html")
        self.district = district
        self.base_url = base_url.rstrip("/")
        self.judge_ids = judge_ids or []
        self.court_range = court_range
        self.timeout = timeout
        self.session = requests.Session()
        self.default_complex_ids: list[str] = []

    def _to_ecourts_date(self, hearing_date: str) -> str:
        if re.match(r"\d{4}-\d{2}-\d{2}", hearing_date):
            y, m, d = hearing_date.split("-")
            return f"{d}-{m}-{y}"
        return hearing_date

    def _safe_get_soup(self, url: str) -> BeautifulSoup | None:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            logger.error("HTML source '%s' request failed for %s: %s", self.name, url, exc)
            return None

    def _extract_ids_from_options(self, soup: BeautifulSoup, keys: tuple[str, ...]) -> list[str]:
        found: list[str] = []
        for select in soup.select("select"):
            select_name = (select.get("name") or "").lower()
            select_id = (select.get("id") or "").lower()
            if not any(k in select_name or k in select_id for k in keys):
                continue

            for option in select.select("option"):
                value = (option.get("value") or "").strip()
                if re.fullmatch(r"\d+", value):
                    found.append(value)
        return found

    def _extract_path_ids(self, text: str, prefix_parts: int, limit: int = 2) -> list[tuple[str, ...]]:
        # Example match target for cause list URLs:
        # /causelist/HR/13/{complex}/{court}/{date}
        pattern = rf"/causelist/HR/13(?:/([0-9]{{1,10}})){{{prefix_parts},{prefix_parts + limit}}}"
        matches = re.findall(pattern, text)
        ids: list[tuple[str, ...]] = []
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, tuple):
                    vals = tuple(v for v in m if v)
                    if vals:
                        ids.append(vals)
                elif m:
                    ids.append((m,))
        return ids

    def _discover_complexes(self) -> list[str]:
        soup = self._safe_get_soup(self.base_url)
        if not soup:
            return list(self.default_complex_ids)

        complexes = set(self._extract_ids_from_options(soup, ("complex", "est", "court_complex")))

        html = str(soup)
        for match in re.finditer(r"/causelist/HR/13/(\d+)", html):
            complexes.add(match.group(1))

        if not complexes:
            complexes.update(self.default_complex_ids)

        discovered = sorted(complexes)
        logger.info("HTML source '%s' discovered complexes: %s", self.name, discovered)
        return discovered

    def _discover_judges_for_complex(self, complex_id: str) -> list[str]:
        complex_url = f"{self.base_url}/{complex_id}"
        soup = self._safe_get_soup(complex_url)
        if not soup:
            return list(self.judge_ids)

        judges = set(self._extract_ids_from_options(soup, ("judge", "court", "bench")))

        html = str(soup)
        # Prefer explicit /{complex}/{court}/... paths.
        for m in re.finditer(rf"/causelist/HR/13/{re.escape(complex_id)}/(\d+)", html):
            judges.add(m.group(1))

        if not judges:
            judges.update(self.judge_ids)

        discovered = sorted(judges)
        logger.info(
            "HTML source '%s' discovered judges/courts for complex %s: %s",
            self.name,
            complex_id,
            discovered,
        )
        return discovered

    def _build_cause_list_urls(self, complex_id: str, judge_id: str, hearing_date: str) -> list[str]:
        date_part = self._to_ecourts_date(hearing_date)
        return [
            f"{self.base_url}/{complex_id}/{judge_id}/{date_part}",
            f"{self.base_url}/{complex_id}/{judge_id}/{self.court_range}/{date_part}",
        ]

    def _build_urls(self, hearing_date: str) -> list[str]:
        # eCourts expects dd-mm-YYYY in URL.
        date_part = hearing_date
        if re.match(r"\d{4}-\d{2}-\d{2}", hearing_date):
            y, m, d = hearing_date.split("-")
            date_part = f"{d}-{m}-{y}"

        urls = []
        for judge_id in self.judge_ids:
            urls.append(f"{self.base_url}/{judge_id}/{self.court_range}/{date_part}")
        return urls

    def _extract_rows(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        cases: list[dict[str, str]] = []

        # Preferred: semantic entry blocks
        for entry in soup.select(".case-entry"):
            text = lambda sel: re.sub(r"\s+", " ", (entry.select_one(sel).get_text(" ", strip=True) if entry.select_one(sel) else "")).strip()
            cases.append(
                {
                    "case_number": text(".case-number"),
                    "title": text(".parties, .title"),
                    "court_number": text(".court-number"),
                    "judge": text(".judge"),
                    "status": text(".status"),
                    "advocate": text(".advocate"),
                    "hearing_date": text(".date, .hearing-date"),
                }
            )

        if cases:
            return cases

        # Fallback: tabular extraction with dynamic header mapping.
        for table in soup.select("table"):
            header_cells = []
            header_row = table.select_one("tr")
            if header_row:
                header_cells = [
                    re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip().lower()
                    for h in header_row.find_all(["th", "td"])
                ]

            colmap = {
                "case_number": None,
                "title": None,
                "court_number": None,
                "judge": None,
                "status": None,
                "advocate": None,
                "hearing_date": None,
            }

            for idx, h in enumerate(header_cells):
                if "case" in h and ("no" in h or "number" in h or "type" in h):
                    colmap["case_number"] = idx
                elif "parties" in h or "title" in h:
                    colmap["title"] = idx
                elif "court" in h and "no" in h:
                    colmap["court_number"] = idx
                elif "judge" in h:
                    colmap["judge"] = idx
                elif "status" in h:
                    colmap["status"] = idx
                elif "advocate" in h:
                    colmap["advocate"] = idx
                elif "date" in h:
                    colmap["hearing_date"] = idx

            for row in table.select("tr"):
                cells = [
                    re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()
                    for td in row.find_all("td")
                ]
                if len(cells) < 3:
                    continue

                row_text_upper = " ".join(cells).upper()
                if "LISTING NO" in row_text_upper or "CASE TYPE" in row_text_upper:
                    continue

                def pick(key: str, default_idx: int) -> str:
                    idx = colmap.get(key)
                    if isinstance(idx, int) and 0 <= idx < len(cells):
                        return cells[idx]
                    if default_idx < len(cells):
                        return cells[default_idx]
                    return ""

                cases.append(
                    {
                        "case_number": pick("case_number", 1),
                        "title": pick("title", 3),
                        "court_number": pick("court_number", 0),
                        "judge": pick("judge", 6),
                        "status": pick("status", 1),
                        "advocate": pick("advocate", 4),
                        "hearing_date": pick("hearing_date", 7),
                    }
                )

        return cases

    def _parse_cause_list_page(self, url: str, hearing_date: str) -> list[dict[str, Any]]:
        soup = self._safe_get_soup(url)
        if not soup:
            return []

        raw_rows = self._extract_rows(soup)
        normalized_cases: list[dict[str, Any]] = []

        for row in raw_rows:
            canonical_case = _normalize_case_number(row.get("case_number"))
            if not canonical_case:
                continue

            title = re.sub(r"\s+", " ", (row.get("title") or "").replace("Add case", "")).strip()
            normalized_cases.append(
                {
                    "case_number": canonical_case,
                    "title": title or "Unknown Title",
                    "court_number": (row.get("court_number") or "").strip() or "Unknown",
                    "judge": (row.get("judge") or "").strip() or "Unknown Judge",
                    "status": (row.get("status") or "").strip() or "Listed",
                    "hearing_date": (row.get("hearing_date") or hearing_date).strip(),
                    "district": self.district,
                    "court": f"District and Sessions Courts, {self.district}",
                    "advocate": (row.get("advocate") or "").strip() or "Unknown Advocate",
                    "raw": title or canonical_case,
                }
            )

        return normalized_cases

    def fetch_cases(self, hearing_date: str) -> list[dict[str, Any]]:
        normalized_cases: list[dict[str, Any]] = []
        seen = set()

        complex_ids = self._discover_complexes()
        if not complex_ids:
            logger.warning("HTML source '%s' found no complexes; falling back to legacy judge list.", self.name)
            complex_ids = [""]

        for complex_id in complex_ids:
            judge_ids = self._discover_judges_for_complex(complex_id) if complex_id else list(self.judge_ids)
            for judge_id in judge_ids:
                urls = self._build_cause_list_urls(complex_id, judge_id, hearing_date) if complex_id else []
                if not urls and judge_id:
                    urls = [f"{self.base_url}/{judge_id}/{self._to_ecourts_date(hearing_date)}"]

                for url in urls:
                    if "/cnr/" in url.lower():
                        continue

                    rows = self._parse_cause_list_page(url, hearing_date)
                    for row in rows:
                        dedupe_key = (
                            row["case_number"],
                            row["hearing_date"],
                            row["judge"],
                            row["court_number"],
                        )
                        if dedupe_key in seen:
                            continue
                        seen.add(dedupe_key)
                        normalized_cases.append(row)

        logger.info("HTML source '%s' fetched %d cases", self.name, len(normalized_cases))
        return normalized_cases


class FormBasedSource(CourtSource):
    """Placeholder for court systems requiring form posts and sessions."""

    def __init__(self, name: str):
        super().__init__(name=name, source_type="form")

    def fetch_cases(self, hearing_date: str) -> list[dict[str, Any]]:
        logger.warning("FormBasedSource '%s' is not configured yet.", self.name)
        return []


court_sources: dict[str, CourtSource] = {
    "gurugram": PDFCauseListSource(name="gurugram", district="Gurugram"),
    "sonipat": HTMLCauseListSource(name="sonipat", district="Sonipat"),
}


def today_iso() -> str:
    return date.today().isoformat()
