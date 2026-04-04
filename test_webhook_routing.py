import models
import main
import whatsapp_handler

from fastapi.testclient import TestClient


def test_webhook_routes_bare_cnr_as_add(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_route_cnr.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)

    monkeypatch.setattr(
        whatsapp_handler,
        "fetch_case_details_by_cnr",
        lambda cnr: {
            "cnr": "HRS0010076892025",
            "case_number": "MACP/458/2025",
            "title": "Chhanga Ram vs Narender",
            "court": "District and Sessions Court, Gurugram",
            "district": "Gurugram",
            "state": "Haryana",
        },
    )

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook",
            json={"phone": "+919111111111", "message": " HRS0010076892025 "},
        )
        assert resp.status_code == 200
        text = resp.json()["response"]
        assert "Case detected: HRS0010076892025" in text
        assert "Fetching details..." in text


def test_webhook_routes_bare_case_number_as_add(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_route_case.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook",
            json={"phone": "+919222222222", "message": "  MACP/458/2025  "},
        )
        assert resp.status_code == 200
        text = resp.json()["response"]
        assert "Case detected: MACP/458/2025" in text
        assert "Fetching details..." in text


def test_webhook_routes_explicit_add_command(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_route_add_command.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook",
            json={"phone": "+919444444444", "message": "Add case CRL.M.C. 1234/2024"},
        )
        assert resp.status_code == 200
        text = resp.json()["response"]
        assert "Started tracking" in text or "Already tracking" in text


def test_webhook_routes_check_command(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_route_check_command.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook",
            json={"phone": "+919555555555", "message": "Check status"},
        )
        assert resp.status_code == 200
        text = resp.json()["response"]
        assert "tracking" in text.lower()


def test_webhook_help_when_no_identifier_or_command(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_route_help.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook",
            json={"phone": "+919333333333", "message": "hello"},
        )
        assert resp.status_code == 200
        text = resp.json()["response"]
        assert "Welcome to CourtAlert." in text
        assert "CNR number (HRS0010076892025)" in text
