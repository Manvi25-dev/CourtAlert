import logging
import re
import os
import asyncio
import traceback
from uuid import uuid4
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Header, HTTPException, Request
from fastapi import Response
from fastapi.responses import PlainTextResponse
try:
    from pydantic.v1 import BaseModel, root_validator
except ImportError:
    from pydantic import BaseModel, root_validator
from dotenv import load_dotenv

load_dotenv()

from models import init_db, get_db_connection
from ingestion_service import (
    start_scheduler,
    run_ingestion_cycle,
    get_ingestion_summary,
    is_ingestion_running,
    get_scheduler_status,
)
from alert_service import build_alert_payload
from stt_bhashini import transcribe_audio
from whatsapp_handler import handle_incoming_message
from services.whatsapp_service import send_whatsapp
from services.sarvam_service import process_text_sarvam, transcribe_audio_sarvam
from orchestrator import process_user_message
from security import limiter, validate_external_audio_url, validate_system_api_key
from case_parser import extract_all_case_numbers
from case_matcher import normalize_case_number

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
API_V1_PREFIX = "/api/v1"
IN_MEMORY_CASE_STORE: list[dict[str, str]] = []
WHATSAPP_FALLBACK_REPLY = "I didn't understand. Try: Add case XYZ"


def _current_whatsapp_webhook_url() -> str:
    base_url = (
        os.getenv("NGROK_URL")
        or os.getenv("WEBHOOK_BASE_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or "<set NGROK_URL>"
    )
    return f"{base_url.rstrip('/')}/webhook/whatsapp"


def _extract_whatsapp_fields(payload: dict) -> tuple[str, str, str]:
    message_text = (
        payload.get("Body")
        or payload.get("message")
        or payload.get("Message")
        or ""
    )
    from_number = (
        payload.get("From")
        or payload.get("from")
        or payload.get("phone")
        or ""
    )
    normalized_phone = str(from_number).strip()
    if normalized_phone.lower().startswith("whatsapp:"):
        normalized_phone = normalized_phone.split(":", 1)[1].strip()
    media_url = (
        payload.get("MediaUrl0")
        or payload.get("media_url")
        or payload.get("audio_url")
        or ""
    )
    return str(message_text).strip(), normalized_phone, str(media_url).strip()


def _extract_case_number_manual(message_text: str) -> str | None:
    for candidate in extract_all_case_numbers(message_text or ""):
        canonical = normalize_case_number(candidate)
        if canonical:
            return canonical

    # Fallback regex for spaced/typed formats like CS(OS) 3336/2011.
    match = re.search(r"[A-Z][A-Z\.\(\)\-/\s]*\d+\s*/\s*\d{4}", (message_text or "").upper())
    if not match:
        return None
    extracted = match.group(0).strip()
    return normalize_case_number(extracted) or extracted


def _detect_action_manual(message_text: str) -> str:
    upper = (message_text or "").strip().upper()
    if upper.startswith("ADD CASE ") or upper.startswith("ADD "):
        return "add/track"
    if upper.startswith("CHECK") or upper.startswith("STATUS") or upper.startswith("LIST"):
        return "list/status"
    return "fallback"


async def _process_whatsapp_background(
    phone: str,
    message_text: str,
    media_url: str,
    request_id: str,
    detected_case: str | None,
) -> None:
    try:
        effective_text = message_text
        if media_url:
            logger.info("WhatsApp media message received: request_id=%s media_url=%s", request_id, media_url)
            effective_text = await asyncio.to_thread(transcribe_audio_sarvam, media_url)
            logger.info("Sarvam transcription output: request_id=%s transcript=%s", request_id, effective_text)

        llm_result = await asyncio.to_thread(process_text_sarvam, effective_text)
        llm_response = (llm_result.get("response_text") or "").strip()
        logger.info("Sarvam LLM response: request_id=%s response=%s", request_id, llm_response)

        result = await asyncio.to_thread(
            handle_incoming_message,
            {
                "user_phone_number": phone,
                "message_type": "text",
                "message_content": effective_text,
            },
        )

        response_text = ""
        if isinstance(result, dict):
            response_text = (result.get("response") or {}).get("message_text", "")

        action_taken = _detect_action_manual(effective_text)
        if action_taken == "fallback" and not response_text:
            response_text = llm_response or WHATSAPP_FALLBACK_REPLY

        print(f"Case detected: {detected_case or 'None'}")
        print(f"Action taken: {action_taken}")
        logger.info(
            "WhatsApp background complete: request_id=%s case=%s action=%s response=%s",
            request_id,
            detected_case,
            action_taken,
            response_text,
        )
    except Exception as exc:
        logger.error("WhatsApp background failure: request_id=%s error=%s", request_id, exc)
        print(f"❌ WEBHOOK ERROR: {exc}")


async def _run_pipeline_background(message_text: str, from_number: str, request_id: str) -> None:
    stage = "pipeline_start"
    try:
        # Run heavy orchestration off the request path so Twilio gets an immediate 200.
        stage = "process_user_message"
        await asyncio.to_thread(process_user_message, message_text, from_number, request_id)
        logger.info("Webhook background processing complete: request_id=%s", request_id)
    except Exception as exc:
        logger.error(
            "Webhook background failure: request_id=%s stage=%s source=FastAPI background task error=%s",
            request_id,
            stage,
            exc,
        )
        print(f"ERROR SOURCE: {stage}")
        print(f"ERROR: {exc}")
        print(traceback.format_exc())


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    print(f"Expected Twilio webhook URL: {_current_whatsapp_webhook_url()}")
    logger.info("Expected Twilio webhook URL: %s", _current_whatsapp_webhook_url())
    logger.info("Application started.")
    yield

app = FastAPI()
app.title = "CourtAlert API"
app.description = "WhatsApp-based legal case tracking system"
app.version = "1.2.0"
app.openapi_tags = [
    {"name": "User", "description": "User-facing tracking and alert endpoints."},
    {"name": "System", "description": "System-level operational endpoint."},
]
app.router.lifespan_context = lifespan


@app.get("/")
def home():
    return {"status": "ok"}

class WebhookMessage(BaseModel):
    phone: str
    message: str


class AudioTranscriptionRequest(BaseModel):
    audio_url: str | None = None
    audio_base64: str | None = None
    source_language: str = "en"

    @root_validator(skip_on_failure=True)
    def validate_audio_source(cls, values):
        provided_sources = [bool(values.get("audio_url")), bool(values.get("audio_base64"))]
        if sum(provided_sources) != 1:
            raise ValueError("Provide exactly one of audio_url or audio_base64")
        return values


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "127.0.0.1"


def _enforce_system_access(request: Request, system_key: str | None):
    client_ip = _client_ip(request)
    allowed, reason = limiter.allow_request(f"system:{client_ip}", client_ip)
    if not allowed:
        logger.warning("System route rate limit exceeded", extra={"ip": client_ip, "reason": reason})
        raise HTTPException(status_code=429, detail=reason)

    authorized, auth_error = validate_system_api_key(system_key)
    if not authorized:
        logger.warning("System route rejected: invalid API key", extra={"ip": client_ip})
        raise HTTPException(status_code=401, detail=auth_error)


def _store_case(case_number: str, user_number: str) -> dict[str, str]:
    record = {
        "case_number": case_number,
        "user_number": user_number,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    IN_MEMORY_CASE_STORE.append(record)
    logger.info("Stored case record: %s", record)
    return record


def _send_whatsapp_reply(user_number: str, reply_text: str) -> str | None:
    if not user_number:
        logger.warning("Skipping outgoing WhatsApp: missing user number")
        return None

    sid = send_whatsapp(user_number, reply_text)
    logger.info("Outgoing WhatsApp sent: to=%s sid=%s body=%s", user_number, sid, reply_text)
    return sid

@app.post(f"{API_V1_PREFIX}/webhook")
@app.post(
    "/webhook",
    tags=["User"],
    summary="Receive Webhook Message",
    description="Receives WhatsApp-style messages and extracts case numbers to track.",
)
def webhook(payload: WebhookMessage, request: Request):
    request_id = uuid4().hex[:12]
    logger.info(
        "Inbound JSON webhook: request_id=%s from=%s message=%s",
        request_id,
        payload.phone,
        payload.message,
    )
    result = process_user_message(payload.message, payload.phone, request_id=request_id)
    return {
        "status": result.get("status", "success"),
        "request_id": request_id,
        "response": result.get("response_text", "Unable to process request"),
    }


@app.post(
    "/webhook/whatsapp",
    tags=["User"],
    summary="Twilio WhatsApp Inbound Webhook",
    description="Receives inbound Twilio WhatsApp messages, parses commands, and sends appropriate replies.",
)
async def whatsapp_webhook(request: Request):
    form = await request.form()
    print("INCOMING:", dict(form))
    return Response("OK", media_type="text/plain")


def local_test_whatsapp_webhook_simulation() -> list[dict[str, str]]:
    simulated_payloads = [
        {
            "From": "whatsapp:+919999999999",
            "Body": "add case CS(OS) 3336/2011",
        },
        {
            "From": "whatsapp:+919999999999",
            "Body": "add case WP(C) 1836/2013",
        },
    ]

    outputs: list[dict[str, str]] = []
    for payload in simulated_payloads:
        print("WEBHOOK HIT")
        print("Incoming request body:", payload)

        message_text, from_number, _media_url = _extract_whatsapp_fields(payload)
        print("Parsed message text:", message_text)

        detected_case = _extract_case_number_manual(message_text)
        print("Extracted case number:", detected_case)

        action_taken = _detect_action_manual(message_text)
        result = handle_incoming_message(
            {
                "user_phone_number": from_number,
                "message_type": "text",
                "message_content": message_text,
            }
        )
        response_text = ""
        if isinstance(result, dict):
            response_text = (result.get("response") or {}).get("message_text", "")
        if not response_text and action_taken == "fallback":
            response_text = WHATSAPP_FALLBACK_REPLY

        print(f"Case detected: {detected_case or 'None'}")
        print(f"Action taken: {action_taken}")

        outputs.append(
            {
                "from": from_number,
                "message": message_text,
                "case_detected": detected_case or "",
                "action_taken": action_taken,
                "response": response_text,
            }
        )

    return outputs


@app.post(
    "/trigger-alerts",
    tags=["System"],
    summary="Trigger Alerts",
    description="Loops through in-memory tracked cases and sends WhatsApp reminder alerts.",
)
def trigger_alerts():
    if not IN_MEMORY_CASE_STORE:
        logger.info("Alert trigger invoked with empty in-memory case store")
        return {"status": "no_cases", "sent": 0, "message": "No stored cases to alert"}

    sent = 0
    failed = 0
    for record in IN_MEMORY_CASE_STORE:
        case_number = record.get("case_number", "")
        user_number = record.get("user_number", "")
        reminder = (
            "⚖️ CourtAlert Reminder\n"
            f"Case: {case_number}\n"
            "Status: Check cause list for updates"
        )

        logger.info("Alert triggered for record=%s", record)
        try:
            _send_whatsapp_reply(user_number, reminder)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.error("Failed to send alert for case=%s user=%s error=%s", case_number, user_number, exc)

    return {
        "status": "completed",
        "sent": sent,
        "failed": failed,
        "total_cases": len(IN_MEMORY_CASE_STORE),
    }

def _build_alert_response(limit: int = 50, priority: str | None = None) -> dict:
    valid_priorities = {None, "today", "tomorrow", "upcoming"}
    if priority not in valid_priorities:
        raise HTTPException(status_code=400, detail="Invalid alert priority")

    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT
                a.case_number AS alert_case_number,
                tc.case_number AS tracked_case_number,
                a.cnr,
                a.title,
                h.case_title,
                a.advocate,
                h.advocate AS hearing_advocate,
                a.court,
                h.court_name,
                a.court_number,
                a.judge,
                a.status,
                h.hearing_date,
                a.hearing_date AS alert_hearing_date,
                a.district,
                a.priority,
                a.message,
                a.source,
                h.source_pdf
            FROM alerts a
            LEFT JOIN tracked_cases tc ON a.case_id = tc.id
            LEFT JOIN hearings h ON a.hearing_id = h.id
            ORDER BY a.created_at DESC
            LIMIT ?
            '''
            ,
            (limit,),
        ).fetchall()

        alerts = []
        for row in rows:
            listing_status = row["status"]
            if listing_status in {"pending", "sent", "failed"}:
                listing_status = None
            alert = build_alert_payload(
                case_number=row["alert_case_number"] or row["tracked_case_number"] or "",
                cnr=row["cnr"],
                title=row["title"] or row["case_title"],
                court=row["court"] or row["court_name"],
                court_number=row["court_number"],
                judge=row["judge"],
                status=listing_status,
                hearing_date=row["alert_hearing_date"] or row["hearing_date"],
                district=row["district"],
                source=row["source"],
                advocate=row["advocate"] or row["hearing_advocate"],
                source_pdf=row["source_pdf"],
            )
            if row["priority"]:
                alert["priority"] = row["priority"]
            if row["message"]:
                alert["message"] = row["message"]
            if priority and alert["priority"] != priority:
                continue
            alerts.append(alert)

        return {"count": len(alerts), "alerts": alerts}
    finally:
        conn.close()


@app.get(f"{API_V1_PREFIX}/alerts")
@app.get(
    "/alerts",
    tags=["User"],
    summary="Get Alerts",
    description="Returns alerts generated during the latest ingestion cycle.",
)
def get_alerts(priority: str | None = None):
    """Return recent structured alerts for UI consumption."""
    return _build_alert_response(priority=priority)


@app.get(f"{API_V1_PREFIX}/alerts/today")
@app.get(
    "/alerts/today",
    tags=["User"],
    summary="Get Today's Alerts",
    description="Returns only alerts scheduled for today.",
)
def get_today_alerts():
    return _build_alert_response(priority="today")


@app.post(f"{API_V1_PREFIX}/system/transcribe-audio")
@app.post(
    "/system/transcribe-audio",
    tags=["System"],
    summary="Transcribe Audio",
    description="Transcribes an audio URL or base64 audio payload using Sarvam speech-to-text.",
)
def transcribe_audio_endpoint(
    payload: AudioTranscriptionRequest,
    request: Request,
    x_system_key: str | None = Header(default=None),
):
    _enforce_system_access(request, x_system_key)

    audio_source = payload.audio_base64 or payload.audio_url or ""
    if payload.audio_url:
        valid_url, error_message = validate_external_audio_url(payload.audio_url)
        if not valid_url:
            raise HTTPException(status_code=400, detail=error_message)

    transcript = transcribe_audio(audio_source, payload.source_language)
    return {"status": "success", "transcript": transcript}


@app.post(f"{API_V1_PREFIX}/system/run-ingestion")
@app.post(
    "/system/run-ingestion",
    tags=["System"],
    summary="Run Ingestion",
    description="Manually trigger cause list ingestion.",
)
def run_ingestion(
    background_tasks: BackgroundTasks,
    request: Request,
    x_system_key: str | None = Header(default=None),
):
    """Non-blocking manual ingestion trigger."""
    _enforce_system_access(request, x_system_key)

    current_summary = get_ingestion_summary()
    courts_checked = current_summary.get("courts_checked", 0)
    if is_ingestion_running():
        return {
            "status": "already_running",
            "message": "Ingestion already in progress",
            "courts_checked": courts_checked,
            "pdfs_processed": get_ingestion_summary().get("pdfs_processed", 0),
            "last_summary": get_ingestion_summary(),
        }

    # Runs after response is sent; API call returns quickly.
    background_tasks.add_task(run_ingestion_cycle, True)
    return {
        "status": "started",
        "message": "Ingestion started in background",
        "courts_checked": courts_checked,
        "pdfs_processed": 0,
        "last_summary": get_ingestion_summary(),
    }


@app.get(
    "/test-whatsapp",
    tags=["System"],
    summary="Send Test WhatsApp",
    description="Sends a test WhatsApp message using Twilio Sandbox.",
)
def test_whatsapp():
    sid = send_whatsapp(
        "+919540098192",
        "⚖️ CourtAlert Test from Backend",
    )
    return {"status": "sent", "sid": sid}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


@app.get("/health", tags=["System"], summary="Health Check")
def health():
    """Returns service health status for deployment monitoring."""
    return {
        "status": "ok",
        "ingestion_scheduler": get_scheduler_status(),
        "version": "v1",
    }
