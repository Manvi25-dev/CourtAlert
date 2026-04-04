import re
import logging

logger = logging.getLogger(__name__)

# Case pattern supports variants like:
# - W.P.(C) 1836/2013
# - wp(c) 1836 2013
# - WP C 1836/2013
# - LPA-186/2024
# - LPA 186 2024
CASE_PATTERN = re.compile(
    r"(?P<case_type>\b(?:"
    r"[a-z]{2,6}(?:\(\s*[a-z]{1,3}\s*\))?"
    r"|[a-z](?:\s*\.\s*[a-z]){1,5}(?:\s*\.?\s*(?:\(\s*[a-z]{1,3}\s*\)|[a-z]{1,3}))?"
    r"|[a-z]{1,3}(?:\s+[a-z]{1,3}){1,2}"
    r"))"
    r"\s*[- ]?\s*(?P<case_no>\d+)\s*(?:/|-|\s)\s*(?P<year>\d{4})",
    re.IGNORECASE,
)

CASE_VALIDATION_PATTERN = re.compile(r"^[A-Z][A-Z()]*-\d+/\d{4}$")
INVALID_CASE_TYPE_TOKENS = {
    "ADD",
    "TRACK",
    "CASE",
    "NUMBER",
    "MONITOR",
    "PLEASE",
    "CHECK",
    "UPDATE",
    "STATUS",
}
PARTIAL_TYPE_NUMBER_PATTERN = re.compile(
    r"\b(?:"
    r"[a-z]{2,6}(?:\s*\(\s*[a-z]{1,3}\s*\)|\s+[a-z]{1,3})?"
    r"|[a-z](?:\s*\.?\s*[a-z]){1,5}(?:\s*\(\s*[a-z]{1,3}\s*\)|\s+[a-z]{1,3})?"
    r")\s*[- ]?\s*\d+\b(?!\s*(?:/|-|\s)\s*\d{4})",
    re.IGNORECASE,
)
PARTIAL_NUMBER_YEAR_PATTERN = re.compile(r"\b\d+\s*(?:/|-|\s)\s*\d{4}\b")
PARTIAL_CASE_ONLY_NUMBER_PATTERN = re.compile(
    r"\bcase\s*(?:no\.?|number)?\s*[:\-]?\s*(\d{1,8})\b",
    re.IGNORECASE,
)


def _normalize_case_type(raw_case_type: str) -> str:
    cleaned = raw_case_type.replace(".", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()

    if "(" in cleaned and ")" in cleaned:
        # WP ( C ) -> WP(C)
        return re.sub(r"\s+", "", cleaned)

    tokens = re.findall(r"[A-Z]+", cleaned)
    if not tokens:
        return ""

    # WP C -> WP(C), W P C -> WP(C)
    if len(tokens) >= 2 and len(tokens[-1]) == 1:
        base = "".join(tokens[:-1])
        return f"{base}({tokens[-1]})"

    return "".join(tokens)


def is_valid_case(case_number: str) -> bool:
    """Return True only for complete identifiers like WP(C)-1836/2013."""
    if not case_number:
        return False
    normalized = case_number.strip().upper()
    if not CASE_VALIDATION_PATTERN.match(normalized):
        return False

    case_type = normalized.split("-", 1)[0]
    compact_case_type = re.sub(r"[^A-Z]", "", case_type)
    if compact_case_type in INVALID_CASE_TYPE_TOKENS:
        return False

    return True


def _find_partial_case_candidate(message: str) -> str | None:
    partial_match = PARTIAL_TYPE_NUMBER_PATTERN.search(message)
    if partial_match:
        return partial_match.group(0)

    number_year_match = PARTIAL_NUMBER_YEAR_PATTERN.search(message)
    if number_year_match and not re.search(r"[a-zA-Z]", number_year_match.group(0)):
        return number_year_match.group(0)

    case_only_number_match = PARTIAL_CASE_ONLY_NUMBER_PATTERN.search(message)
    if case_only_number_match:
        return case_only_number_match.group(1)

    return None


def normalize_case_number(raw_case: str) -> str:
    """
    Normalize legal case numbers to standard format.
    
    Examples:
    - "W.P.(C) 1836/2013" → "WP(C)-1836/2013"
    - "WP(C) 1836/2013" → "WP(C)-1836/2013"
    - "WPC 1836/2013" → "WPC-1836/2013"
    - "LPA-186/2024" → "LPA-186/2024"
    - "LPA 186/2024" → "LPA-186/2024"
    
    Args:
        raw_case: Raw extracted case string (already lowercase)
        
    Returns:
        Normalized case number string in uppercase
    """
    raw_cleaned = re.sub(r"\s+", " ", raw_case.strip())
    match = CASE_PATTERN.search(raw_cleaned)

    if match:
        case_type = _normalize_case_type(match.group("case_type"))
        case_num = match.group("case_no")
        year = match.group("year")

        if case_type and year:
            return f"{case_type}-{case_num}/{year}"
        if case_type:
            return f"{case_type}-{case_num}"
        return f"{case_num}/{year}"
    else:
        # Fallback: retain uppercase alphanumeric shape without inventing structure.
        return re.sub(r"[^A-Z0-9/\-()]", "", raw_case.upper())


def parse_message(message: str) -> dict:
    """
    Parse incoming WhatsApp message and detect intent + extract case number.
    
    Supports multiple case formats:
    - "Add case LPA-186/2024" → intent: add_case, case: "LPA-186/2024"
    - "Track case W.P.(C) 1836/2013" → intent: track_case, case: "WP(C)-1836/2013"
    - "can i monitor case WPC 1836/2013" → intent: track_case, case: "WPC-1836/2013"
    
    Case format variations handled:
    - W.P.(C), WP(C), WPC (with/without dots/parens)
    - Flexible spacing: "W.P. (C) 1836 / 2013"
    - LPA-186/2024, LPA 186/2024
    
    Returns:
        {
            "intent": "add_case" | "track_case" | "unknown",
            "case_number": str (normalized) or None
        }
    """
    normalized = message.lower().strip()
    intent = "unknown"
    case_number = None

    logger.info("[Parser] Raw input: %s", message)

    # Detect intent
    if re.search(r"\badd\b", normalized):
        intent = "add_case"
    elif re.search(r"\btrack\b", normalized):
        intent = "track_case"

    case_match = CASE_PATTERN.search(normalized)
    
    if case_match:
        raw_case = case_match.group(0)
        logger.info("[Parser] Matched pattern: %s", raw_case)
        normalized_case = normalize_case_number(raw_case)
        if is_valid_case(normalized_case):
            case_number = normalized_case
            logger.info("[Parser] Normalized output: %s", case_number)
        else:
            logger.info("[Parser] Rejected partial match after normalization: %s", normalized_case)
            case_number = None
    else:
        logger.info("[Parser] No case number extracted")
        partial_candidate = _find_partial_case_candidate(normalized)
        if partial_candidate:
            logger.info("[Parser] Rejected partial match: %s", partial_candidate)

    if intent == "unknown" and case_number:
        # If a clear case number exists, treat as track request by default.
        intent = "track_case"
        logger.info("[Parser] Intent promoted to track_case due to clear case number")

    result = {
        "intent": intent,
        "case_number": case_number,
    }
    logger.info("[Parser] Final result: intent=%s, case_number=%s", intent, case_number)
    
    return result
