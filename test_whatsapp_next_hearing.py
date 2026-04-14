from fastapi.testclient import TestClient

import main
import models


def test_next_hearing_query_no_tracked_case(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_next_hearing_none.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(main, "get_user_cases", lambda phone: [])

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+919000000001", "Body": "when is it?"},
        )

    assert resp.status_code == 200
    assert "No case found. Please add a case first." in resp.text


def test_next_hearing_query_multiple_cases_prompts_selection(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_next_hearing_multi.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(
        main,
        "get_user_cases",
        lambda phone: [
            {"id": 1, "case_number": "GJDH020024462018", "cnr": "GJDH020024462018", "created_at": "2026-04-13T10:00:00"},
            {"id": 2, "case_number": "HRS0010076892025", "cnr": "HRS0010076892025", "created_at": "2026-04-14T10:00:00"},
        ],
    )

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+919000000002", "Body": "next date?"},
        )

    assert resp.status_code == 200
    assert "Which case? Reply with case number." in resp.text


def test_next_hearing_query_returns_compact_hearing_message(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_next_hearing_single.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(
        main,
        "get_user_cases",
        lambda phone: [
            {
                "id": 2,
                "case_number": "GJDH020024462018",
                "cnr": "GJDH020024462018",
                "created_at": "2026-04-14T10:00:00",
            }
        ],
    )
    monkeypatch.setattr(
        main,
        "fetch_case_details_by_cnr",
        lambda cnr: {
            "cnr": cnr,
            "title": "Rakesh Chatterjee vs Hector Realty",
            "court": "Gurugram District Court",
            "next_hearing_date": "22 Apr 2026",
        },
    )

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+919000000003", "Body": "hearing kab hai?"},
        )

    assert resp.status_code == 200
    assert "Next hearing for Rakesh Chatterjee vs Hector Realty is on 22 Apr 2026 at Gurugram District Court" in resp.text


def test_next_hearing_query_without_upcoming_date(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_next_hearing_missing_date.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(
        main,
        "get_user_cases",
        lambda phone: [
            {
                "id": 3,
                "case_number": "GJDH020024462018",
                "cnr": "GJDH020024462018",
                "created_at": "2026-04-14T11:00:00",
            }
        ],
    )
    monkeypatch.setattr(main, "fetch_case_details_by_cnr", lambda cnr: {"cnr": cnr, "title": "Case Title", "court": "Court Name"})

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+919000000004", "Body": "when is it?"},
        )

    assert resp.status_code == 200
    assert "No upcoming hearing date found. Please check later." in resp.text
