import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None
    PlaywrightTimeoutError = Exception

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    fuzz = None


LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 3
BACKOFF_SECONDS = [1, 2, 4]
CACHE_DIR = Path("cache/ecourts")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://services.ecourts.gov.in/",
    "Connection": "keep-alive",
}

CASE_RE = re.compile(
    r"\b([A-Z][A-Z\.\(\)\-/\s]{0,30})\s*(\d{1,7})\s*[/\-]\s*(\d{4})\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(\d{2}[-/]\d{2}[-/]\d{4}|\d{4}-\d{2}-\d{2})\b")
ITEM_RE = re.compile(r"\b(?:ITEM\s*NO\.?|ITEM)\s*[:\-]?\s*(\d{1,4})\b", re.IGNORECASE)
COURT_RE = re.compile(r"\b(?:COURT\s*NO\.?|COURT\s*ROOM)\s*[:\-]?\s*(\d{1,3})\b", re.IGNORECASE)
VS_RE = re.compile(r"\b(?:vs\.?|v\.?|versus)\b", re.IGNORECASE)


def _log_event(source: str, status: Any, attempt: int, action: str, extra: Optional[dict] = None) -> None:
    payload = {
        "source": source,
        "status": status,
        "attempt": attempt,
        "action": action,
    }
    if extra:
        payload.update(extra)
    LOGGER.info(json.dumps(payload, ensure_ascii=True))


def _cache_file(source_key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", source_key)
    return CACHE_DIR / f"{safe_name}.json"


def _save_cache(source_key: str, data: dict) -> None:
    path = _cache_file(source_key)
    payload = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "data": data,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def _load_cache(source_key: str) -> Optional[dict]:
    path = _cache_file(source_key)
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj.get("data")
    except Exception:
        return None


def _is_fallback_condition(status_code: Optional[int], text: str, error: Optional[Exception]) -> bool:
    if error is not None:
        return True
    if status_code is None:
        return True
    if status_code == 403:
        return True
    if status_code >= 500:
        return True
    if not (text or "").strip():
        return True
    return False


def _response_type(content_type: str, body: str) -> str:
    ctype = (content_type or "").lower()
    if "pdf" in ctype:
        return "PDF"
    if not (body or "").strip():
        return "empty"
    return "HTML"


def _is_suspicious_html(body: str) -> bool:
    text = (body or "").strip()
    if not text:
        return True
    soup = BeautifulSoup(text, "html.parser")
    visible = soup.get_text(" ", strip=True)
    has_table = soup.find("table") is not None
    has_case_pattern = CASE_RE.search(visible or "") is not None
    # eCourts may legitimately show "no data" markers on some days.
    explicit_no_data = bool(re.search(r"no\s+(records?|data|cause\s*list)\s+(found|available)", visible, re.IGNORECASE))
    return not (has_table or has_case_pattern or explicit_no_data)


def _classify_fetch_issue(status_code: Optional[int], body: str, content_type: str, error: Optional[Exception]) -> Optional[str]:
    if error is not None:
        return "REQUEST_EXCEPTION"
    if status_code is None:
        return "NO_STATUS"
    if status_code == 403:
        return "ACCESS_BLOCKED"
    if status_code >= 500:
        return "UPSTREAM_5XX"
    if not (body or "").strip():
        return "EMPTY_RESPONSE"
    if "html" in (content_type or "").lower() and _is_suspicious_html(body):
        return "SUSPICIOUS_HTML"
    return None


def _log_fetch_attempt(
    source: str,
    attempt: int,
    method: str,
    status_code: Optional[int],
    result: str,
    issue: Optional[str] = None,
) -> None:
    payload = {
        "source": source,
        "attempt": attempt,
        "method": method,
        "status_code": status_code,
        "result": result,
    }
    if issue:
        payload["issue"] = issue
    LOGGER.info(json.dumps(payload, ensure_ascii=True))


def classify_failure(status_code: Optional[int], entries_parsed: int, access_failed: bool = False) -> Optional[str]:
    if status_code == 403:
        return "ACCESS_BLOCKED"
    if access_failed:
        return "ACCESS_FAILURE"
    if entries_parsed == 0:
        return "PARSING_FAILURE"
    return None


def _request_with_retry(
    strategy_name: str,
    source_key: str,
    func,
    retries: int = DEFAULT_RETRIES,
) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    last_status: Optional[int] = None
    last_body = ""
    last_content_type = ""
    last_content = b""
    last_issue: Optional[str] = None
    for attempt in range(1, retries + 1):
        status: Optional[int] = None
        body = ""
        content_type = ""
        content = b""
        try:
            status, body, content_type, content = func()
            last_status = status
            last_body = body
            last_content_type = content_type
            last_content = content
            issue = _classify_fetch_issue(status, body, content_type, None)
            if issue is None:
                _log_fetch_attempt(source_key, attempt, strategy_name, status, "success")
                return {
                    "ok": True,
                    "status": status,
                    "status_code": status,
                    "body": body,
                    "content_type": content_type,
                    "content": content,
                    "response_type": _response_type(content_type, body),
                    "method": strategy_name,
                    "attempt": attempt,
                }
            last_issue = issue
            _log_fetch_attempt(source_key, attempt, strategy_name, status, "fallback_triggered", issue=issue)
        except Exception as exc:
            last_error = exc
            last_issue = "REQUEST_EXCEPTION"
            _log_fetch_attempt(source_key, attempt, strategy_name, None, "fallback_triggered", issue=last_issue)

        if attempt < retries:
            time.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])

    return {
        "ok": False,
        "status": last_status,
        "status_code": last_status,
        "body": last_body,
        "content_type": last_content_type,
        "content": last_content,
        "response_type": _response_type(last_content_type, last_body),
        "method": strategy_name,
        "attempt": retries,
        "failure_reason": last_issue,
        "error": str(last_error) if last_error else "unknown_error",
    }


def fetch_direct(url: str, timeout: int = DEFAULT_TIMEOUT, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    sess = session or requests.Session()
    if "User-Agent" not in sess.headers:
        sess.headers.update(HEADERS)
    response = sess.get(url, timeout=timeout)
    return {
        "status": response.status_code,
        "text": response.text or "",
        "content_type": (response.headers.get("Content-Type") or "").lower(),
        "content": response.content,
    }


def fetch_with_session(url: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    session = requests.Session()
    session.headers.update(HEADERS)

    resp = session.get("https://services.ecourts.gov.in/", timeout=timeout)
    resp.raise_for_status()

    main_resp = session.get(url, timeout=timeout)
    return {
        "status": main_resp.status_code,
        "text": main_resp.text or "",
        "content_type": (main_resp.headers.get("Content-Type") or "").lower(),
        "content": main_resp.content,
    }


def fetch_with_browser(url: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    if sync_playwright is None:
        raise RuntimeError("playwright_not_installed")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            html = page.content()
            return {
                "status": 200,
                "text": html,
                "content_type": "text/html",
                "content": html.encode("utf-8", errors="ignore"),
            }
        except PlaywrightTimeoutError:
            return {
                "status": 408,
                "text": "",
                "content_type": "",
                "content": b"",
            }
        finally:
            context.close()
            browser.close()


def fetch_with_fallback(source_key: str, url: str, retries: int = DEFAULT_RETRIES, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    shared_session = requests.Session()
    shared_session.headers.update(HEADERS)

    methods = [
        ("requests", lambda: _direct_request(url, timeout, shared_session)),
        ("session", lambda: _session_request(url, timeout)),
        ("browser", lambda: _browser_request(url, timeout)),
    ]

    had_403 = False
    last_failure: Optional[Dict[str, Any]] = None

    for method_name, method_call in methods:
        result = _request_with_retry(method_name, source_key, method_call, retries=retries)
        if result.get("ok"):
            result["fetch_method"] = method_name
            result["access"] = "SUCCESS"
            return result
        if result.get("status_code") == 403:
            had_403 = True
        last_failure = result

    failure_reason = "ACCESS_BLOCKED" if had_403 else (last_failure or {}).get("failure_reason") or "ACCESS_FAILURE"
    return {
        "ok": False,
        "status": (last_failure or {}).get("status_code"),
        "status_code": (last_failure or {}).get("status_code"),
        "body": (last_failure or {}).get("body") or "",
        "content_type": (last_failure or {}).get("content_type") or "",
        "content": (last_failure or {}).get("content") or b"",
        "response_type": (last_failure or {}).get("response_type") or "empty",
        "method": "none",
        "fetch_method": "none",
        "attempt": (last_failure or {}).get("attempt") or retries,
        "failure_reason": failure_reason,
        "access": "FAILED",
    }


def extract_text(payload: Dict[str, Any]) -> List[str]:
    content_type = (payload.get("content_type") or "").lower()
    text = payload.get("body") or ""
    content = payload.get("content") or b""

    out: List[str] = []
    if "pdf" in content_type:
        if pdfplumber is None:
            return out
        temp_pdf = CACHE_DIR / "temp_extract.pdf"
        temp_pdf.write_bytes(content)
        with pdfplumber.open(str(temp_pdf)) as pdf:
            page_text = [p.extract_text() or "" for p in pdf.pages]
        joined = "\n".join(page_text)
        out.append(_cleanup_text(joined))
        return out

    soup = BeautifulSoup(text, "html.parser")
    out.append(_cleanup_text(soup.get_text("\n", strip=True)))

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href.lower().endswith(".pdf"):
            continue
        try:
            pdf_resp = requests.get(href, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            if pdf_resp.status_code != 200:
                continue
            if pdfplumber is None:
                continue
            temp_pdf = CACHE_DIR / "temp_link_extract.pdf"
            temp_pdf.write_bytes(pdf_resp.content)
            with pdfplumber.open(str(temp_pdf)) as pdf:
                page_text = [p.extract_text() or "" for p in pdf.pages]
            out.append(_cleanup_text("\n".join(page_text)))
        except Exception:
            continue

    return [block for block in out if block.strip()]


def _cleanup_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not re.match(r"^(page\s*\d+|cause list|district court)$", line, re.IGNORECASE)]
    merged: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if i + 1 < len(lines) and not CASE_RE.search(line) and CASE_RE.search(f"{line} {lines[i+1]}"):
            merged.append(f"{line} {lines[i+1]}")
            i += 2
            continue
        merged.append(line)
        i += 1
    return "\n".join(merged)


def normalize_case(case_number: str) -> str:
    value = (case_number or "").upper()
    return re.sub(r"\s+", "", value)


def normalize_party_name(name: str) -> str:
    text = (name or "").lower()
    text = VS_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_entries(text_blocks: List[str], hearing_date: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for block in text_blocks:
        for line in block.splitlines():
            m = CASE_RE.search(line)
            if not m:
                continue

            case_type = re.sub(r"[^A-Z0-9]", "", m.group(1).upper())
            case_no = m.group(2)
            case_year = m.group(3)
            case_number = f"{case_type}/{int(case_no)}/{case_year}"

            item_match = ITEM_RE.search(line)
            court_match = COURT_RE.search(line)
            date_match = DATE_RE.search(line)

            party_text = line[m.end():]
            party_text = re.sub(r"\b(?:ITEM|COURT|DATE)\b.*$", "", party_text, flags=re.IGNORECASE).strip(" :-")

            entries.append(
                {
                    "case_number": case_number,
                    "party_names": party_text,
                    "court_number": court_match.group(1) if court_match else "",
                    "item_number": item_match.group(1) if item_match else "",
                    "hearing_date": date_match.group(1) if date_match else hearing_date,
                }
            )
    return entries


def match_cases(tracked_cases: List[Dict[str, Any]], parsed_entries: List[Dict[str, Any]], fuzzy_threshold: int = 85) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    parsed_norm = [
        {
            "entry": e,
            "case": normalize_case(e.get("case_number", "")),
            "party": normalize_party_name(e.get("party_names", "")),
        }
        for e in parsed_entries
    ]

    for tracked in tracked_cases:
        tracked_case = normalize_case(str(tracked.get("case_number") or tracked.get("normalized_case_id") or ""))
        tracked_party = normalize_party_name(str(tracked.get("party_names") or tracked.get("title") or ""))

        exact = next((p for p in parsed_norm if p["case"] and p["case"] == tracked_case), None)
        if exact:
            matches.append(
                {
                    "tracked_case_id": tracked.get("id") or tracked_case,
                    "confidence": "HIGH",
                    "score": 100,
                    "entry": exact["entry"],
                }
            )
            continue

        if tracked_party and fuzz is not None:
            best_score = -1
            best = None
            for p in parsed_norm:
                if not p["party"]:
                    continue
                score = fuzz.token_sort_ratio(tracked_party, p["party"])
                if score > best_score:
                    best_score = score
                    best = p
            if best is not None and best_score >= fuzzy_threshold:
                matches.append(
                    {
                        "tracked_case_id": tracked.get("id") or tracked_case,
                        "confidence": "MEDIUM",
                        "score": int(best_score),
                        "entry": best["entry"],
                    }
                )

    return matches


def fetch_ecourts_causelist(
    state_code: str,
    district_id: int,
    hearing_date: Optional[str] = None,
    tracked_cases: Optional[List[Dict[str, Any]]] = None,
    retries: int = DEFAULT_RETRIES,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    hearing_date = hearing_date or datetime.utcnow().date().isoformat()
    state_code = str(state_code).upper().strip()
    source_key = f"ecourts_{state_code}_{district_id}"
    url = f"https://ecourtsindia.com/causelist/{state_code}/{district_id}"

    response = fetch_with_fallback(
        source_key=source_key,
        url=url,
        retries=retries,
        timeout=timeout,
    )

    if response.get("ok"):
        text_blocks = extract_text(response)
        parsed_entries = parse_entries(text_blocks, hearing_date)
        matches = match_cases(tracked_cases or [], parsed_entries)
        failure_classification = classify_failure(response.get("status_code"), len(parsed_entries), access_failed=False)
        payload = {
            "source": source_key,
            "url": url,
            "stale": False,
            "status": "SUCCESS",
            "access": "SUCCESS",
            "status_code": response.get("status_code"),
            "response_type": response.get("response_type"),
            "fetch_method": response.get("fetch_method") or response.get("method"),
            "failure_classification": failure_classification,
            "entries": parsed_entries,
            "matches": matches,
            "stats": {
                "total_entries_parsed": len(parsed_entries),
                "match_success_rate": (len(matches) / len(tracked_cases) * 100.0) if tracked_cases else 0.0,
            },
        }
        if parsed_entries:
            _save_cache(source_key, payload)
        _log_event(source_key, 200, 1, "parsed_entries", {"total_entries": len(parsed_entries)})
        return payload

    cached = _load_cache(source_key)
    if cached is not None:
        stale_payload = dict(cached)
        stale_payload["stale"] = True
        stale_payload["status"] = "STALE"
        stale_payload["reason"] = "ACCESS_BLOCKED"
        stale_payload["access"] = "FAILED"
        stale_payload["status_code"] = response.get("status_code")
        stale_payload["response_type"] = response.get("response_type")
        stale_payload["fetch_method"] = response.get("fetch_method")
        stale_payload["failure_classification"] = "ACCESS_BLOCKED"
        _log_event(source_key, "cache", 0, "fallback_to_cache", {"reason": stale_payload["reason"]})
        return stale_payload

    return {
        "source": source_key,
        "url": url,
        "stale": True,
        "status": "STALE",
        "reason": "ACCESS_BLOCKED",
        "access": "FAILED",
        "status_code": response.get("status_code"),
        "response_type": response.get("response_type"),
        "fetch_method": response.get("fetch_method"),
        "failure_classification": "ACCESS_BLOCKED",
        "entries": [],
        "matches": [],
        "stats": {
            "total_entries_parsed": 0,
            "match_success_rate": 0.0,
        },
    }


def _direct_request(url: str, timeout: int, session: Optional[requests.Session] = None):
    data = fetch_direct(url, timeout=timeout, session=session)
    return (
        data["status"],
        data["text"],
        data["content_type"],
        data["content"],
    )


def _session_request(url: str, timeout: int):
    data = fetch_with_session(url, timeout=timeout)
    return (
        data["status"],
        data["text"],
        data["content_type"],
        data["content"],
    )


def _browser_request(url: str, timeout: int):
    data = fetch_with_browser(url, timeout=timeout)
    return (
        data["status"],
        data["text"],
        data["content_type"],
        data["content"],
    )
