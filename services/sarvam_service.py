import json
import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

SARVAM_LLM_URL = os.getenv("SARVAM_LLM_URL", "https://api.sarvam.ai/v1/chat/completions").strip()
SARVAM_STT_URL = os.getenv("SARVAM_STT_URL", "https://api.sarvam.ai/v1/speech-to-text").strip()
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
SARVAM_LLM_MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-m").strip()
SARVAM_STT_LANGUAGE = os.getenv("SARVAM_STT_LANGUAGE", "en-IN").strip()
SARVAM_TIMEOUT_SECONDS = int(os.getenv("SARVAM_TIMEOUT_SECONDS", "4").strip() or "4")


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
    }


def _extract_json_text(raw_content: str) -> str | None:
    cleaned = (raw_content or "").strip().replace("```json", "").replace("```", "")
    if not cleaned:
        return None
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    return match.group(0).strip()


def _download_twilio_audio(media_url: str, timeout_seconds: int) -> bytes:
    sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()

    try:
        if sid and token:
            response = requests.get(media_url, auth=(sid, token), timeout=timeout_seconds)
        else:
            response = requests.get(media_url, timeout=timeout_seconds)
        response.raise_for_status()
        return response.content
    except Exception:
        # Some Twilio media URLs are public for a short period. Retry without auth if auth path fails.
        response = requests.get(media_url, timeout=timeout_seconds)
        response.raise_for_status()
        return response.content


def transcribe_audio_sarvam(audio_url: str, source_language: str | None = None) -> str:
    """Download Twilio audio and transcribe using Sarvam STT.

    Returns a safe fallback string on failure and never raises by default.
    """
    language = (source_language or SARVAM_STT_LANGUAGE or "en-IN").strip()

    if not audio_url:
        logger.warning("Sarvam STT skipped: empty audio_url")
        return "Could not process audio"

    if not SARVAM_API_KEY:
        logger.warning("SARVAM_API_KEY missing; using STT fallback")
        return "Could not process audio"

    try:
        audio_bytes = _download_twilio_audio(audio_url, SARVAM_TIMEOUT_SECONDS)
        files = {
            "file": ("voice_note.ogg", audio_bytes, "audio/ogg"),
        }
        data = {
            "language_code": language,
        }
        response = requests.post(
            SARVAM_STT_URL,
            headers=_auth_headers(),
            data=data,
            files=files,
            timeout=SARVAM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        payload = response.json() if response.content else {}
        transcript = (
            payload.get("transcript")
            or payload.get("text")
            or payload.get("output")
            or ""
        )
        transcript = str(transcript).strip()

        if transcript:
            return transcript

        logger.warning("Sarvam STT returned no transcript payload=%s", payload)
        return "Could not process audio"
    except Exception as exc:
        logger.exception("Sarvam STT failed: %s", exc)
        return "Could not process audio"


def process_text_sarvam(message_text: str) -> dict[str, Any]:
    """Run message through Sarvam LLM for intent extraction and simple plain-text reply.

    Returns:
        {
          "intent": "add_case|track_case|list_status|unknown",
          "case_number": "...|None",
          "response_text": "plain text response",
        }
    """
    base_response = {
        "intent": "unknown",
        "case_number": None,
        "response_text": (message_text or "").strip() or "I could not understand your request.",
    }

    if not message_text:
        return base_response

    if not SARVAM_API_KEY:
        logger.warning("SARVAM_API_KEY missing; returning passthrough text")
        return base_response

    prompt = (
        "You are a legal WhatsApp assistant parser for Indian court case tracking. "
        "Return ONLY minified JSON with keys intent, case_number, response_text. "
        "Intent must be one of add_case, track_case, list_status, unknown. "
        "response_text must be short plain text suitable for WhatsApp and contain no markdown.\n"
        f"User message: {message_text}"
    )

    payload = {
        "model": SARVAM_LLM_MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 180,
    }

    try:
        response = requests.post(
            SARVAM_LLM_URL,
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=SARVAM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        body = response.json() if response.content else {}
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content and isinstance(body.get("output"), str):
            content = body.get("output", "")
        if not content and isinstance(body.get("response"), str):
            content = body.get("response", "")

        json_text = _extract_json_text(content)
        if not json_text:
            logger.warning("Sarvam LLM returned non-JSON content: %s", content)
            return base_response

        parsed = json.loads(json_text)
        intent = str(parsed.get("intent") or "unknown").strip().lower()
        if intent not in {"add_case", "track_case", "list_status", "unknown"}:
            intent = "unknown"

        case_number = parsed.get("case_number")
        if isinstance(case_number, str):
            case_number = case_number.strip() or None
        else:
            case_number = None

        response_text = parsed.get("response_text")
        if not isinstance(response_text, str) or not response_text.strip():
            response_text = base_response["response_text"]

        return {
            "intent": intent,
            "case_number": case_number,
            "response_text": response_text.strip(),
        }
    except Exception as exc:
        logger.exception("Sarvam LLM failed: %s", exc)
        return base_response
