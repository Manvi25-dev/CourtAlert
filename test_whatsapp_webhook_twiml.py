from fastapi.testclient import TestClient

import main
import models


def test_whatsapp_webhook_returns_twiml_message(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_twiml.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(main, "add_user", lambda phone: None)
    monkeypatch.setattr(main, "add_tracked_case", lambda *args, **kwargs: True)

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook/whatsapp",
            data={
                "From": "whatsapp:+919111111111",
                "Body": "add case CNR:GJDH020024462018",
            },
        )

    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/xml")
    assert "<Response>" in resp.text
    assert "<Message>" in resp.text
    assert "Tracking GJDH020024462018" in resp.text


def test_whatsapp_status_for_tracked_cnr_returns_tracking_active(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_twiml_status_cnr.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(main, "fetch_case_details_by_cnr", lambda cnr: None)
    monkeypatch.setattr(
        main,
        "get_user_cases",
        lambda phone: [
            {
                "case_number": "GJDH020024462018",
                "normalized_case_id": "GJDH020024462018",
                "cnr": "GJDH020024462018",
                "court": "",
                "status": "active",
            }
        ],
    )

    with TestClient(main.app) as client:
        resp = client.post(
            "/webhook/whatsapp",
            data={
                "From": "whatsapp:+919111111111",
                "Body": "when is it?",
            },
        )

    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/xml")
    assert "No upcoming hearing date found. Please check later." in resp.text
    assert "Live data temporarily unavailable" not in resp.text
