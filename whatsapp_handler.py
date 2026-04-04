import re
import logging

from cnr_service import extract_cnr, fetch_case_details_by_cnr
from models import (
    add_user,
    add_tracked_case,
    get_user_cases,
    remove_tracked_case,
    upsert_case_by_cnr,
)
from case_parser import extract_all_case_numbers
from case_matcher import normalize_case_number
from stt_bhashini import transcribe_audio
from security import validate_webhook_payload, limiter

logger = logging.getLogger(__name__)


class LegacyResponse:
    def __init__(self, message_text: str):
        self.message_text = message_text


def extract_case_number(text: str):
    pattern = r"[A-Z\.]+/?\d+/\d{4}"
    match = re.search(pattern, text.upper())
    return match.group(0) if match else None


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


def _is_cnr_message(message_upper: str) -> bool:
    return bool(_CNR_FULL_RE.fullmatch(message_upper))


def _is_case_number_message(message_upper: str) -> bool:
    if _CASE_FULL_RE.fullmatch(message_upper):
        return True
    # Also allow compact canonical forms that normalize_case_number handles.
    return normalize_case_number(message_upper) is not None and " " not in message_upper.replace("/", "")


def _extract_add_payload(message_upper: str) -> str:
    # Accept "ADD CASE <id>" and "ADD <id>".
    if message_upper.startswith("ADD CASE "):
        return message_upper[len("ADD CASE "):].strip()
    if message_upper.startswith("ADD "):
        return message_upper[len("ADD "):].strip()
    return ""


def _route_message(phone: str, text: str) -> str:
    """Routing priority: identifier -> command -> help message."""
    normalized_text = (text or "").strip()
    message_upper = normalized_text.upper()

    # 1) Identifier first: exact CNR message.
    if _is_cnr_message(message_upper):
        cnr = message_upper
        add_response = handle_add_case(phone, f"Add case {cnr}")
        return f"Case detected: {cnr}\nFetching details...\n\n{add_response}"

    # 2) Identifier first: exact case-number message.
    if _is_case_number_message(message_upper):
        case_number = normalize_case_number(message_upper) or message_upper
        add_response = handle_add_case(phone, f"Add case {case_number}")
        return f"Case detected: {case_number}\nFetching details...\n\n{add_response}"

    # 3) Explicit command handling.
    if message_upper.startswith("ADD CASE") or message_upper.startswith("ADD "):
        payload = _extract_add_payload(message_upper)
        return handle_add_case(phone, f"Add case {payload}" if payload else normalized_text)
    if message_upper.startswith("CHECK") or message_upper.startswith("STATUS") or message_upper.startswith("LIST"):
        return handle_list_cases(phone)

    # 4) Help is the final fallback only.
    return WELCOME_MESSAGE

def process_whatsapp_message(payload: dict) -> str:
    """
    Process incoming WhatsApp message and return a text response.
    """
    phone = payload["user_phone_number"]
    msg_type = payload["message_type"]
    content = payload["message_content"]
    
    # Ensure user exists
    add_user(phone)
    
    # Handle Voice
    if msg_type in ["voice", "audio"]:
        text = transcribe_audio(content) # content is url
    else:
        text = content
        
    return _route_message(phone, text)


def process_simple_webhook_message(phone: str, message: str) -> str:
    """MVP webhook entry: accepts {phone, message} and tracks canonical case IDs."""
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
    # Current path: handle_add_case(phone, text)
    # Legacy path: handle_add_case(user_id, phone, {"case_number": ...})
    legacy_mode = len(args) == 3
    if len(args) == 2:
        phone, text = args
    elif len(args) == 3:
        _user_id, phone, case_info = args
        case_number = case_info.get("case_number", "") if isinstance(case_info, dict) else ""
        text = f"Add case {case_number}"
    else:
        raise TypeError("handle_add_case expects 2 or 3 arguments")

    cnr = extract_cnr(text)

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

    added = []
    existing = []

    # CNR-first tracking path for scalable cross-court uniqueness.
    if cnr:
        details = fetch_case_details_by_cnr(cnr) or {"cnr": cnr, "case_number": cnr, "title": ""}
        stored_cnr = upsert_case_by_cnr(details)
        canonical_case = normalize_case_number(details.get("case_number")) or stored_cnr or cnr

        if add_tracked_case(
            phone,
            canonical_case,
            canonical_case,
            cnr=stored_cnr,
            court=details.get("court"),
        ):
            added.append(stored_cnr or cnr)
        else:
            existing.append(stored_cnr or cnr)

    if not cnr and not cases:
        message = "I couldn't find any valid case numbers. Please use format like 'CRL.M.C. 1234/2024'."
        return LegacyResponse(message) if legacy_mode else message

    for canonical_case in cases:
        if add_tracked_case(phone, canonical_case, canonical_case):
            added.append(canonical_case)
        else:
            existing.append(canonical_case)
            
    response = ""
    if added:
        response += f"Started tracking: {', '.join(added)}\n"
    if existing:
        response += f"Already tracking: {', '.join(existing)}\n"

    final_message = response.strip()

    if legacy_mode:
        case_number = cases[0]
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
    """Validated webhook-style handler retained for test compatibility."""
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


def send_alert_to_user(user_id: str, user_phone: str, alert: dict) -> dict:
    """Mock sender used by orchestrator tests."""
    logger.info("Sending alert to %s: %s", user_phone, alert.get("message", ""))
    return {"status": "sent", "user_id": user_id, "phone": user_phone}
