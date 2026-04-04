from typing import Any

from cause_list_fetcher import fetch_gurugram_district_pdfs, parse_cause_list_pdf
from court_sources import _normalize_case_number
from sources.base import SourceAdapter


class PDFCauseListAdapter(SourceAdapter):
    def __init__(self, district: str = "Gurugram"):
        self.district = district

    def fetch(self, hearing_date: str) -> list[str]:
        return fetch_gurugram_district_pdfs()

    def parse(self, content: Any, hearing_date: str) -> list[dict]:
        files: list[str] = content or []
        rows: list[dict] = []
        for filepath in files:
            entries, extracted_date = parse_cause_list_pdf(filepath)
            final_date = extracted_date or hearing_date
            for entry in entries:
                canonical = _normalize_case_number(entry.get("case_number") or entry.get("case_no"))
                if not canonical:
                    continue
                rows.append(
                    {
                        "case_number": canonical,
                        "title": entry.get("title") or "Unknown Title",
                        "court": entry.get("court") or f"District and Sessions Courts, {self.district}",
                        "court_number": entry.get("item") or "Unknown",
                        "judge": entry.get("judge") or "Unknown Judge",
                        "status": entry.get("status") or "Listed",
                        "hearing_date": entry.get("hearing_date") or final_date,
                        "district": self.district,
                        "advocate": entry.get("advocate") or "Unknown Advocate",
                        "cnr": entry.get("cnr"),
                        "raw": entry.get("raw") or "",
                    }
                )
        return rows
