import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def parse_hearing_date(value: Optional[str]) -> date | None:
    if not value:
        return None

    cleaned = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def derive_source(source_pdf: Optional[str]) -> str:
    source_lower = (source_pdf or "").lower()
    if "adv" in source_lower:
        return "advance_list"
    if "sup" in source_lower:
        return "supplementary_list"
    return "cause_list"


def classify_alert_priority(hearing_date: Optional[str], today: Optional[date] = None) -> str:
    hearing_day = parse_hearing_date(hearing_date)
    reference_day = today or date.today()

    if hearing_day is None or hearing_day > reference_day + timedelta(days=1):
        return "upcoming"
    if hearing_day == reference_day:
        return "today"
    if hearing_day == reference_day + timedelta(days=1):
        return "tomorrow"
    return "upcoming"


def format_hearing_date(hearing_date: Optional[str]) -> str:
    hearing_day = parse_hearing_date(hearing_date)
    if hearing_day is None:
        return hearing_date or "Unknown Date"
    return hearing_day.strftime("%d %b %Y")


def format_alert_message(alert: Dict[str, Any], today: Optional[date] = None) -> str:
    priority = alert.get("priority") or classify_alert_priority(alert.get("hearing_date"), today=today)
    heading = {
        "today": "Case listed today",
        "tomorrow": "Case listed tomorrow",
        "upcoming": "Case listed upcoming",
    }.get(priority, "Case listed")

    lines = [
        heading,
        "",
        alert.get("case_number") or "Unknown Case",
        alert.get("title") or "Unknown Title",
        "",
        f"Court: {alert.get('court') or 'Unknown Court'}",
    ]

    if alert.get("court_number"):
        lines.append(f"Court No.: {alert['court_number']}")
    if alert.get("judge"):
        lines.append(f"Judge: {alert['judge']}")
    if alert.get("status"):
        lines.append(f"Stage: {alert['status']}")
    if alert.get("district"):
        lines.append(f"District: {alert['district']}")

    lines.extend([
        "",
        f"Date: {format_hearing_date(alert.get('hearing_date'))}",
    ])

    return "\n".join(lines)


def build_alert_payload(
    case_number: str,
    cnr: Optional[str] = None,
    title: Optional[str] = None,
    court: Optional[str] = None,
    court_number: Optional[str] = None,
    judge: Optional[str] = None,
    status: Optional[str] = None,
    hearing_date: Optional[str] = None,
    district: Optional[str] = None,
    source: Optional[str] = None,
    advocate: Optional[str] = None,
    user_phone: Optional[str] = None,
    source_pdf: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a structured alert payload with normalized fields."""
    payload = {
        "cnr": cnr,
        "case_number": case_number,
        "title": title or "Unknown Title",
        "court": court or "Unknown Court",
        "court_number": court_number or "",
        "judge": judge or "Unknown Judge",
        "status": status or "Listed",
        "hearing_date": hearing_date or date.today().isoformat(),
        "district": district or "",
        "source": source or derive_source(source_pdf),
        "advocate": advocate or "Unknown Advocate",
    }

    payload["priority"] = classify_alert_priority(payload["hearing_date"])
    payload["message"] = format_alert_message(payload)

    if user_phone:
        payload["user_phone"] = user_phone
    if source_pdf:
        payload["source_pdf"] = source_pdf

    logger.debug("Built alert payload: %s", payload)
    return payload
