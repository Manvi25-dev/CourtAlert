import sqlite3
import logging
import re
import os
from datetime import datetime
from typing import List, Optional, Tuple

from alert_service import build_alert_payload
from case_parser import normalize_case_id

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_URL", "courtalert.db")


_CANONICAL_CASE_RE = re.compile(r"\b([A-Z]+)[\s/\-]+(\d+)[\s/\-]+(\d{4})\b")
_CNR_RE = re.compile(r"\b([A-Z]{3}[0-9]{13})\b")


def normalize_cnr(value: str | None) -> str | None:
    if not value:
        return None
    match = _CNR_RE.search(value.upper().strip())
    return match.group(1) if match else None


def _normalize_case_for_storage(text: str | None) -> str | None:
    if not text:
        return None

    raw = text.upper()
    match = _CANONICAL_CASE_RE.search(raw)
    if match:
        case_type, number, year = match.groups()
        return f"{case_type}/{int(number)}/{year}"

    legacy = normalize_case_id(raw)
    if not legacy:
        return None

    try:
        case_type, number, year = legacy.split("-", 2)
    except ValueError:
        return None
    return f"{case_type}/{int(number)}/{year}"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        phone_number TEXT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tracked Cases table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tracked_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_phone TEXT,
        case_number TEXT,
        normalized_case_id TEXT,
        cnr TEXT,
        court TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_phone) REFERENCES users (phone_number),
        UNIQUE(user_phone, normalized_case_id)
    )
    ''')

    # CNR-indexed canonical cases table for scalable cross-court tracking.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS cases (
        cnr TEXT PRIMARY KEY,
        case_number TEXT,
        title TEXT,
        court TEXT,
        district TEXT,
        state TEXT,
        case_type TEXT,
        registration_number TEXT,
        filing_number TEXT,
        petitioner TEXT,
        respondents TEXT,
        advocates TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Hearings table (Parsed from Cause Lists)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS hearings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        normalized_case_id TEXT,
        cnr TEXT,
        hearing_date DATE,
        court_name TEXT,
        item_number TEXT,
        case_title TEXT,
        advocate TEXT,
        raw_text TEXT,
        source_pdf TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(normalized_case_id, hearing_date)
    )
    ''')
    
    # Alerts table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_phone TEXT,
        case_id INTEGER,
        hearing_id INTEGER,
        cnr TEXT,
        case_number TEXT,
        title TEXT,
        hearing_date DATE,
        court TEXT,
        court_number TEXT,
        judge TEXT,
        status TEXT,
        district TEXT,
        source TEXT,
        priority TEXT,
        message TEXT,
        advocate TEXT,
        delivery_status TEXT DEFAULT 'pending',
        sent_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_phone) REFERENCES users (phone_number),
        FOREIGN KEY (case_id) REFERENCES tracked_cases (id),
        FOREIGN KEY (hearing_id) REFERENCES hearings (id),
        UNIQUE(user_phone, hearing_id)
    )
    ''')
    

    # Ingestion run tracking table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ingestion_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        start_time TEXT,
        end_time TEXT,
        cases_found INTEGER DEFAULT 0,
        errors TEXT,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Lightweight migration for older DB files used by legacy scripts/tests.
    tracked_cols = {row[1] for row in cursor.execute("PRAGMA table_info(tracked_cases)").fetchall()}
    if "normalized_case_id" not in tracked_cols:
        cursor.execute("ALTER TABLE tracked_cases ADD COLUMN normalized_case_id TEXT")
    if "cnr" not in tracked_cols:
        cursor.execute("ALTER TABLE tracked_cases ADD COLUMN cnr TEXT")
    if "court" not in tracked_cols:
        cursor.execute("ALTER TABLE tracked_cases ADD COLUMN court TEXT")

    alerts_cols = {row[1] for row in cursor.execute("PRAGMA table_info(alerts)").fetchall()}
    if "case_number" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN case_number TEXT")
    if "cnr" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN cnr TEXT")
    if "hearing_date" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN hearing_date DATE")
    if "court" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN court TEXT")
    if "source" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN source TEXT")
    if "title" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN title TEXT")
    if "court_number" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN court_number TEXT")
    if "judge" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN judge TEXT")
    if "district" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN district TEXT")
    if "priority" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN priority TEXT")
    if "message" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN message TEXT")
    if "advocate" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN advocate TEXT")
    if "delivery_status" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN delivery_status TEXT")
        cursor.execute(
            "UPDATE alerts SET delivery_status = CASE "
            "WHEN status IN ('pending', 'sent', 'failed') THEN status "
            "ELSE COALESCE(delivery_status, 'pending') END"
        )
    cursor.execute(
        "UPDATE alerts SET status = NULL "
        "WHERE status IN ('pending', 'sent', 'failed')"
    )

    hearing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(hearings)").fetchall()}
    if "case_title" not in hearing_cols:
        cursor.execute("ALTER TABLE hearings ADD COLUMN case_title TEXT")
    if "advocate" not in hearing_cols:
        cursor.execute("ALTER TABLE hearings ADD COLUMN advocate TEXT")
    if "cnr" not in hearing_cols:
        cursor.execute("ALTER TABLE hearings ADD COLUMN cnr TEXT")

    # Ensure scalable uniqueness constraints.
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_cnr_hearing "
        "ON alerts(cnr, hearing_date) WHERE cnr IS NOT NULL"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_case_hearing "
        "ON alerts(case_number, hearing_date) WHERE cnr IS NULL AND case_number IS NOT NULL"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_hearings_cnr_hearing "
        "ON hearings(cnr, hearing_date) WHERE cnr IS NOT NULL"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tracked_cases_user_cnr "
        "ON tracked_cases(user_phone, cnr) WHERE cnr IS NOT NULL"
    )

    conn.commit()
    conn.close()
    logger.info("Database initialized.")


def log_ingestion_run(summary: dict) -> None:
    """Persist a record of each ingestion run for operational monitoring."""
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO ingestion_runs (source, start_time, end_time, cases_found, errors, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "scheduler",
                summary.get("started_at"),
                summary.get("finished_at"),
                summary.get("entries_extracted", 0),
                str(summary.get("errors") or []),
                summary.get("status", "unknown"),
            ),
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to log ingestion run to database")
    finally:
        conn.close()

def add_user(phone_number: str):
    conn = get_db_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO users (phone_number) VALUES (?)", (phone_number,))
        conn.commit()
        return phone_number
    finally:
        conn.close()

def add_tracked_case(
    phone_number: str,
    case_number: str,
    normalized_id: Optional[str] = None,
    cnr: Optional[str] = None,
    court: Optional[str] = None,
) -> bool:
    normalized_from_case = _normalize_case_for_storage(case_number)
    normalized_from_param = _normalize_case_for_storage(normalized_id)

    canonical_case = normalized_from_case or normalized_from_param
    if not canonical_case:
        canonical_case = case_number.strip().upper()

    normalized_id = canonical_case
    cnr = normalize_cnr(cnr)

    if court and not cnr and canonical_case and "/" in canonical_case:
        normalized_id = f"{canonical_case}|{court.strip().lower()}"

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO tracked_cases (user_phone, case_number, normalized_case_id, cnr, court) "
            "VALUES (?, ?, ?, ?, ?)",
            (phone_number, canonical_case, normalized_id, cnr, court)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False # Already exists
    finally:
        conn.close()

def get_user_cases(phone_number: str) -> List[dict]:
    conn = get_db_connection()
    cases = conn.execute(
        "SELECT * FROM tracked_cases WHERE user_phone = ? AND status = 'active'",
        (phone_number,)
    ).fetchall()
    conn.close()
    return [dict(c) for c in cases]

def get_all_active_cases() -> List[str]:
    conn = get_db_connection()
    rows = conn.execute("SELECT DISTINCT normalized_case_id FROM tracked_cases WHERE status = 'active'").fetchall()
    conn.close()
    return [row['normalized_case_id'] for row in rows]


def get_all_active_cnrs() -> List[str]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT DISTINCT cnr FROM tracked_cases WHERE status = 'active' AND cnr IS NOT NULL"
    ).fetchall()
    conn.close()
    return [row["cnr"] for row in rows if row["cnr"]]


def get_all_active_case_rows() -> List[dict]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM tracked_cases WHERE status = 'active'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_hearing(
    case_id: str,
    date: str,
    court: str,
    item: str,
    raw: str,
    source: str,
    title: Optional[str] = None,
    advocate: Optional[str] = None,
    cnr: Optional[str] = None,
) -> int:
    cnr = normalize_cnr(cnr)
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            '''INSERT OR IGNORE INTO hearings 
               (normalized_case_id, cnr, hearing_date, court_name, item_number, case_title, advocate, raw_text, source_pdf) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (case_id, cnr, date, court, item, title, advocate, raw, source)
        )
        conn.commit()
        
        # If inserted, return lastrowid. If ignored, we need to fetch existing id.
        if cursor.rowcount > 0:
            return cursor.lastrowid
        else:
            row = conn.execute(
                "SELECT id FROM hearings WHERE normalized_case_id = ? AND hearing_date = ?",
                (case_id, date)
            ).fetchone()
            return row['id'] if row else None
    finally:
        conn.close()

def create_alert(
    user_phone: str,
    case_db_id: int,
    hearing_db_id: int,
    alert_payload: Optional[dict] = None,
):
    return _create_alert_record(user_phone, case_db_id, hearing_db_id, alert_payload=alert_payload)


def _create_alert_record(
    user_phone: str,
    case_db_id: int,
    hearing_db_id: int,
    alert_payload: Optional[dict] = None,
) -> bool:
    conn = get_db_connection()
    hearing = conn.execute(
        "SELECT cnr, hearing_date, court_name, source_pdf, case_title, advocate FROM hearings WHERE id = ?",
        (hearing_db_id,),
    ).fetchone()
    case_row = conn.execute(
        "SELECT case_number FROM tracked_cases WHERE id = ?",
        (case_db_id,),
    ).fetchone()

    try:
        payload = build_alert_payload(
            case_number=(alert_payload or {}).get("case_number") or (case_row["case_number"] if case_row else ""),
            cnr=(alert_payload or {}).get("cnr") or (hearing["cnr"] if hearing else None),
            title=(alert_payload or {}).get("title") or (hearing["case_title"] if hearing else None),
            court=(alert_payload or {}).get("court") or (hearing["court_name"] if hearing else None),
            court_number=(alert_payload or {}).get("court_number"),
            judge=(alert_payload or {}).get("judge"),
            status=(alert_payload or {}).get("status"),
            hearing_date=(alert_payload or {}).get("hearing_date") or (hearing["hearing_date"] if hearing else None),
            district=(alert_payload or {}).get("district"),
            source=(alert_payload or {}).get("source"),
            advocate=(alert_payload or {}).get("advocate") or (hearing["advocate"] if hearing else None),
            user_phone=user_phone,
            source_pdf=(alert_payload or {}).get("source_pdf") or (hearing["source_pdf"] if hearing else None),
        )

        cursor = conn.execute(
            "INSERT OR IGNORE INTO alerts ("
            "user_phone, case_id, hearing_id, cnr, case_number, title, court, court_number, judge, status, hearing_date, district, source, priority, message, advocate, delivery_status"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_phone,
                case_db_id,
                hearing_db_id,
                payload.get("cnr"),
                payload.get("case_number"),
                payload.get("title"),
                payload.get("court"),
                payload.get("court_number"),
                payload.get("judge"),
                payload.get("status"),
                payload.get("hearing_date"),
                payload.get("district"),
                payload.get("source"),
                payload.get("priority"),
                payload.get("message"),
                payload.get("advocate"),
                "pending",
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def create_alert_with_cnr(
    user_phone: str,
    case_db_id: int,
    hearing_db_id: int,
    cnr: Optional[str],
    hearing_date: Optional[str],
    court: Optional[str],
    source: Optional[str],
    alert_payload: Optional[dict] = None,
):
    payload = dict(alert_payload or {})
    payload.setdefault("cnr", normalize_cnr(cnr))
    payload.setdefault("hearing_date", hearing_date)
    payload.setdefault("court", court)
    payload.setdefault("source", source)
    return _create_alert_record(user_phone, case_db_id, hearing_db_id, alert_payload=payload)

def get_users_tracking_case(normalized_case_id: str) -> List[Tuple[str, int]]:
    """Returns list of (user_phone, tracked_case_id)"""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT user_phone, id FROM tracked_cases WHERE normalized_case_id = ? AND status = 'active'",
        (normalized_case_id,)
    ).fetchall()
    conn.close()
    return [(r['user_phone'], r['id']) for r in rows]


def get_users_tracking_cnr(cnr: str) -> List[Tuple[str, int]]:
    normalized = normalize_cnr(cnr)
    if not normalized:
        return []
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT user_phone, id FROM tracked_cases WHERE cnr = ? AND status = 'active'",
        (normalized,),
    ).fetchall()
    conn.close()
    return [(r["user_phone"], r["id"]) for r in rows]


def upsert_case_by_cnr(details: dict) -> Optional[str]:
    cnr = normalize_cnr(details.get("cnr"))
    if not cnr:
        return None

    conn = get_db_connection()
    try:
        conn.execute(
            '''
            INSERT INTO cases (
                cnr, case_number, title, court, district, state,
                case_type, registration_number, filing_number,
                petitioner, respondents, advocates
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cnr) DO UPDATE SET
                case_number=excluded.case_number,
                title=excluded.title,
                court=excluded.court,
                district=excluded.district,
                state=excluded.state,
                case_type=excluded.case_type,
                registration_number=excluded.registration_number,
                filing_number=excluded.filing_number,
                petitioner=excluded.petitioner,
                respondents=excluded.respondents,
                advocates=excluded.advocates
            ''',
            (
                cnr,
                details.get("case_number"),
                details.get("title"),
                details.get("court"),
                details.get("district"),
                details.get("state"),
                details.get("case_type"),
                details.get("registration_number"),
                details.get("filing_number"),
                details.get("petitioner"),
                details.get("respondents"),
                details.get("advocates"),
            ),
        )
        conn.commit()
        return cnr
    finally:
        conn.close()

def delete_advance_list_data(source_pdf: str):
    """
    Safely deletes alerts and hearings for a specific Advance Cause List PDF.
    STRICTLY limited to files containing 'adv' (case-insensitive) to protect other data.
    """
    if "adv" not in source_pdf.lower():
        logger.warning(f"Refusing to delete data for non-Advance List file: {source_pdf}")
        return

    conn = get_db_connection()
    try:
        # 1. Delete alerts associated with hearings from this source
        conn.execute('''
            DELETE FROM alerts 
            WHERE hearing_id IN (
                SELECT id FROM hearings WHERE source_pdf = ?
            )
        ''', (source_pdf,))
        
        # 2. Delete the hearings themselves
        conn.execute('DELETE FROM hearings WHERE source_pdf = ?', (source_pdf,))
        
        conn.commit()
        logger.info(f"Deleted existing data for Advance List: {source_pdf}")
    except Exception as e:
        logger.error(f"Error deleting data for {source_pdf}: {e}")
    finally:
        conn.close()


# ---------------- Legacy compatibility API ----------------

def get_connection():
    return get_db_connection()


def get_all_tracked_cases() -> List[dict]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM tracked_cases WHERE status = 'active' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tracked_cases_for_user(phone_number: str) -> List[dict]:
    return get_user_cases(phone_number)


def remove_tracked_case(phone_number: str, case_number: str) -> bool:
    normalized = normalize_case_id(case_number)
    conn = get_db_connection()
    try:
        if normalized:
            cursor = conn.execute(
                "UPDATE tracked_cases SET status = 'inactive' "
                "WHERE user_phone = ? AND normalized_case_id = ? AND status = 'active'",
                (phone_number, normalized),
            )
        else:
            cursor = conn.execute(
                "UPDATE tracked_cases SET status = 'inactive' "
                "WHERE user_phone = ? AND case_number = ? AND status = 'active'",
                (phone_number, case_number),
            )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_hearings_for_case(case_number: str) -> List[dict]:
    normalized = normalize_case_id(case_number)
    conn = get_db_connection()
    try:
        if normalized:
            rows = conn.execute(
                "SELECT * FROM hearings WHERE normalized_case_id = ? ORDER BY hearing_date DESC",
                (normalized,),
            ).fetchall()
        else:
            rows = []
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_alerts_for_user(phone_number: str) -> List[dict]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM alerts WHERE user_phone = ? ORDER BY created_at DESC",
        (phone_number,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_by_phone(phone_number: str) -> Optional[dict]:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT phone_number, created_at FROM users WHERE phone_number = ?",
        (phone_number,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None
