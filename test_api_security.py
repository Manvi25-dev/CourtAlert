import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)
SYSTEM_HEADERS = {"X-System-Key": "supersecretkey"}


def test_webhook_rejects_invalid_phone():
    response = client.post(
        "/api/v1/webhook",
        json={
            "phone": "12345",
            "message": "Add case CRL.M.C. 320/2026",
        },
    )

    assert response.status_code == 400


def test_system_route_rejects_missing_key():
    response = client.post(
        "/api/v1/system/transcribe-audio",
        json={
            "audio_base64": "UklGRg==",
            "source_language": "en",
        },
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "malicious_url",
    [
        "http://localhost:8000",
        "file:///etc/passwd",
        "http://169.254.169.254",
    ],
)
def test_transcribe_rejects_unsafe_audio_url(malicious_url: str):
    response = client.post(
        "/api/v1/system/transcribe-audio",
        headers=SYSTEM_HEADERS,
        json={
            "audio_url": malicious_url,
            "source_language": "en",
        },
    )

    assert response.status_code == 400


def test_transcribe_accepts_base64_without_url():
    response = client.post(
        "/api/v1/system/transcribe-audio",
        headers=SYSTEM_HEADERS,
        json={
            "audio_base64": "UklGRg==",
            "source_language": "en",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "ingestion_scheduler" in body
    assert body["version"] == "v1"
