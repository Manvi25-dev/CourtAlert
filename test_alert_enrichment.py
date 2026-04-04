from datetime import date, timedelta

from fastapi.testclient import TestClient

import main
import models
from alert_service import build_alert_payload, classify_alert_priority, format_alert_message


def test_alert_priority_calculation():
    reference_day = date(2026, 3, 11)

    assert classify_alert_priority("2026-03-11", today=reference_day) == "today"
    assert classify_alert_priority("2026-03-12", today=reference_day) == "tomorrow"
    assert classify_alert_priority("2026-03-13", today=reference_day) == "upcoming"


def test_alert_message_formatting():
    alert = build_alert_payload(
        case_number="MACP/458/2025",
        cnr="HRS0010076892025",
        title="Chhanga Ram vs Narender",
        court="District & Sessions Court, Gurugram",
        court_number="3",
        judge="Sh. Example Judge",
        status="Evidence",
        hearing_date="2026-03-12",
        district="Gurugram",
        source="cause_list",
    )

    message = format_alert_message(alert, today=date(2026, 3, 11))
    assert "Case listed tomorrow" in message
    assert "MACP/458/2025" in message
    assert "Chhanga Ram vs Narender" in message
    assert "Court: District & Sessions Court, Gurugram" in message
    assert "Court No.: 3" in message
    assert "Judge: Sh. Example Judge" in message
    assert "Stage: Evidence" in message
    assert "Date: 12 Mar 2026" in message


def test_duplicate_alert_prevention(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_alerts.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))

    models.init_db()
    models.add_user("+919999999999")
    conn = models.get_db_connection()
    try:
        conn.execute(
            "INSERT INTO tracked_cases (user_phone, case_number, normalized_case_id, cnr, court) VALUES (?, ?, ?, ?, ?)",
            (
                "+919999999999",
                "MACP/458/2025",
                "MACP/458/2025",
                "HRS0010076892025",
                "district court, gurugram",
            ),
        )
        case_id = conn.execute("SELECT id FROM tracked_cases").fetchone()[0]
        conn.execute(
            "INSERT INTO hearings (normalized_case_id, cnr, hearing_date, court_name, item_number, case_title, advocate, raw_text, source_pdf) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "MACP/458/2025",
                "HRS0010076892025",
                "2026-03-12",
                "District & Sessions Court, Gurugram",
                "3",
                "Chhanga Ram vs Narender",
                "Demo Advocate",
                "raw",
                "cause_list.pdf",
            ),
        )
        hearing_id = conn.execute("SELECT id FROM hearings").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    payload = build_alert_payload(
        case_number="MACP/458/2025",
        cnr="HRS0010076892025",
        title="Chhanga Ram vs Narender",
        court="District & Sessions Court, Gurugram",
        court_number="3",
        judge="Sh. Example Judge",
        status="Evidence",
        hearing_date="2026-03-12",
        district="Gurugram",
        source="cause_list",
    )

    first = models.create_alert_with_cnr(
        "+919999999999",
        case_id,
        hearing_id,
        cnr="HRS0010076892025",
        hearing_date="2026-03-12",
        court="District & Sessions Court, Gurugram",
        source="cause_list",
        alert_payload=payload,
    )
    second = models.create_alert_with_cnr(
        "+919999999999",
        case_id,
        hearing_id,
        cnr="HRS0010076892025",
        hearing_date="2026-03-12",
        court="District & Sessions Court, Gurugram",
        source="cause_list",
        alert_payload=payload,
    )

    conn = models.get_db_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM alerts WHERE cnr = ? AND hearing_date = ?", ("HRS0010076892025", "2026-03-12")).fetchone()[0]
    finally:
        conn.close()

    assert first is True
    assert second is False
    assert count == 1


def test_alert_filtering_endpoint(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_alert_filter.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)

    with TestClient(main.app) as client:
        conn = models.get_db_connection()
        try:
            conn.execute(
                "INSERT INTO alerts (case_number, title, court, court_number, judge, status, hearing_date, district, source, priority, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "MACP/458/2025",
                    "Chhanga Ram vs Narender",
                    "District & Sessions Court, Gurugram",
                    "3",
                    "Sh. Example Judge",
                    "Evidence",
                    date.today().isoformat(),
                    "Gurugram",
                    "cause_list",
                    "today",
                    "Case listed today",
                ),
            )
            conn.execute(
                "INSERT INTO alerts (case_number, title, court, court_number, judge, status, hearing_date, district, source, priority, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "CS/2312/2017",
                    "Anju Mangla Vs. Narain Singh",
                    "District and Sessions Courts, Sonipat",
                    "12",
                    "Sh. Another Judge",
                    "Appearance",
                    (date.today() + timedelta(days=2)).isoformat(),
                    "Sonipat",
                    "cause_list",
                    "upcoming",
                    "Case listed upcoming",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        today_response = client.get("/alerts/today")
        assert today_response.status_code == 200
        today_payload = today_response.json()
        assert today_payload["count"] == 1
        assert today_payload["alerts"][0]["priority"] == "today"

        filtered_response = client.get("/alerts", params={"priority": "today"})
        assert filtered_response.status_code == 200
        filtered_payload = filtered_response.json()
        assert filtered_payload["count"] == 1
        assert filtered_payload["alerts"][0]["case_number"] == "MACP/458/2025"