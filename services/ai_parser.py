import os
import json
import logging
import re

import requests
from dotenv import load_dotenv
from services.parser import normalize_case_number, is_valid_case
from services.sarvam_service import process_text_sarvam

load_dotenv()

logger = logging.getLogger(__name__)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")


def _has_standard_case_year(case_number: str) -> bool:
    return bool(re.search(r"/\d{4}$", case_number))


def ai_parse_message(message: str) -> dict:
    """
    Use Sarvam API as fallback parser when rule-based parsing fails.
    
    Args:
        message: Raw user message text
        
    Returns:
        dict with keys:
            - intent: "add_case", "track_case", or "unknown"
            - case_number: extracted case number or None
    """
    if not SARVAM_API_KEY:
        logger.warning("SARVAM_API_KEY not set. AI parsing unavailable.")
        return {"intent": "unknown", "case_number": None}

    try:
        result = process_text_sarvam(message)
        intent = result.get("intent", "unknown")
        case_number = result.get("case_number")

        if intent not in {"add_case", "track_case", "unknown", "list_status"}:
            intent = "unknown"

        if intent == "list_status":
            # Existing orchestrator supports add/track/unknown; map list intent safely.
            intent = "unknown"

        if isinstance(case_number, str):
            cleaned_case = case_number.strip()
            case_number = normalize_case_number(cleaned_case) if cleaned_case else None
            if case_number and not _has_standard_case_year(case_number):
                candidate_match = re.search(
                    r"([a-z.()]+(?:\s|-)*\d+(?:\s*(?:/|-|\s)\s*\d{4}))",
                    message.lower(),
                )
                if candidate_match:
                    case_number = normalize_case_number(candidate_match.group(1))
            if case_number and not is_valid_case(case_number):
                logger.info("AI partial/invalid case rejected: %s", case_number)
                case_number = None
        else:
            case_number = None

        logger.info(
            "Sarvam parser result: intent=%s case=%s",
            intent,
            case_number,
        )
        return {
            "intent": intent,
            "case_number": case_number,
        }

    except requests.exceptions.RequestException as exc:
        logger.error("Sarvam API request error: %s", exc)
        return {"intent": "unknown", "case_number": None}
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Sarvam response JSON: %s", exc)
        return {"intent": "unknown", "case_number": None}
    except Exception as exc:
        logger.error("Unexpected error in ai_parse_message: %s", exc)
        return {"intent": "unknown", "case_number": None}
