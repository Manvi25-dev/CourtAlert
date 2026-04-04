import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CNR_PATTERN = re.compile(r"\b([A-Z]{3}[0-9]{13})\b", re.IGNORECASE)


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

    title = fields.get("case title") or fields.get("title") or ""
    case_number = fields.get("case no") or fields.get("registration number") or normalized
    details = {
        "cnr": normalized,
        "case_number": case_number,
        "title": title,
        "court": fields.get("court name") or fields.get("court") or "Unknown Court",
        "district": fields.get("district") or "",
        "state": fields.get("state") or "",
        "case_type": fields.get("case type") or "",
        "registration_number": fields.get("registration number") or "",
        "filing_number": fields.get("filing number") or "",
        "petitioner": fields.get("petitioner") or fields.get("petitioner and advocate") or "",
        "respondents": fields.get("respondent") or fields.get("respondents") or "",
        "advocates": fields.get("advocate") or fields.get("advocates") or "",
    }

    return details
