from fastapi.testclient import TestClient

import ingestion_service
import main
import models


SYSTEM_HEADERS = {"X-System-Key": "supersecretkey"}


class _FakeCourtSource:
    def fetch_cases(self, hearing_date: str):
        return [
            {
                "case_number": "CS/2312/2017",
                "title": "Anju Mangla Vs. Narain Singh",
                "court_number": "30",
                "judge": "Sh. Azad Singh",
                "status": "Appearance",
                "hearing_date": "2026-03-13",
                "district": "Sonipat",
                "court": "District and Sessions Courts, Sonipat",
                "advocate": "Vijay Kumar Sharma",
                "raw": "Anju Mangla Vs. Narain Singh",
            },
            {
                "case_number": "MACP/458/2025",
                "title": "Chhanga Ram Vs. Narender",
                "court_number": "12",
                "judge": "Sh. Example Judge",
                "status": "Appearance",
                "hearing_date": "2026-03-13",
                "district": "Sonipat",
                "court": "District and Sessions Courts, Sonipat",
                "advocate": "Demo Advocate",
                "raw": "Chhanga Ram Vs. Narender",
            },
        ]


def test_end_to_end_webhook_ingestion_alerts(monkeypatch, tmp_path):
    # Use an isolated SQLite DB for this test run.
    test_db = tmp_path / "courtalert_e2e.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))

    # Disable scheduler side effects during app startup.
    monkeypatch.setattr(main, "start_scheduler", lambda: None)

    # Replace live court sources with deterministic fixtures.
    monkeypatch.setattr(
        ingestion_service,
        "court_sources",
        {"sonipat": _FakeCourtSource()},
    )

    with TestClient(main.app) as client:
        # 1) User tracks a case via minimal webhook schema.
        webhook_resp = client.post(
            "/webhook",
            json={
                "phone": "+919999999999",
                "message": "Add case CS/2312/2017",
            },
        )
        assert webhook_resp.status_code == 200
        assert webhook_resp.json()["status"] == "success"

        # 2) Trigger ingestion (background task route).
        ingest_resp = client.post("/system/run-ingestion", headers=SYSTEM_HEADERS)
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["status"] in {"started", "already_running"}

        # 3) Read generated alerts (no ingestion logic in this endpoint).
        alerts_resp = client.get("/alerts")
        assert alerts_resp.status_code == 200
        payload = alerts_resp.json()

        assert "count" in payload
        assert "alerts" in payload
        assert payload["count"] >= 1

        first = payload["alerts"][0]
        assert first["case_number"] == "CS/2312/2017"
        assert first["title"] == "Anju Mangla Vs. Narain Singh"
        assert first["advocate"] == "Vijay Kumar Sharma"
        assert first["court"] == "District and Sessions Courts, Sonipat"
        assert first["hearing_date"] == "2026-03-13"
        assert first["source"] == "cause_list"
