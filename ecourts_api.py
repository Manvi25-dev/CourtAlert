import json
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Any, Iterable

import requests

LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_RETRIES = 3
BACKOFF_SECONDS = (1, 2, 4)
API_UNAVAILABLE_MESSAGE = "Live data temporarily unavailable. We are retrying."


def _env_int(name: str, default: int) -> int:
    raw_value = (os.getenv(name) or "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def get_ecourts_api_config() -> dict[str, Any]:
    base_url = (os.getenv("ECOURTS_API_URL") or os.getenv("ECOURTS_API_BASE_URL") or "").strip()
    api_key = (os.getenv("ECOURTS_API_KEY") or "").strip()
    return {
        "enabled": bool(base_url and api_key),
        "base_url": base_url,
        "api_key": api_key,
        "api_key_header": (os.getenv("ECOURTS_API_KEY_HEADER") or "Authorization").strip(),
        "api_key_prefix": (os.getenv("ECOURTS_API_KEY_PREFIX") or "Bearer").strip(),
        "court_param": (os.getenv("ECOURTS_API_COURT_PARAM") or "court_id").strip(),
        "date_param": (os.getenv("ECOURTS_API_DATE_PARAM") or "date").strip(),
        "timeout_seconds": _env_int("ECOURTS_API_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        "retries": _env_int("ECOURTS_API_RETRIES", DEFAULT_RETRIES),
    }


def is_ecourts_api_configured() -> bool:
    return bool(get_ecourts_api_config()["enabled"])


def normalize_case(case: str | None) -> str:
    if not case:
        return ""
    return re.sub(r"[^A-Z0-9]", "", case.upper())


def _build_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "CourtAlert/1.0",
    }
    api_key = config.get("api_key") or ""
    if not api_key:
        return headers

    header_name = str(config.get("api_key_header") or "Authorization").strip()
    prefix = str(config.get("api_key_prefix") or "").strip()
    if header_name.lower() == "authorization":
        headers[header_name] = f"{prefix} {api_key}".strip() if prefix else api_key
    else:
        headers[header_name] = api_key
    return headers


def _log_api_event(event: str, payload: dict[str, Any]) -> None:
    message = dict(payload)
    message["event"] = event
    LOGGER.info(json.dumps(message, ensure_ascii=True))


def fetch_ecourts_cases(court_id: str | int, date_value: str) -> Any:
    """Fetch raw JSON from the official eCourts API."""

    config = get_ecourts_api_config()
    if not config["enabled"]:
        raise RuntimeError("ECOURTS_API_URL or ECOURTS_API_KEY is not configured")

    params = {
        config["court_param"]: court_id,
        config["date_param"]: date_value,
    }
    headers = _build_headers(config)
    session = requests.Session()

    last_error: Exception | None = None
    for attempt in range(1, int(config["retries"]) + 1):
        try:
            response = session.get(
                str(config["base_url"]),
                params=params,
                headers=headers,
                timeout=int(config["timeout_seconds"]),
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("ECOURTS API returned non-JSON payload") from exc

            _log_api_event(
                "success",
                {
                    "api_status": "success",
                    "court_id": court_id,
                    "date": date_value,
                    "attempt": attempt,
                },
            )
            return payload
        except Exception as exc:
            last_error = exc
            _log_api_event(
                "retry",
                {
                    "api_status": "failure",
                    "court_id": court_id,
                    "date": date_value,
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            if attempt < int(config["retries"]):
                time.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])

    assert last_error is not None
    raise last_error


def _extract_candidate_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    candidate_keys = (
        "data",
        "result",
        "results",
        "entries",
        "items",
        "cases",
        "rows",
        "records",
        "case_list",
    )
    for key in candidate_keys:
        value = payload.get(key)
        if isinstance(value, list):
            records = [item for item in value if isinstance(item, dict)]
            if records:
                return records
        if isinstance(value, dict):
            nested = _extract_candidate_records(value)
            if nested:
                return nested

    if _looks_like_case_record(payload):
        return [payload]

    return []


def _looks_like_case_record(record: dict[str, Any]) -> bool:
    normalized_keys = {str(key).lower().replace(" ", "_") for key in record.keys()}
    expected_fragments = (
        "case_number",
        "case_no",
        "caseno",
        "case",
        "party",
        "party_names",
        "court_no",
        "court_number",
        "judge",
        "date",
        "listing_date",
        "hearing_date",
    )
    return any(fragment in key for key in normalized_keys for fragment in expected_fragments)


def _first_value(record: dict[str, Any], aliases: Iterable[str]) -> str:
    def _normalize_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    for alias in aliases:
        normalized_alias = _normalize_key(alias)
        for key, value in record.items():
            if _normalize_key(str(key)) == normalized_alias:
                cleaned = _clean(value)
                if cleaned:
                    return cleaned
    return ""


def normalize_ecourts_case(record: dict[str, Any], hearing_date: str, court_label: str | None = None) -> dict[str, Any]:
    case_number = _first_value(
        record,
        (
            "case_number",
            "case_no",
            "caseno",
            "casenumber",
            "case",
            "case_id",
        ),
    )
    party_names = _first_value(
        record,
        (
            "party_names",
            "parties",
            "party",
            "case_title",
            "casetitle",
            "title",
        ),
    )
    court_no = _first_value(
        record,
        (
            "court_no",
            "court_number",
            "courtno",
            "court",
            "courtroom",
        ),
    )
    listing_date = _first_value(
        record,
        (
            "listing_date",
            "hearing_date",
            "date",
            "listed_on",
            "listeddate",
        ),
    ) or hearing_date
    judge = _first_value(
        record,
        (
            "judge",
            "judge_name",
            "judgename",
            "bench",
            "court_bench",
        ),
    )
    status = _first_value(
        record,
        (
            "status",
            "listing_status",
            "stage",
            "cause_status",
        ),
    ) or "Listed"

    normalized_case = normalize_case(case_number)
    court_value = _first_value(record, ("court", "court_name", "courtname")) or (court_label or "")

    return {
        "case_number": case_number,
        "normalized_case_number": normalized_case,
        "party_names": party_names,
        "court_no": court_no,
        "court_number": court_no,
        "listing_date": listing_date,
        "hearing_date": listing_date,
        "judge": judge,
        "status": status,
        "court": court_value,
        "raw": record,
    }


def normalize_ecourts_response(payload: Any, hearing_date: str, court_label: str | None = None) -> dict[str, Any]:
    records = _extract_candidate_records(payload)
    entries = []
    for record in records:
        normalized = normalize_ecourts_case(record, hearing_date, court_label=court_label)
        if normalized.get("case_number") or normalized.get("party_names"):
            entries.append(normalized)

    api_status = "success" if payload is not None else "failure"
    return {
        "api_status": api_status,
        "entries": entries,
        "cases_checked": len(entries),
        "matches_found": 0,
        "raw": payload,
    }


def _format_date(value: str | None) -> str:
    if not value:
        return "Unknown Date"

    cleaned = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    return cleaned


def match_case_listing(tracked_case: str, entries: list[dict[str, Any]], checked_date: str | None = None) -> dict[str, Any]:
    tracked_normalized = normalize_case(tracked_case)
    checked_date = checked_date or date.today().isoformat()

    if not tracked_normalized:
        return {
            "case_number": tracked_case,
            "status": "NOT_LISTED",
            "checked_date": checked_date,
            "confidence": "LOW",
        }

    for entry in entries:
        entry_case = _clean(entry.get("case_number"))
        entry_normalized = normalize_case(entry_case)
        if tracked_normalized == entry_normalized:
            return {
                "case_number": entry_case or tracked_case,
                "status": "LISTED",
                "court_no": _clean(entry.get("court_no") or entry.get("court_number")),
                "date": _clean(entry.get("listing_date") or entry.get("hearing_date") or checked_date),
                "judge": _clean(entry.get("judge")),
                "confidence": "HIGH",
                "match_type": "exact",
            }

    for entry in entries:
        entry_case = _clean(entry.get("case_number"))
        entry_normalized = normalize_case(entry_case)
        if tracked_normalized and entry_normalized and tracked_normalized in entry_normalized:
            return {
                "case_number": entry_case or tracked_case,
                "status": "LISTED",
                "court_no": _clean(entry.get("court_no") or entry.get("court_number")),
                "date": _clean(entry.get("listing_date") or entry.get("hearing_date") or checked_date),
                "judge": _clean(entry.get("judge")),
                "confidence": "MEDIUM",
                "match_type": "partial",
            }

    return {
        "case_number": tracked_case,
        "status": "NOT_LISTED",
        "checked_date": checked_date,
        "confidence": "LOW",
        "match_type": "none",
    }


def lookup_case_listings(
    tracked_cases: list[str],
    court_id: str | int,
    hearing_date: str,
    court_label: str | None = None,
) -> dict[str, Any]:
    tracked_cases = [case for case in tracked_cases if _clean(case)]
    try:
        payload = fetch_ecourts_cases(court_id, hearing_date)
        normalized = normalize_ecourts_response(payload, hearing_date, court_label=court_label)
        entries = normalized["entries"]
        results = [match_case_listing(case, entries, checked_date=hearing_date) for case in tracked_cases]
        matches_found = sum(1 for result in results if result.get("status") == "LISTED")
        summary = {
            "api_status": "success",
            "cases_checked": len(tracked_cases),
            "matches_found": matches_found,
            "entries": entries,
            "results": results,
            "court_id": court_id,
            "checked_date": hearing_date,
        }
        _log_api_event(
            "lookup_success",
            {
                "api_status": "success",
                "court_id": court_id,
                "date": hearing_date,
                "cases_checked": len(tracked_cases),
                "matches_found": matches_found,
            },
        )
        return summary
    except Exception as exc:
        _log_api_event(
            "lookup_failure",
            {
                "api_status": "failure",
                "court_id": court_id,
                "date": hearing_date,
                "cases_checked": len(tracked_cases),
                "matches_found": 0,
                "error": str(exc),
            },
        )
        return {
            "api_status": "failure",
            "cases_checked": len(tracked_cases),
            "matches_found": 0,
            "entries": [],
            "results": [
                {
                    "case_number": case,
                    "status": "NOT_LISTED",
                    "checked_date": hearing_date,
                    "confidence": "LOW",
                }
                for case in tracked_cases
            ],
            "court_id": court_id,
            "checked_date": hearing_date,
            "error": str(exc),
        }


def build_case_status_message(case_number: str, lookup_result: dict[str, Any]) -> str:
    if lookup_result.get("api_status") == "failure":
        return API_UNAVAILABLE_MESSAGE

    result = lookup_result.get("result") or lookup_result
    if result.get("status") == "LISTED":
        listed_date = _format_date(result.get("date") or lookup_result.get("checked_date"))
        court_no = _clean(result.get("court_no") or result.get("court_number")) or "Unknown"
        judge = _clean(result.get("judge"))
        message = f"{case_number} is listed on {listed_date} in Court No {court_no}"
        if judge:
            message = f"{message} before {judge}"
        return message

    checked_date = _format_date(result.get("checked_date") or lookup_result.get("checked_date"))
    return f"{case_number} is not listed on {checked_date}"
