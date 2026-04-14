from fastapi.testclient import TestClient

import main
import models


def test_whatsapp_webhook_returns_twiml_message(monkeypatch, tmp_path):
    test_db = tmp_path / "courtalert_twiml.db"
    monkeypatch.setattr(models, "DB_PATH", str(test_db))
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(main, "add_user", lambda phone: None)
    monkeypatch.setattr(main, "add_tracked_case", lambda phone, case: True)

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
