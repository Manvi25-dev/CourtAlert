from fastapi.testclient import TestClient

import ingestion_service
import main
import models
import whatsapp_handler


SYSTEM_HEADERS = {"X-System-Key": "supersecretkey"}


class _FakeCourtSource:
    def fetch_cases(self, hearing_date: str):
        return [
            {
                "cnr": "HRS0010076892025",
                "case_number": "MACP/458/2025",
                "title": "Chhanga Ram vs Narender",
                "court": "District and Sessions Court, Gurugram",
                "court_number": "12",
                "judge": "Sh. Example Judge",
                "status": "Appearance",
                "district": "Gurugram",
                "hearing_date": "2026-03-13",
                "advocate": "Demo Advocate",
                "raw": "Chhanga Ram vs Narender",
            }
        ]


def test_end_to_end_cnr_tracking(monkeypatch, tmp_path):
    # Isolate DB.
    test_db = tmp_path / "courtalert_cnr_e2e.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))

    # Disable background scheduler side effects.
    monkeypatch.setattr(main, "start_scheduler", lambda: None)

    # Deterministic CNR metadata response.
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
            "case_type": "MACP",
            "registration_number": "458/2025",
            "filing_number": "123/2025",
            "petitioner": "Chhanga Ram",
            "respondents": "Narender",
            "advocates": "Demo Advocate",
        },
    )

    monkeypatch.setattr(
        ingestion_service,
        "court_sources",
        {"fake": _FakeCourtSource()},
    )

    with TestClient(main.app) as client:
        # Add by CNR.
        webhook = client.post(
            "/webhook",
            json={
                "phone": "+918888888888",
                "message": "Add case HRS0010076892025",
            },
        )
        assert webhook.status_code == 200

        # Trigger ingestion and matching.
        ingest = client.post("/system/run-ingestion", headers=SYSTEM_HEADERS)
        assert ingest.status_code == 200

        # Verify alert includes CNR.
        alerts = client.get("/alerts")
        assert alerts.status_code == 200
        payload = alerts.json()
        assert payload["count"] >= 1
        first = payload["alerts"][0]
        assert first["cnr"] == "HRS0010076892025"
        assert first["case_number"] == "MACP/458/2025"
        assert first["court"] == "District and Sessions Court, Gurugram"
        assert first["title"] == "Chhanga Ram vs Narender"
