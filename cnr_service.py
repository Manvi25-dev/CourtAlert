import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CNR_PATTERN = re.compile(r"\b([A-Z]{3,4}[0-9]{12,13})\b", re.IGNORECASE)


def extract_cnr(text: str) -> str | None:
    if not text:
        return None
    match = CNR_PATTERN.search(text.upper())
    return match.group(1) if match else None


def fetch_case_details_by_cnr(cnr: str, timeout: int = 20) -> dict[str, Any] | None:
    normalized = extract_cnr(cnr)
    if not normalized:
        return None

    url = f"https://ecourtsindia.com/cnr/{normalized}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("CNR fetch failed for %s: %s", normalized, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    fields: dict[str, str] = {}
    for row in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        if len(cells) < 2:
            continue
        key = re.sub(r"\s+", " ", cells[0].strip().lower())
        val = re.sub(r"\s+", " ", cells[1].strip())
        if key:
            fields[key] = val

    def _pick_field(*aliases: str) -> str:
        for alias in aliases:
            value = fields.get(alias)
            if value:
                return value
        return ""

    title = _pick_field("case title", "title")
    case_number = _pick_field("case no", "registration number") or normalized
    next_hearing_date = _pick_field(
        "next hearing date",
        "next date",
        "date of hearing",
        "next hearing",
        "next hearing dt",
    )
    details = {
        "cnr": normalized,
        "case_number": case_number,
        "title": title,
        "court": _pick_field("court name", "court") or "Unknown Court",
        "district": _pick_field("district"),
        "state": _pick_field("state"),
        "case_type": _pick_field("case type"),
        "registration_number": _pick_field("registration number"),
        "filing_number": _pick_field("filing number"),
        "petitioner": _pick_field("petitioner", "petitioner and advocate"),
        "respondents": _pick_field("respondent", "respondents"),
        "advocates": _pick_field("advocate", "advocates"),
        "next_hearing_date": next_hearing_date,
    }

    return details
