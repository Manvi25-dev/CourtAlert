import logging
from typing import Any

from cause_list_fetcher import CAUSE_LIST_URL
from cause_list_pipeline import (
    deduplicate_entries,
    extract_text,
    fetch_cause_list,
    parse_entries,
)
from sources.base import SourceAdapter

logger = logging.getLogger(__name__)


class CourtPortalFormAdapter(SourceAdapter):
    """Delhi High Court cause-list adapter using public PDF links."""

    def __init__(self, download_dir: str = "cause_lists", base_url: str = CAUSE_LIST_URL):
        self.download_dir = download_dir
        self.base_url = base_url

    def fetch(self, hearing_date: str) -> Any:
        del hearing_date
        try:
            payload = fetch_cause_list(self.base_url)
            pdf_count = len(payload.get("pdf_links") or [])
            logger.info("Delhi HC source discovered %d pdf links", pdf_count)
            return payload
        except Exception as exc:
            logger.exception("Delhi HC source fetch failed: %s", exc)
            return {"type": "html", "source_url": self.base_url, "html": "", "pdf_links": [], "pdf_bytes": None}

    def parse(self, content: Any, hearing_date: str) -> list[dict]:
        parsed_rows: list[dict] = []

        try:
            text_blocks = extract_text(content or {}, download_dir=self.download_dir)
            entries, failed_parses = parse_entries(text_blocks)
            entries = deduplicate_entries(entries)

            logger.info(
                "Delhi HC parsing summary: text_blocks=%d entries=%d failed_lines=%d",
                len(text_blocks),
                len(entries),
                len(failed_parses),
            )

            for idx, entry in enumerate(entries[:5], start=1):
                logger.info(
                    "Delhi HC sample %d: case=%s party=%s court_no=%s item_no=%s",
                    idx,
                    entry.case_number,
                    entry.party_names,
                    entry.court_number,
                    entry.item_number,
                )

            for entry in entries:
                parsed_rows.append(
                    {
                        "case_number": entry.case_number,
                        "case_numbers": [entry.case_number],
                        "title": entry.party_names or "Unknown Title",
                        "court": "Delhi High Court",
                        "court_number": entry.court_number or "",
                        "item": entry.item_number or "",
                        "judge": "Unknown Judge",
                        "status": "Listed",
                        "hearing_date": hearing_date,
                        "district": "Delhi",
                        "advocate": "Unknown Advocate",
                        "cnr": None,
                        "raw": entry.case_number,
                        "source": entry.source_url,
                    }
                )
        except Exception as exc:
            logger.exception("Delhi HC source parse failed: %s", exc)

        target_hits = [row.get("case_number") for row in parsed_rows if "11440" in str(row.get("case_number") or "")]
        if target_hits:
            logger.info("TARGET CASE FOUND IN PARSED ROWS: %s", target_hits[:10])
        else:
            logger.info("TARGET CASE NOT FOUND IN PARSED ROWS (search: 11440)")

        logger.info("Delhi HC source parsed %d entries", len(parsed_rows))
        return parsed_rows
