"""CourtAlert Orchestrator
Unified user-message pipeline and legacy scheduled orchestration helpers.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from uuid import uuid4

from alert_service import build_alert_payload
from ecourts_api import API_UNAVAILABLE_MESSAGE, build_case_status_message, match_case_listing
from case_matcher import normalize_case_number as matcher_normalize_case_number
from case_matcher import run_matching_pipeline
from case_parser import normalize_case_id, parse_case_number
from cause_list_fetcher import fetch_and_parse_cause_lists
from court_sources import court_sources, resolve_court_from_case, today_iso
from models import (
    add_tracked_case,
    add_user,
    get_connection,
    get_user_by_phone,
    get_user_cases,
)
from services.ai_parser import ai_parse_message
from services.parser import parse_message
from services.whatsapp_service import send_whatsapp

logger = logging.getLogger(__name__)


def _normalize_case_for_pipeline(candidate: str | None) -> str | None:
    if not candidate:
        return None

    parsed_display = parse_case_number(candidate)
    if not parsed_display:
        parsed_display = parse_case_number(str(candidate).upper())
    if not parsed_display:
        return None

    normalized = matcher_normalize_case_number(parsed_display)
    if normalized:
        return normalized

    normalized_id = normalize_case_id(parsed_display)
    if not normalized_id:
        return None

    try:
        case_type, number, year = normalized_id.split("-", 2)
    except ValueError:
        return None
    return f"{case_type}/{int(number)}/{year}"


def _fetch_entries_for_court(court_key: str) -> tuple[list[dict], str]:
    if court_key == "delhi_hc":
        entries = fetch_and_parse_cause_lists()
        return entries, "cause_list_fetcher.fetch_and_parse_cause_lists"

    if court_key in {"gurugram", "sonipat"}:
        source = court_sources.get(court_key)
        entries = source.fetch_cases(today_iso()) if source else []
        return entries, f"court_sources.court_sources['{court_key}'].fetch_cases"

    entries = fetch_and_parse_cause_lists()
    return entries, "cause_list_fetcher.fetch_and_parse_cause_lists"


def _find_matching_entry(entries: list[dict], case_number: str) -> dict | None:
    for entry in entries:
        candidate = entry.get("case_number") or entry.get("case_no") or entry.get("raw")
        normalized_candidate = matcher_normalize_case_number(str(candidate)) if candidate else None
        if normalized_candidate and normalized_candidate == case_number:
            return entry
    return None


def _build_confirmation_message(case_number: str, court_name: str, fetcher_name: str, added: bool) -> str:
    tracking_line = "registered for alerts" if added else "already registered for alerts"
    return (
        "Case pipeline completed.\n"
        f"Case: {case_number}\n"
        f"Court: {court_name}\n"
        f"Fetcher: {fetcher_name}\n"
        f"Tracking: {tracking_line}"
    )


def _safe_send_whatsapp(user_number: str, reply_text: str, request_id: str) -> str | None:
    try:
        sid = send_whatsapp(user_number, reply_text)
        logger.info("[req:%s] response sent: sid=%s", request_id, sid)
        return sid
    except Exception as exc:
        logger.error("[req:%s] whatsapp send failed: %s", request_id, exc)
        return None


def _resolve_live_source_key(case_number: str | None, court_name: str | None = None) -> str:
    court_text = (court_name or "").lower()
    if "gurugram" in court_text or "gurgaon" in court_text:
        return "gurugram"
    if "sonipat" in court_text or "sonepat" in court_text:
        return "sonipat"
    return resolve_court_from_case(case_number, court_name)["court_key"]


def process_user_message(message: str, user_number: str, request_id: str | None = None) -> dict:
    request_id = request_id or uuid4().hex[:12]
    logger.info("[req:%s] message received: user=%s text=%s", request_id, user_number, message)

    parsed_result = parse_message(message)
    logger.info("[req:%s] parsed result: %s", request_id, parsed_result)

    intent = parsed_result.get("intent", "unknown")
    parsed_case = parsed_result.get("case_number")

    if intent == "unknown" or not parsed_case:
        ai_result = ai_parse_message(message)
        logger.info("[req:%s] AI fallback parsed result: %s", request_id, ai_result)
        if ai_result.get("case_number"):
            parsed_case = ai_result.get("case_number")
        if intent == "unknown":
            intent = ai_result.get("intent", "unknown")

    matched_case = _normalize_case_for_pipeline(parsed_case or message)
    logger.info("[req:%s] matched case: %s", request_id, matched_case)

    if intent == "QUERY_STATUS":
        user_cases = get_user_cases(user_number)
        tracked_row = None
        tracked_case = matched_case

        if tracked_case:
            for row in user_cases:
                row_case = _normalize_case_for_pipeline(row.get("case_number") or row.get("normalized_case_id"))
                if row_case == tracked_case:
                    tracked_row = row
                    break
        elif user_cases:
            tracked_row = user_cases[0]
            tracked_case = _normalize_case_for_pipeline(tracked_row.get("case_number") or tracked_row.get("normalized_case_id"))

        if not tracked_case:
            reply = "Please share the case number you want me to check."
            logger.info("[req:%s] response sent: %s", request_id, reply)
            send_sid = _safe_send_whatsapp(user_number, reply, request_id)
            return {
                "request_id": request_id,
                "status": "missing_case",
                "response_text": reply,
                "whatsapp_sid": send_sid,
            }

        source_key = _resolve_live_source_key(tracked_case, (tracked_row or {}).get("court"))
        source = court_sources.get(source_key)
        if not source:
            reply = API_UNAVAILABLE_MESSAGE
        else:
            live_entries = source.fetch_cases(today_iso())
            live_meta = getattr(source, "last_fetch_meta", {})
            if live_meta.get("api_status") == "failure":
                reply = API_UNAVAILABLE_MESSAGE
            else:
                listing = match_case_listing(tracked_case, live_entries, checked_date=today_iso())
                reply = build_case_status_message(tracked_case, {"api_status": "success", "result": listing, "checked_date": today_iso()})

        logger.info("[req:%s] response sent: %s", request_id, reply)
        send_sid = _safe_send_whatsapp(user_number, reply, request_id)
        return {
            "request_id": request_id,
            "status": "success" if reply != API_UNAVAILABLE_MESSAGE else "api_unavailable",
            "intent": intent,
            "case_number": tracked_case,
            "response_text": reply,
            "whatsapp_sid": send_sid,
        }

    if not matched_case:
        reply = "Case number is invalid or incomplete. Example: add case CS(OS) 3336/2011"
        logger.info("[req:%s] response sent: %s", request_id, reply)
        send_sid = _safe_send_whatsapp(user_number, reply, request_id)
        return {
            "request_id": request_id,
            "status": "invalid_case",
            "response_text": reply,
            "whatsapp_sid": send_sid,
        }

    court_resolution = resolve_court_from_case(matched_case, message)
    court_key = court_resolution["court_key"]
    court_name = court_resolution["court_name"]
    logger.info("[req:%s] court detected: key=%s name=%s", request_id, court_key, court_name)

    fetched_entries, fetcher_used = _fetch_entries_for_court(court_key)
    logger.info("[req:%s] fetcher used: %s entries=%d", request_id, fetcher_used, len(fetched_entries))

    matched_entry = _find_matching_entry(fetched_entries, matched_case)
    logger.info("[req:%s] fetched case match: %s", request_id, bool(matched_entry))

    add_user(user_number)
    added = add_tracked_case(
        phone_number=user_number,
        case_number=matched_case,
        normalized_id=matched_case,
        court=None,
    )
    logger.info("[req:%s] alert registered: added=%s", request_id, added)

    alert_payload = build_alert_payload(
        case_number=matched_case,
        title=(matched_entry or {}).get("title"),
        court=(matched_entry or {}).get("court") or court_name,
        hearing_date=(matched_entry or {}).get("hearing_date"),
        advocate=(matched_entry or {}).get("advocate"),
        source=fetcher_used,
    )

    response_text = _build_confirmation_message(matched_case, court_name, fetcher_used, added)
    if intent not in {"add_case", "track_case"}:
        response_text = f"Interpreted request as case tracking.\n\n{response_text}"

    response_text = f"{response_text}\n\n{alert_payload['message']}"

    send_sid = _safe_send_whatsapp(user_number, response_text, request_id)

    return {
        "request_id": request_id,
        "status": "success",
        "intent": intent,
        "parsed": parsed_result,
        "matched_case": matched_case,
        "court": court_resolution,
        "fetcher": fetcher_used,
        "entry_found": bool(matched_entry),
        "alert_registered": added,
        "response_text": response_text,
        "whatsapp_sid": send_sid,
    }


class CourtAlertOrchestrator:
    """Legacy orchestrator retained for scheduled ingestion compatibility."""

    def __init__(self):
        self.last_fetch_time = None
        self.last_parsed_entries = []

    def run_full_pipeline(self) -> dict:
        logger.info("Starting full ingestion pipeline")
        result = {
            "timestamp": datetime.now().isoformat(),
            "stages": {},
        }

        try:
            parsed_entries = fetch_and_parse_cause_lists()
            self.last_parsed_entries = parsed_entries
            result["stages"]["fetch_parse"] = {
                "status": "success",
                "entries_parsed": len(parsed_entries),
            }
        except Exception as exc:
            result["stages"]["fetch_parse"] = {"status": "error", "error": str(exc)}
            return result

        try:
            alerts = run_matching_pipeline(parsed_entries)
            result["stages"]["matching"] = {
                "status": "success",
                "alerts_generated": len(alerts),
            }
        except Exception as exc:
            result["stages"]["matching"] = {"status": "error", "error": str(exc)}
            return result

        result["stages"]["report"] = {
            "status": "success",
            "summary": {
                "entries_parsed": len(parsed_entries),
                "alerts_generated": result["stages"]["matching"].get("alerts_generated", 0),
            },
        }
        return result

    def get_system_status(self) -> dict:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM tracked_cases WHERE status = 'active'")
        tracked_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM hearings")
        hearing_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM alerts")
        alert_count = cursor.fetchone()[0]

        conn.close()

        return {
            "timestamp": datetime.now().isoformat(),
            "users": user_count,
            "tracked_cases": tracked_count,
            "hearings": hearing_count,
            "alerts_sent": alert_count,
            "last_pipeline_run": self.last_fetch_time,
        }


def run_scheduler(interval_seconds: int = 3600):
    orchestrator = CourtAlertOrchestrator()
    logger.info("Scheduler started with interval=%ss", interval_seconds)

    try:
        while True:
            result = orchestrator.run_full_pipeline()
            orchestrator.last_fetch_time = datetime.now().isoformat()
            logger.info("Scheduled execution result: %s", result)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    orchestrator = CourtAlertOrchestrator()
    result = orchestrator.run_full_pipeline()

    print("Pipeline Result:")
    print(json.dumps(result, indent=2))

    print("System Status:")
    status = orchestrator.get_system_status()
    print(json.dumps(status, indent=2))

    sample_user = get_user_by_phone("+910000000000")
    if sample_user:
        print(json.dumps(sample_user, indent=2))
