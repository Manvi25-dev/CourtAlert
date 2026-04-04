import logging
import os
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from cause_list_fetcher import CAUSE_LIST_URL, parse_cause_list_pdf
from sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class CourtPortalFormAdapter(SourceAdapter):
    """Delhi High Court cause-list adapter using public PDF links."""

    def __init__(self, download_dir: str = "cause_lists"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, hearing_date: str) -> Any:
        del hearing_date
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml",
            }
        )
        try:
            response = session.get(CAUSE_LIST_URL, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            pdf_urls: list[str] = []
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if not href.lower().endswith(".pdf"):
                    continue
                full_url = href if href.startswith("http") else f"https://delhihighcourt.nic.in{href}"
                pdf_urls.append(full_url)

            logger.info("Delhi HC source discovered %d pdf links", len(pdf_urls))
            return pdf_urls
        except Exception as exc:
            logger.exception("Delhi HC source fetch failed: %s", exc)
            return []

    def parse(self, content: Any, hearing_date: str) -> list[dict]:
        pdf_urls: list[str] = content or []
        parsed_rows: list[dict] = []

        for pdf_url in pdf_urls:
            try:
                filename = pdf_url.split("/")[-1]
                filepath = self.download_dir / filename
                if not filepath.exists():
                    dl = requests.get(pdf_url, timeout=20)
                    dl.raise_for_status()
                    filepath.write_bytes(dl.content)

                entries, extracted_date = parse_cause_list_pdf(str(filepath))
                final_date = extracted_date or hearing_date
                for entry in entries:
                    case_number = entry.get("case_number") or entry.get("case_no")
                    if not case_number:
                        continue
                    parsed_rows.append(
                        {
                            "case_number": case_number,
                            "title": entry.get("title") or "Unknown Title",
                            "court": entry.get("court") or "Delhi High Court",
                            "court_number": entry.get("item") or entry.get("court_number") or "",
                            "judge": entry.get("judge") or "Unknown Judge",
                            "status": entry.get("status") or "Listed",
                            "hearing_date": entry.get("hearing_date") or final_date,
                            "district": entry.get("district") or "Delhi",
                            "advocate": entry.get("advocate") or "Unknown Advocate",
                            "cnr": entry.get("cnr"),
                            "raw": entry.get("raw") or "",
                        }
                    )
            except Exception as exc:
                logger.exception("Delhi HC source parse failed for %s: %s", pdf_url, exc)

        logger.info("Delhi HC source parsed %d entries", len(parsed_rows))
        return parsed_rows
