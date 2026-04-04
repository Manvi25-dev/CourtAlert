import logging
import re
from datetime import date
from typing import Any

from alert_service import build_alert_payload
from case_parser import normalize_case_id
from models import (
    get_all_active_cases,
    get_all_active_case_rows,
    get_all_active_cnrs,
    save_hearing, 
    get_users_tracking_case, 
    get_users_tracking_cnr,
    create_alert,
    create_alert_with_cnr,
    get_db_connection,
)
from cnr_service import extract_cnr

logger = logging.getLogger(__name__)


CASE_PATTERN = re.compile(r"\b([A-Z]+)[\s/\-]+(\d+)[\s/\-]+(\d{4})\b")


def extract_case_number(text: str) -> str | None:
    """Extract first valid case pattern and return normalized TYPE/NUMBER/YEAR."""
    if not text:
        return None
    match = CASE_PATTERN.search(text.upper())
    if not match:
        return None
    case_type, number, year = match.groups()
    return f"{case_type}/{int(number)}/{year}"


def normalize_case_number(value: str | None) -> str | None:
    """Normalize raw case text into canonical TYPE/NUMBER/YEAR format."""
    if not value:
        return None

    direct = extract_case_number(value)
    if direct:
        return direct

    slash_match = re.search(r"\b([A-Z\.]+)/(\d+)/(\d{4})\b", str(value).upper())
    if slash_match:
        case_type, number, year = slash_match.groups()
        case_type = re.sub(r"[^A-Z0-9]", "", case_type)
        return f"{case_type}/{int(number)}/{year}"

    # Backward-compatibility with prior canonical format TYPE-NUMBER-YEAR.
    normalized_id = normalize_case_id(value)
    if not normalized_id:
        return None

    try:
        case_type, number, year = normalized_id.split("-", 2)
    except ValueError:
        return None

    return f"{case_type}/{int(number)}/{year}"


def normalize_parsed_entry(entry: dict[str, Any], fallback_date: str | None = None) -> dict[str, Any] | None:
    raw_case = entry.get("case_number") or entry.get("case_no") or entry.get("raw")
    normalized_case = normalize_case_number(raw_case)
    cnr = extract_cnr(str(entry.get("cnr") or entry.get("raw") or ""))
    if not normalized_case and not cnr:
        return None

    return {
        "cnr": cnr,
        "case_number": normalized_case,
        "title": entry.get("title") or entry.get("raw") or "Unknown Title",
        "court": entry.get("court") or entry.get("bench") or "Unknown Court",
        "court_number": entry.get("court_number") or entry.get("item") or entry.get("item_number") or "",
        "judge": entry.get("judge") or "Unknown Judge",
        "status": entry.get("status") or entry.get("list_type") or "Listed",
        "hearing_date": entry.get("hearing_date") or fallback_date,
        "district": entry.get("district") or "",
        "source": entry.get("source"),
        "advocate": entry.get("advocate") or "Unknown Advocate",
        "item": entry.get("item") or entry.get("item_number") or "Unknown",
        "raw": entry.get("raw") or str(raw_case),
    }

def match_cases_and_alert(parsed_entries: list[dict], source_pdf: str, hearing_date: str | None = None):
    """
    Compare parsed cause list entries against tracked cases.
    If match found:
      1. Save hearing details
      2. Create alerts for all users tracking that case
    """
    # Get all active tracked cases (normalized IDs)
    active_rows = get_all_active_case_rows()
    tracked_cnrs = set(get_all_active_cnrs())

    tracked_case_lookup: dict[tuple[str, str], set[str]] = {}
    for row in active_rows:
        canonical = normalize_case_number(row.get("normalized_case_id") or row.get("case_number"))
        if not canonical:
            continue
        court = (row.get("court") or "").strip().lower()
        tracked_case_lookup.setdefault((canonical, court), set()).add(row.get("normalized_case_id") or canonical)
    
    if not tracked_case_lookup and not tracked_cnrs:
        logger.info("No active cases to track.")
        return []

    logger.info(
        "Matching against %s tracked cases and %s CNRs...",
        len(tracked_case_lookup),
        len(tracked_cnrs),
    )
    tracked_case_candidates = sorted({case_id for case_id, _court in tracked_case_lookup.keys()})
    
    match_count = 0
    
    generated_alerts: list[dict[str, Any]] = []

    for entry in parsed_entries:
        parsed = normalize_parsed_entry(entry, hearing_date)
        if not parsed:
            continue

        canonical_case = parsed.get("case_number")
        parsed_cnr = parsed.get("cnr")
        parsed_court = (parsed.get("court") or "").strip().lower()

        matched_tracking_ids: list[tuple[str, list[tuple[str, int]]]] = []

        logger.info(
            "Parsed case=%s cnr=%s compared against tracked_cases=%s",
            canonical_case,
            parsed_cnr,
            tracked_case_candidates,
        )

        # 1) CNR-first matching.
        if parsed_cnr and parsed_cnr in tracked_cnrs:
            users = get_users_tracking_cnr(parsed_cnr)
            if users:
                matched_tracking_ids.append(("cnr", users))

        # 2) Fallback to case number + court.
        if not matched_tracking_ids and canonical_case:
            for key in ((canonical_case, parsed_court), (canonical_case, "")):
                if key not in tracked_case_lookup:
                    continue
                collected_users: list[tuple[str, int]] = []
                for tracked_db_id in tracked_case_lookup[key]:
                    collected_users.extend(get_users_tracking_case(tracked_db_id))
                if collected_users:
                    matched_tracking_ids.append(("case", collected_users))
                    break

        if matched_tracking_ids:
            logger.info("MATCH FOUND: cnr=%s case=%s", parsed_cnr, canonical_case)
            match_count += 1
            
            # 1. Save Hearing
            # Use provided hearing_date (e.g. from Advance List) or fallback to today
            final_hearing_date = parsed["hearing_date"] if parsed["hearing_date"] else date.today().isoformat()
            
            hearing_id = save_hearing(
                case_id=canonical_case or parsed_cnr or "UNKNOWN",
                date=final_hearing_date,
                court=parsed["court"],
                item=parsed["item"],
                raw=parsed["raw"],
                source=source_pdf,
                title=parsed["title"],
                advocate=parsed["advocate"],
                cnr=parsed_cnr,
            )
            
            # 2. Create Alerts
            seen_user_case: set[tuple[str, int]] = set()
            for mode, users in matched_tracking_ids:
                for user_phone, case_db_id in users:
                    key = (user_phone, case_db_id)
                    if key in seen_user_case:
                        continue
                    seen_user_case.add(key)
                    alert_payload = build_alert_payload(
                        case_number=canonical_case or "",
                        cnr=parsed_cnr,
                        title=parsed["title"],
                        court=parsed["court"],
                        court_number=parsed.get("court_number"),
                        judge=parsed.get("judge"),
                        status=parsed.get("status"),
                        hearing_date=final_hearing_date,
                        district=parsed.get("district"),
                        source=parsed.get("source"),
                        advocate=parsed.get("advocate"),
                        user_phone=user_phone,
                        source_pdf=source_pdf,
                    )
                    if mode == "cnr":
                        created = create_alert_with_cnr(
                            user_phone,
                            case_db_id,
                            hearing_id,
                            cnr=parsed_cnr,
                            hearing_date=final_hearing_date,
                            court=parsed["court"],
                            source=source_pdf,
                            alert_payload=alert_payload,
                        )
                    else:
                        created = create_alert(user_phone, case_db_id, hearing_id, alert_payload=alert_payload)
                    if not created:
                        logger.info(
                            "Alert skipped as duplicate",
                            extra={"cnr": parsed_cnr, "case_number": canonical_case, "hearing_date": final_hearing_date},
                        )
                        continue
                    generated_alerts.append(alert_payload)
                    logger.info(
                        "Alert created",
                        extra={"cnr": parsed_cnr, "case_number": canonical_case, "hearing_date": final_hearing_date},
                    )
        else:
            logger.info("NO MATCH for parsed case: %s", canonical_case or parsed_cnr or "UNKNOWN")

    logger.info("Matching complete. Found %s matches.", match_count)
    return generated_alerts


def match_case_number(tracked_case: str, parsed_case: str) -> bool:
    """Legacy helper: compare canonicalized case IDs."""
    tracked_norm = normalize_case_number(tracked_case)
    parsed_norm = normalize_case_number(parsed_case)
    return bool(tracked_norm and parsed_norm and tracked_norm == parsed_norm)


def process_matches_and_generate_alerts(matches: list[tuple[dict, dict]]) -> list[dict]:
    """Legacy helper used by older tests/scripts to persist and return alerts."""
    generated: list[dict] = []
    conn = get_db_connection()
    try:
        for tracked_case, parsed_entry in matches:
            user_id = tracked_case.get("user_id") or tracked_case.get("user_phone")
            case_number = normalize_case_number(
                tracked_case.get("case_number") or parsed_entry.get("case_number")
            )
            if not user_id or not case_number:
                continue

            hearing_date = parsed_entry.get("hearing_date") or date.today().isoformat()
            alert = build_alert_payload(
                case_number=case_number,
                cnr=parsed_entry.get("cnr"),
                title=parsed_entry.get("title"),
                court=parsed_entry.get("bench") or parsed_entry.get("court"),
                court_number=parsed_entry.get("court_number") or parsed_entry.get("item_number"),
                judge=parsed_entry.get("judge"),
                status=parsed_entry.get("status") or parsed_entry.get("list_type"),
                hearing_date=hearing_date,
                district=parsed_entry.get("district"),
                source=parsed_entry.get("source"),
                advocate=parsed_entry.get("advocate"),
                user_phone=str(user_id),
            )
            cursor = conn.execute(
                "INSERT OR IGNORE INTO alerts (user_phone, case_number, cnr, title, court, court_number, judge, status, hearing_date, district, source, priority, message, advocate, delivery_status, sent_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(user_id),
                    alert["case_number"],
                    alert.get("cnr"),
                    alert.get("title"),
                    alert.get("court"),
                    alert.get("court_number"),
                    alert.get("judge"),
                    alert.get("status"),
                    alert.get("hearing_date"),
                    alert.get("district"),
                    alert.get("source"),
                    alert.get("priority"),
                    alert.get("message"),
                    alert.get("advocate"),
                    "sent",
                    hearing_date,
                ),
            )
            if cursor.rowcount > 0:
                alert["user_id"] = user_id
                alert["alert_type"] = parsed_entry.get("match_type", "PRIMARY_LISTING")
                generated.append(alert)
        conn.commit()
    finally:
        conn.close()

    return generated


def run_matching_pipeline(parsed_entries: list[dict]) -> list[dict]:
    """Legacy pipeline entry for demo/orchestrator compatibility."""
    active_cases = get_all_active_cases()
    tracked_lookup: dict[str, set[str]] = {}
    for tracked_id in active_cases:
        canonical = normalize_case_number(tracked_id)
        if canonical:
            tracked_lookup.setdefault(canonical, set()).add(tracked_id)

    if not tracked_lookup:
        return []

    matches: list[tuple[dict, dict]] = []
    for entry in parsed_entries:
        candidate = entry.get("case_number") or entry.get("case_no")
        if not candidate:
            continue

        normalized = normalize_case_number(candidate)
        if not normalized or normalized not in tracked_lookup:
            continue

        for tracked_db_id in tracked_lookup[normalized]:
            users = get_users_tracking_case(tracked_db_id)
            for user_phone, case_id in users:
                matches.append(
                    (
                        {"id": case_id, "user_id": user_phone, "case_number": normalized},
                        {
                            "case_number": normalized,
                            "hearing_date": entry.get("hearing_date"),
                            "bench": entry.get("bench") or entry.get("court") or "Unknown Bench",
                            "judge": entry.get("judge") or entry.get("court") or "Unknown Judge",
                            "list_type": entry.get("list_type", "Unknown"),
                            "item_number": entry.get("item_number") or entry.get("item", "Unknown"),
                            "match_type": entry.get("match_type", "PRIMARY_LISTING"),
                            "title": entry.get("title") or entry.get("raw"),
                        },
                    )
                )

    return process_matches_and_generate_alerts(matches)
