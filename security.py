import ipaddress
import re
import logging
import os
import socket
import time
from collections import defaultdict
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


class RateLimiter:
    """In-memory sliding-window limiter for local testing."""

    def __init__(self, max_ip_requests: int = 60, max_user_requests: int = 20, window_seconds: int = 60):
        self.max_ip_requests = max_ip_requests
        self.max_user_requests = max_user_requests
        self.window_seconds = window_seconds
        self.ip_requests: dict[str, list[float]] = defaultdict(list)
        self.user_requests: dict[str, list[float]] = defaultdict(list)

    def _prune(self, values: list[float], now: float) -> list[float]:
        cutoff = now - self.window_seconds
        return [v for v in values if v >= cutoff]

    def allow_request(self, phone_number: str, client_ip: str) -> tuple[bool, str | None]:
        now = time.time()
        self.ip_requests[client_ip] = self._prune(self.ip_requests[client_ip], now)
        self.user_requests[phone_number] = self._prune(self.user_requests[phone_number], now)

        if len(self.ip_requests[client_ip]) >= self.max_ip_requests:
            logger.warning("Rate limit exceeded", extra={"ip": client_ip, "limit_type": "ip"})
            return False, "Rate limit exceeded for IP"
        if len(self.user_requests[phone_number]) >= self.max_user_requests:
            logger.warning("Rate limit exceeded", extra={"ip": client_ip, "user": phone_number, "limit_type": "user"})
            return False, "Rate limit exceeded for user"

        self.ip_requests[client_ip].append(now)
        self.user_requests[phone_number].append(now)
        return True, None


limiter = RateLimiter()


def get_system_api_key() -> str:
    return os.getenv("COURTALERT_SYSTEM_API_KEY", "").strip()


def validate_system_api_key(provided_key: str | None) -> tuple[bool, str | None]:
    required_key = get_system_api_key()
    if not required_key:
        return True, None
    if provided_key != required_key:
        logger.warning("Invalid system API key attempt", extra={"key_provided": bool(provided_key)})
        return False, "Invalid system API key"
    return True, None


def validate_external_audio_url(url: str) -> tuple[bool, str | None]:
    parsed = urlsplit((url or "").strip())
    if parsed.scheme.lower() != "https":
        logger.warning("Blocked unsafe URL: non-HTTPS scheme", extra={"url": url, "scheme": parsed.scheme})
        return False, "Only HTTPS audio URLs are allowed"

    hostname = parsed.hostname
    if not hostname:
        logger.warning("Blocked unsafe URL: missing hostname", extra={"url": url})
        return False, "Audio URL must include a hostname"

    if hostname.lower() in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        logger.warning("Blocked unsafe URL: localhost target", extra={"url": url, "hostname": hostname})
        return False, "Audio URL cannot target localhost"

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        logger.warning("Blocked unsafe URL: unresolvable hostname", extra={"url": url, "hostname": hostname})
        return False, "Audio URL hostname could not be resolved"

    for result in resolved:
        ip_text = result[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            logger.warning(
                "Blocked unsafe URL: resolves to non-public IP",
                extra={"url": url, "hostname": hostname, "resolved_ip": ip_text},
            )
            return False, "Audio URL resolves to a non-public IP address"

    return True, None

def validate_webhook_payload(payload: dict) -> tuple[dict, str]:
    """
    Validate normalized webhook payload.
    Returns (validated_data, error_message).
    """
    required_fields = ["user_phone_number", "message_type", "message_content"]
    for field in required_fields:
        if field not in payload:
            return None, f"Missing required field: {field}"
            
    # Validate Phone Number (E.164ish)
    phone = payload["user_phone_number"]
    if not re.match(r'^\+\d{10,15}$', phone):
        return None, f"Invalid phone number format: {phone}"
        
    # Validate Message Type
    msg_type = payload["message_type"]
    if msg_type not in ["text", "voice", "audio"]:
        return None, f"Unsupported message type: {msg_type}"
        
    return payload, None

def sanitize_case_number(case_number: str) -> str:
    """
    Sanitize case number input.
    Allow only alphanumeric, dots, slashes, hyphens, and spaces.
    """
    if not case_number:
        return ""
    # Remove any character that isn't alphanumeric, space, dot, slash, or hyphen
    sanitized = re.sub(r'[^a-zA-Z0-9\s\./-]', '', case_number)
    return sanitized.strip()

def validate_canonical_case_id(case_id: str) -> bool:
    """
    Validate if a case ID matches the strict canonical format: TYPE-NUMBER-YEAR.
    Example: CRLMC-8148-2025
    """
    if not case_id:
        return False
    return bool(re.match(r'^[A-Z0-9]+-\d+-\d{4}$', case_id))
