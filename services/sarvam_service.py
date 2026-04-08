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


def extract_intent_with_confidence(message_text: str, user_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Enhanced intent extraction with strict JSON structure and context-aware case identification.

    Args:
        message_text: User's WhatsApp message
        user_context: Dict with keys: tracked_cases, last_query, last_action, last_case

    Returns:
        {
            "intent": "TRACK_CASE|QUERY_STATUS|LIST_CASES|REMOVE_CASE|UNKNOWN",
            "case_identifier": "...|None",
            "case_type": "CNR|CASE_NUMBER|NONE",
            "confidence": 0.0-1.0,
            "entities": {
                "case_number": "...|None",
                "court": "...|None",
                "action_type": "add|remove|list|check",
            },
            "reasoning": "explanation for intent choice",
            "suggested_next_action": "what system should do next",
        }
    """
    base_response = {
        "intent": "UNKNOWN",
        "case_identifier": None,
        "case_type": "NONE",
        "confidence": 0.5,
        "entities": {"case_number": None, "court": None, "action_type": None},
        "reasoning": "Unable to parse message",
        "suggested_next_action": "ask_for_clarification",
    }

    if not message_text:
        return base_response

    if not SARVAM_API_KEY:
        logger.warning("SARVAM_API_KEY missing; using fallback intent extraction")
        return base_response

    user_context = user_context or {}
    tracked = ", ".join(user_context.get("tracked_cases", [])[:3]) or "none"
    last_action = user_context.get("last_action", "none")
    last_case = user_context.get("last_case", "none")

    prompt = f"""You are an intelligent legal assistant for Indian court case tracking.

ANALYZE this user message and return STRICT JSON with intent and case identifier.

USER CONTEXT:
- Currently tracking: {tracked}
- Last accessed case: {last_case}
- Last action: {last_action}

USER MESSAGE: "{message_text}"

TASK:
1. Identify primary INTENT
2. Extract CASE_IDENTIFIER (CNR or case number)
3. Identify CASE_TYPE (CNR, CASE_NUMBER, or NONE)
4. Assess CONFIDENCE (0-1) based on message clarity

INTENT CLASSIFICATION:
- TRACK_CASE: User wants to add/track a new case
- QUERY_STATUS: User asks "when is it?", "what's next?", "hearing date?", "status?"
- LIST_CASES: User wants to see tracked cases
- REMOVE_CASE: User wants to delete/stop tracking a case
- UNKNOWN: Ambiguous or unclear intent

CASE IDENTIFIER RULES:
- CNR: 16 alphanumeric chars (e.g., GJDH020024462018, HRS0010076892025)
- CASE_NUMBER: Format like "LPA 171/2019", "CRL.M.C. 320/2026", "CASE 171 of 2019"
- Accept flexible formats: "case 171 of 2019", "lpa/171/2019", "CNR:GJDH020024462018"
- If user says "when is it?" or "status?" and context has tracked cases → use last_case from context

CONFIDENCE SCORING:
- 0.95+: Clear case identifier with explicit intent
- 0.85-0.94: Case identifier present but phrasing loose
- 0.70-0.84: Weak case signals or ambiguous intent
- 0.50-0.69: Very unclear, requires fallback parsing
- <0.50: No recognizable pattern

RETURN ONLY valid JSON (no markdown, no extra text):
{{
  "intent": "TRACK_CASE|QUERY_STATUS|LIST_CASES|REMOVE_CASE|UNKNOWN",
  "case_identifier": "GJDH020024462018 or LPA/171/2019 or null",
  "case_type": "CNR|CASE_NUMBER|NONE",
  "confidence": 0.90,
  "entities": {{
    "case_number": "optional extracted case number",
    "court": "optional inferred court",
    "action_type": "add|remove|list|check"
  }},
  "reasoning": "why this intent and case",
  "suggested_next_action": "next system action"
}}"""


    payload = {
        "model": SARVAM_LLM_MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
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

        json_text = _extract_json_text(content)
        if not json_text:
            logger.warning("Sarvam intent extraction returned non-JSON: %s", content[:200])
            return base_response

        parsed = json.loads(json_text)

        # Validate and map intent
        raw_intent = str(parsed.get("intent", "")).strip().upper()
        valid_intents = {"TRACK_CASE", "QUERY_STATUS", "LIST_CASES", "REMOVE_CASE", "UNKNOWN"}
        intent = raw_intent if raw_intent in valid_intents else "UNKNOWN"

        # Extract case_identifier and case_type
        case_identifier = str(parsed.get("case_identifier", "") or "").strip() or None
        raw_case_type = str(parsed.get("case_type", "")).strip().upper()
        valid_case_types = {"CNR", "CASE_NUMBER", "NONE"}
        case_type = raw_case_type if raw_case_type in valid_case_types else "NONE"

        # Extract confidence
        confidence = float(parsed.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))  # Clamp to 0-1

        # Extract entities
        entities_raw = parsed.get("entities", {})
        entities = {
            "case_number": (entities_raw.get("case_number") or "").strip() or None,
            "court": (entities_raw.get("court") or "").strip() or None,
            "action_type": (entities_raw.get("action_type") or "").strip().lower() or None,
        }

        # Get reasoning and next action
        reasoning = str(parsed.get("reasoning", "")).strip() or f"Intent: {intent}, Case: {case_identifier or 'not provided'}"
        next_action = (
            str(parsed.get("suggested_next_action", "")).strip().lower()
            or ("fetch_case_status" if intent == "QUERY_STATUS" else ("add_case" if intent == "TRACK_CASE" else "prompt_for_case_number"))
        )

        return {
            "intent": intent,
            "case_identifier": case_identifier,
            "case_type": case_type,
            "confidence": confidence,
            "entities": entities,
            "reasoning": reasoning,
            "suggested_next_action": next_action,
        }

    except json.JSONDecodeError as exc:
        logger.exception("Sarvam returned invalid JSON: %s", exc)
        return base_response
    except Exception as exc:
        logger.exception("Sarvam intent extraction failed: %s", exc)
        return base_response

