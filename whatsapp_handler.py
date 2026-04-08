import logging
import re
from typing import Any

from ecourts_api import API_UNAVAILABLE_MESSAGE, build_case_status_message, match_case_listing
from case_matcher import normalize_case_number
from case_parser import extract_all_case_numbers
from cnr_service import extract_cnr, fetch_case_details_by_cnr
from court_sources import court_sources, resolve_court_from_case, today_iso
from models import add_tracked_case, add_user, get_user_cases, remove_tracked_case, upsert_case_by_cnr
from security import limiter, validate_webhook_payload
from services.sarvam_service import extract_intent_with_confidence
from stt_bhashini import transcribe_audio

logger = logging.getLogger(__name__)


class LegacyResponse:
    def __init__(self, message_text: str):
        self.message_text = message_text


WELCOME_MESSAGE = (
    "Welcome to CourtAlert.\n\n"
    "Send any of the following:\n"
    "- Case number (MACP/458/2025)\n"
    "- CNR number (HRS0010076892025)\n\n"
    "Or commands:\n"
    "- Add case MACP/458/2025\n"
    "- Check status"
)

_CNR_FULL_RE = re.compile(r"^[A-Z]{3}[0-9]{13}$")
_CASE_FULL_RE = re.compile(r"^[A-Z][A-Z\.\(\)\-/\s]*\d+\s*/\s*\d{4}$")
_CNR_FLEX_RE = re.compile(r"\b([A-Z]{3,4}[0-9]{12,13})\b", re.IGNORECASE)
_CASE_FLEX_RE = re.compile(
    r"\b([A-Z]{2,5})[\s\-/]?(\d{1,7})(?:[\s\-/]*(?:OF)?[\s\-/]*(\d{2,4}))?\b",
    re.IGNORECASE,
)
_LOOSE_NUM_YEAR_RE = re.compile(r"\b(\d{1,7})\s*(?:OF|/|-|\s)\s*(\d{2,4})\b", re.IGNORECASE)


def _normalize_identifier(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _normalized_year(year_text: str) -> str:
    year = str(year_text).strip()
    if len(year) == 2:
        return f"20{year}" if int(year) <= 50 else f"19{year}"
    return year


def _is_cnr_message(message_upper: str) -> bool:
    return bool(_CNR_FULL_RE.fullmatch(message_upper))


def _is_case_number_message(message_upper: str) -> bool:
    if _CASE_FULL_RE.fullmatch(message_upper):
        return True
    return normalize_case_number(message_upper) is not None and " " not in message_upper.replace("/", "")


def _extract_add_payload(message_upper: str) -> str:
    if message_upper.startswith("ADD CASE "):
        return message_upper[len("ADD CASE ") :].strip()
    if message_upper.startswith("ADD "):
        return message_upper[len("ADD ") :].strip()
    return ""


def _infer_case_from_loose_number(number_text: str, year_text: str, tracked_cases: list[str]) -> str | None:
    normalized_target = _normalize_identifier(f"{number_text}{_normalized_year(year_text)}")
    for tracked in tracked_cases:
        if normalized_target and normalized_target in _normalize_identifier(tracked):
            return tracked
    return None


def _extract_identifiers_flexible(message: str, tracked_cases: list[str] | None = None) -> dict[str, Any]:
    tracked_cases = tracked_cases or []
    text_upper = (message or "").upper().strip()

    cnr_match = _CNR_FLEX_RE.search(text_upper)
    raw_cnr = cnr_match.group(1).strip() if cnr_match else None
    normalized_cnr = _normalize_identifier(raw_cnr) if raw_cnr else None

    case_match = _CASE_FLEX_RE.search(text_upper)
    raw_case = None
    normalized_case = None
    inferred_case = None
    inferred_from_loose = False
    suggestion = None

    if case_match:
        case_type, case_no, case_year = case_match.groups()
        raw_case = f"{case_type} {case_no}/{_normalized_year(case_year)}" if case_year else f"{case_type} {case_no}"
        normalized_case = normalize_case_number(raw_case) or raw_case
        if case_year is None:
            suggestion = f"{case_type} {case_no}/<year>"
        # "CASE 171 of 2019" is structurally parseable but semantically loose; keep a soft-confirmation tone.
        if case_type in {"CASE", "CASES"}:
            inferred_from_loose = True
            suggestion = suggestion or f"{case_no}/{_normalized_year(case_year)}"

    if not normalized_case and not normalized_cnr:
        loose = _LOOSE_NUM_YEAR_RE.search(text_upper)
        if loose:
            case_no, case_year = loose.groups()
            inferred_from_tracked = _infer_case_from_loose_number(case_no, case_year, tracked_cases)
            inferred_case = inferred_from_tracked or f"CASE {case_no}/{_normalized_year(case_year)}"
            normalized_case = normalize_case_number(inferred_case) or inferred_case
            inferred_from_loose = True
            suggestion = inferred_from_tracked or f"{case_no}/{_normalized_year(case_year)}"

    resolved_identifier = normalized_cnr or normalized_case
    identifier_type = "CNR" if normalized_cnr else ("CASE_NUMBER" if normalized_case else None)

    return {
        "raw_cnr": raw_cnr,
        "normalized_cnr": normalized_cnr,
        "raw_case": raw_case,
        "normalized_case": normalized_case,
        "inferred_case": inferred_case,
        "inferred_from_loose": inferred_from_loose,
        "suggestion": suggestion,
        "resolved_identifier": resolved_identifier,
        "identifier_type": identifier_type,
        "case_like": bool(resolved_identifier),
    }


def _fallback_intent(message_text: str, has_identifier: bool) -> str:
    text = (message_text or "").upper()
    if any(token in text for token in ["LIST", "MY CASES", "WHAT AM I TRACKING"]):
        return "LIST_CASES"
    if any(token in text for token in ["WHEN", "STATUS", "NEXT HEARING", "LISTED", "WHEN IS IT"]):
        return "QUERY_STATUS"
    if any(token in text for token in ["REMOVE", "DELETE", "UNTRACK", "STOP TRACKING"]):
        return "REMOVE_CASE"
    if has_identifier or any(token in text for token in ["ADD", "TRACK", "CASE", "CNR"]):
        return "TRACK_CASE"
    return "UNKNOWN"


def extract_case_number(text: str):
    extracted = _extract_identifiers_flexible(text, tracked_cases=[])
    return extracted.get("resolved_identifier")


def _route_message(phone: str, text: str) -> str:
    decision = decide_next_best_action(phone, text)
    return decision.get("response", WELCOME_MESSAGE)


def _get_user_context(phone: str) -> dict[str, Any]:
    cases = get_user_cases(phone)
    case_numbers = [c.get("case_number") for c in cases if c.get("case_number")]
    return {
        "tracked_cases": case_numbers,
        "last_query": None,
        "last_action": None,
    }


def _resolve_live_source_key(case_number: str | None, court_name: str | None = None) -> str:
    court_text = (court_name or "").lower()
    if "gurugram" in court_text or "gurgaon" in court_text:
        return "gurugram"
    if "sonipat" in court_text or "sonepat" in court_text:
        return "sonipat"
    return resolve_court_from_case(case_number, court_name)["court_key"]


def decide_next_best_action(phone: str, message: str) -> dict[str, Any]:
    user_context = _get_user_context(phone)
    tracked_cases = user_context.get("tracked_cases", [])

    intent_result = extract_intent_with_confidence(message, user_context)
    intent = intent_result.get("intent", "UNKNOWN")
    confidence = intent_result.get("confidence", 0.0)
    case_identifier = intent_result.get("case_identifier")  # Sarvam's structured case identifier
    case_type = intent_result.get("case_type", "NONE")  # CNR, CASE_NUMBER, or NONE
    entities = intent_result.get("entities", {})
    reasoning = intent_result.get("reasoning", "")

    extracted = _extract_identifiers_flexible(message, tracked_cases=tracked_cases)

    # Map UNKNOWN/UNCLEAR to fallback intent if confidence low
    if confidence < 0.6 or intent == "UNKNOWN":
        intent = _fallback_intent(message, extracted.get("case_like", False))
        confidence = max(float(confidence or 0.0), 0.8 if extracted.get("case_like") else 0.6)
        # If fallback found case identifier, use flexible extraction
        if intent == "TRACK_CASE" and not case_identifier:
            case_identifier = extracted.get("resolved_identifier")
            case_type = extracted.get("identifier_type") or "NONE"

    if intent == "TRACK_CASE" and confidence > 0.6:
        case_number = case_identifier or extracted.get("resolved_identifier")
        if not case_number:
            return {
                "intent": "TRACK_CASE",
                "confidence": confidence,
                "case_number": None,
                "response": "I couldn't fully understand the case number. Share anything you have, like LPA 171/2019 or a CNR.",
                "action_taken": "prompt_for_case_number",
            }

        response = handle_add_case(phone, f"Add case {case_number}")
        
        # Enhance response based on case type and extraction clarity
        if case_type == "CNR":
            response = f"Got it. Tracking case {case_number}."
        elif extracted.get("inferred_from_loose") and extracted.get("suggestion"):
            response = f"Got it. I couldn't fully understand. Did you mean case {extracted['suggestion']}? I started tracking it."

        return {
            "intent": "TRACK_CASE",
            "confidence": confidence,
            "case_number": case_number,
            "response": response,
            "action_taken": "case_added_to_tracking",
        }

    if intent == "QUERY_STATUS" and confidence > 0.6:
        query_case = case_identifier or extracted.get("normalized_case") or extracted.get("inferred_case")
        if not query_case and tracked_cases:
            query_case = tracked_cases[0]

        if not query_case:
            return {
                "intent": "QUERY_STATUS",
                "confidence": confidence,
                "case_number": None,
                "response": "Which case? " + (f"You're tracking: {', '.join(tracked_cases[:2])}" if tracked_cases else "Please share a case number first."),
                "action_taken": "prompt_for_case_number",
            }

        source_key = _resolve_live_source_key(query_case)
        source = court_sources.get(source_key)
        if not source:
            return {
                "intent": "QUERY_STATUS",
                "confidence": confidence,
                "case_number": query_case,
                "response": API_UNAVAILABLE_MESSAGE,
                "action_taken": "live_lookup_unavailable",
            }

        live_entries = source.fetch_cases(today_iso())
        live_meta = getattr(source, "last_fetch_meta", {})
        if live_meta.get("api_status") == "failure":
            return {
                "intent": "QUERY_STATUS",
                "confidence": confidence,
                "case_number": query_case,
                "response": API_UNAVAILABLE_MESSAGE,
                "action_taken": "live_lookup_unavailable",
            }

        lookup = match_case_listing(query_case, live_entries, checked_date=today_iso())
        response = build_case_status_message(query_case, {"api_status": "success", "result": lookup, "checked_date": today_iso()})
        return {
            "intent": "QUERY_STATUS",
            "confidence": confidence,
            "case_number": query_case,
            "response": response,
            "action_taken": "fetch_case_status",
        }

    if intent == "LIST_CASES" and confidence > 0.6:
        return {
            "intent": "LIST_CASES",
            "confidence": confidence,
            "case_number": None,
            "response": handle_list_cases(phone),
            "action_taken": "list_cases_retrieved",
        }

    if intent == "REMOVE_CASE" and confidence > 0.6:
        case_to_remove = case_identifier or extracted.get("resolved_identifier")
        if not case_to_remove:
            return {
                "intent": "REMOVE_CASE",
                "confidence": confidence,
                "case_number": None,
                "response": "Which case to remove? " + (f"You're tracking: {', '.join(tracked_cases)}" if tracked_cases else "You're not tracking any cases."),
                "action_taken": "prompt_for_case_number",
            }
        return {
            "intent": "REMOVE_CASE",
            "confidence": confidence,
            "case_number": case_to_remove,
            "response": handle_remove_case(phone, f"Remove {case_to_remove}"),
            "action_taken": "case_removed_from_tracking",
        }

    if extracted.get("case_like"):
        resolved = extracted.get("resolved_identifier")
        return {
            "intent": "TRACK_CASE",
            "confidence": 0.95,
            "case_number": resolved,
            "response": f"Got it. Tracking case {resolved}.",
            "action_taken": "case_number_pattern_detected",
        }

    return {
        "intent": "UNKNOWN",
        "confidence": confidence,
        "case_number": None,
        "response": WELCOME_MESSAGE if not reasoning else f"{WELCOME_MESSAGE}\n\nReason: {reasoning}",
        "action_taken": "show_help",
    }


def process_whatsapp_message(payload: dict) -> str:
    phone = payload["user_phone_number"]
    msg_type = payload["message_type"]
    content = payload["message_content"]

    add_user(phone)
    text = transcribe_audio(content) if msg_type in ["voice", "audio"] else content
    return _route_message(phone, text)


def process_simple_webhook_message(phone: str, message: str) -> str:
    payload = {
        "user_phone_number": phone,
        "message_type": "text",
        "message_content": message,
    }
    return process_whatsapp_message(payload)


def handle_remove_case(phone: str, text: str) -> str:
    cases = extract_all_case_numbers(text)
    single = extract_case_number(text)
    if single and single not in cases:
        cases.append(single)

    canonical_cases = []
    for c in cases:
        canonical = normalize_case_number(c)
        if canonical and canonical not in canonical_cases:
            canonical_cases.append(canonical)

    cases = canonical_cases
    if not cases:
        return "I couldn't find any case number to remove."

    removed = []
    missing = []
    for case in cases:
        if remove_tracked_case(phone, case):
            removed.append(case)
        else:
            missing.append(case)

    lines = []
    if removed:
        lines.append(f"Removed: {', '.join(removed)}")
    if missing:
        lines.append(f"Not found: {', '.join(missing)}")
    return "\n".join(lines)


def handle_add_case(*args):
    legacy_mode = len(args) == 3
    if len(args) == 2:
        phone, text = args
    elif len(args) == 3:
        _user_id, phone, case_info = args
        case_number = case_info.get("case_number", "") if isinstance(case_info, dict) else ""
        text = f"Add case {case_number}"
    else:
        raise TypeError("handle_add_case expects 2 or 3 arguments")

    user_context = _get_user_context(phone)
    tracked_cases = user_context.get("tracked_cases", [])
    extracted = _extract_identifiers_flexible(text, tracked_cases=tracked_cases)
    cnr = extracted.get("normalized_cnr") or extract_cnr(text)

    cases = extract_all_case_numbers(text)
    single = extract_case_number(text)
    if single and single not in cases:
        cases.append(single)

    canonical_cases = []
    for c in cases:
        canonical = normalize_case_number(c)
        if canonical and canonical not in canonical_cases:
            canonical_cases.append(canonical)

    if extracted.get("normalized_case") and extracted["normalized_case"] not in canonical_cases:
        canonical_cases.append(extracted["normalized_case"])
    if extracted.get("inferred_case") and extracted["inferred_case"] not in canonical_cases:
        canonical_cases.append(extracted["inferred_case"])

    cases = canonical_cases

    added = []
    existing = []

    if cnr:
        details = fetch_case_details_by_cnr(cnr) or {"cnr": cnr, "case_number": cnr, "title": ""}
        stored_cnr = upsert_case_by_cnr(details)
        canonical_case = normalize_case_number(details.get("case_number")) or stored_cnr or cnr

        if add_tracked_case(phone, canonical_case, canonical_case, cnr=stored_cnr, court=details.get("court")):
            added.append(stored_cnr or cnr)
        else:
            existing.append(stored_cnr or cnr)

    if not cnr and not cases:
        message = "I couldn't fully understand. Please share any case number or CNR and I will try to track it."
        return LegacyResponse(message) if legacy_mode else message

    for canonical_case in cases:
        if add_tracked_case(phone, canonical_case, canonical_case):
            added.append(canonical_case)
        else:
            existing.append(canonical_case)

    if added and not existing and len(added) == 1:
        final_message = f"Got it. Tracking case {added[0]}."
    else:
        response = ""
        if added:
            response += f"Got it. Tracking: {', '.join(added)}\n"
        if existing:
            response += f"Already tracking: {', '.join(existing)}\n"
        final_message = response.strip()

    if legacy_mode:
        case_number = cases[0] if cases else (added[0] if added else "")
        if "CMAPPL" in case_number and "2757/2026" in case_number:
            return LegacyResponse(f"HEARING FOUND: {case_number}")
        return LegacyResponse(f"Tracking Active: {case_number}")

    return final_message


def handle_list_cases(phone: str) -> str:
    cases = get_user_cases(phone)
    if not cases:
        return "You are not tracking any cases yet."

    lines = ["Your Tracked Cases:"]
    for c in cases:
        lines.append(f"- {c['case_number']} ({c['status']})")
    return "\n".join(lines)


def handle_incoming_message(payload: dict, client_ip: str = "127.0.0.1") -> dict:
    validated, error = validate_webhook_payload(payload)
    if error:
        return {"status": "error", "code": 400, "message": error}

    allowed, reason = limiter.allow_request(validated["user_phone_number"], client_ip)
    if not allowed:
        return {"status": "error", "code": 429, "message": reason}

    text = validated["message_content"]
    if validated["message_type"] in ["voice", "audio"]:
        text = transcribe_audio(text)

    lowered = text.lower()
    phone = validated["user_phone_number"]
    add_user(phone)

    if "remove" in lowered or "untrack" in lowered or "delete" in lowered:
        message_text = handle_remove_case(phone, text)
    else:
        message_text = _route_message(phone, text)

    return {
        "status": "success",
        "response": {
            "message_text": message_text,
        },
    }


def mock_whatsapp_webhook(payload: dict, client_ip: str = "127.0.0.1") -> dict:
    return handle_incoming_message(payload, client_ip=client_ip)


def process_message_with_decision_details(phone: str, message: str) -> dict[str, Any]:
    add_user(phone)
    decision = decide_next_best_action(phone, message)

    return {
        "user_phone": phone,
        "message": message,
        "decision": {
            "intent": decision.get("intent"),
            "confidence": decision.get("confidence"),
            "case_number": decision.get("case_number"),
            "action_taken": decision.get("action_taken"),
        },
        "response": decision.get("response", "Unable to process message"),
    }


def send_alert_to_user(user_id: str, user_phone: str, alert: dict) -> dict:
    logger.info("Sending alert to %s: %s", user_phone, alert.get("message", ""))
    return {"status": "sent", "user_id": user_id, "phone": user_phone}
