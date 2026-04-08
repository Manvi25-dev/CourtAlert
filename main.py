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

from ecourts_api import API_UNAVAILABLE_MESSAGE, build_case_status_message, match_case_listing
from court_sources import court_sources as live_court_sources, resolve_court_from_case, today_iso
from models import (
    init_db,
    get_db_connection,
    add_user,
    add_tracked_case,
    get_user_cases,
    get_user_alerts_with_hearings,
)
from ingestion_service import (
    start_scheduler,
    run_ingestion_cycle,
    get_ingestion_summary,
    get_last_parsed_entries,
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


def _resolve_live_source_key(case_number: str | None, court_name: str | None = None) -> str:
    court_text = (court_name or "").lower()
    if "gurugram" in court_text or "gurgaon" in court_text:
        return "gurugram"
    if "sonipat" in court_text or "sonepat" in court_text:
        return "sonipat"
    return resolve_court_from_case(case_number, court_name)["court_key"]


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
    if (
        upper.startswith("CHECK")
        or upper.startswith("STATUS")
        or upper.startswith("LIST")
        or "WHEN IS IT" in upper
        or "NEXT HEARING" in upper
        or "UPDATE ME ON MY CASES" in upper
    ):
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

def _extract_simple_webhook_fields(payload: dict) -> tuple[str, str]:
    phone = payload.get("phone") or payload.get("From") or payload.get("from") or payload.get("user_phone_number") or ""
    message = payload.get("message") or payload.get("Body") or payload.get("message_content") or payload.get("Message") or ""
    return str(phone).strip(), str(message).strip()


@app.post(f"{API_V1_PREFIX}/webhook")
@app.post(
    "/webhook",
    tags=["User"],
    summary="Receive Webhook Message",
    description="Receives WhatsApp-style messages and extracts case numbers to track.",
)
async def webhook(request: Request):
    request_id = uuid4().hex[:12]

    payload: dict
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    phone, message = _extract_simple_webhook_fields(payload)
    if not phone or not message:
        logger.warning("Inbound webhook missing phone/message: request_id=%s payload=%s", request_id, payload)
        return Response("Missing phone or message", status_code=400, media_type="text/plain")

    logger.info(
        "Inbound JSON webhook: request_id=%s from=%s message=%s",
        request_id,
        phone,
        message,
    )
    result = process_user_message(message, phone, request_id=request_id)
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
    request_id = uuid4().hex[:12]
    
    try:
        form = await request.form()
        logger.info("WhatsApp webhook received: request_id=%s form=%s", request_id, dict(form))
        
        # Extract phone and message from Twilio form
        message_text, from_number, _media_url = _extract_whatsapp_fields(dict(form))
        logger.info("Extracted fields: request_id=%s from=%s message=%s", request_id, from_number, message_text)
        
        # Detect intent first, then route.
        action = _detect_action_manual(message_text)
        logger.info("Intent detected: request_id=%s action=%s", request_id, action)
        
        response_text = ""
        
        # Handle "add/track" action with valid case number
        if action == "add/track":
            detected_case = _extract_case_number_manual(message_text)
            logger.info("Add intent details: request_id=%s phone=%s case=%s", request_id, from_number, detected_case)

            if not detected_case:
                response_text = "Invalid format. Try: add case CRL.M.C. 123/2024"
                logger.info("Add intent without case: request_id=%s phone=%s", request_id, from_number)
                return Response(response_text, media_type="text/plain")

            try:
                # Add user to DB
                add_user(from_number)
                logger.info("User added: request_id=%s phone=%s", request_id, from_number)
                
                # Add tracked case to DB
                success = add_tracked_case(from_number, detected_case)
                
                if success:
                    response_text = f"Case {detected_case} is now being tracked."
                    logger.info("Case stored successfully: request_id=%s phone=%s case=%s", 
                               request_id, from_number, detected_case)
                else:
                    # Case already exists for this user
                    response_text = f"Case {detected_case} is already being tracked."
                    logger.info("Case already tracked: request_id=%s phone=%s case=%s", 
                               request_id, from_number, detected_case)
            except Exception as db_error:
                logger.error("DB error while storing case: request_id=%s error=%s", request_id, db_error)
                response_text = f"Error tracking case {detected_case}. Please try again."
        
        # Handle "list/status" action - fetch live listings for tracked cases.
        elif action == "list/status":
            try:
                user_cases = get_user_cases(from_number)
                logger.info(
                    "Fetched status data: request_id=%s phone=%s cases=%d",
                    request_id,
                    from_number,
                    len(user_cases),
                )

                if not user_cases:
                    response_text = "You are not tracking any cases yet."
                else:
                    lines = ["Your tracked cases:"]
                    api_failed = False

                    for i, case_row in enumerate(user_cases, 1):
                        case_num = str(case_row.get("case_number") or "Unknown").strip()
                        normalized_case_id = str(case_row.get("normalized_case_id") or case_num).strip()
                        court_name = str(case_row.get("court") or "").strip()
                        source_key = _resolve_live_source_key(normalized_case_id, court_name)
                        source = live_court_sources.get(source_key)

                        if not source:
                            api_failed = True
                            lines.append(f"{i}. {case_num} -> {API_UNAVAILABLE_MESSAGE}")
                            continue

                        live_entries = source.fetch_cases(today_iso())
                        live_meta = getattr(source, "last_fetch_meta", {})
                        if live_meta.get("api_status") == "failure":
                            api_failed = True
                            lines.append(f"{i}. {case_num} -> {API_UNAVAILABLE_MESSAGE}")
                            continue

                        lookup = match_case_listing(normalized_case_id, live_entries, checked_date=today_iso())
                        lines.append(
                            f"{i}. {build_case_status_message(case_num, {'api_status': 'success', 'result': lookup, 'checked_date': today_iso()})}"
                        )

                    response_text = "\n".join(lines)
                    if api_failed and len(lines) == 1:
                        response_text = API_UNAVAILABLE_MESSAGE
            except Exception as db_error:
                logger.error("DB error while fetching alerts: request_id=%s error=%s", request_id, db_error)
                response_text = "Error fetching your cases. Please try again."
        
        else:
            response_text = "I didn't understand. Try:\n- add case CRL.M.C. 123/2024\n- when is it?"
            logger.info("Fallback action: request_id=%s action=%s phone=%s", request_id, action, from_number)
        
        logger.info("WhatsApp response: request_id=%s response=%s", request_id, response_text)
        
        # Return immediately to not block Twilio
        return Response(response_text, media_type="text/plain")
        
    except Exception as e:
        logger.error("WhatsApp webhook error: request_id=%s error=%s", request_id, e, exc_info=True)
        return Response("Error processing message. Please try again.", media_type="text/plain")


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


@app.get(
    "/debug/parsed-cases",
    tags=["System"],
    summary="Debug parsed cases",
    description="Returns cached parsed entries from recent ingestion runs.",
)
def debug_parsed_cases(limit: int = 50):
    safe_limit = max(1, min(limit, 200))
    rows = get_last_parsed_entries(safe_limit)
    return {
        "count": len(rows),
        "parsed_cases": rows,
    }


@app.get(
    "/debug/tracked-cases",
    tags=["System"],
    summary="Debug tracked cases",
    description="Returns active tracked cases with normalized identifiers.",
)
def debug_tracked_cases():
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, user_phone, case_number, normalized_case_id, cnr, court, status, created_at
            FROM tracked_cases
            WHERE status = 'active'
            ORDER BY created_at DESC
            """
        ).fetchall()
        return {
            "count": len(rows),
            "tracked_cases": [dict(row) for row in rows],
        }
    finally:
        conn.close()


@app.get(
    "/debug/latest-hearings",
    tags=["System"],
    summary="Debug latest hearings",
    description="Returns the last 20 hearings from DB for ingestion diagnostics.",
)
def debug_latest_hearings():
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, normalized_case_id, cnr, hearing_date, court_name, item_number, case_title, source_pdf, created_at
            FROM hearings
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()
        return {
            "count": len(rows),
            "hearings": [dict(row) for row in rows],
        }
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


@app.get("/health", tags=["System"], summary="Health Check")
def health():
    """Returns service health status for deployment monitoring."""
    scheduler_status = get_scheduler_status()
    return {
        "status": "ok",
        "ingestion_scheduler": scheduler_status,
        "scheduler_running": scheduler_status == "running",
        "version": "v1",
    }
