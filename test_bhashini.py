import base64

import stt_bhashini


class DummyResponse:
    def __init__(self, payload=None, content=b""):
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_transcribe_audio_falls_back_to_mock_when_not_configured(monkeypatch):
    monkeypatch.delenv("BHASHINI_COMPUTE_URL", raising=False)
    monkeypatch.delenv("BHASHINI_SERVICE_ID", raising=False)
    monkeypatch.delenv("BHASHINI_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("BHASHINI_PIPELINE_ID", raising=False)
    monkeypatch.delenv("BHASHINI_USER_ID", raising=False)
    monkeypatch.delenv("BHASHINI_API_KEY", raising=False)
    monkeypatch.setenv("BHASHINI_MOCK_TRANSCRIPT", "mocked transcript")

    assert stt_bhashini.transcribe_audio("https://example.com/audio.wav") == "mocked transcript"


def test_transcribe_audio_uses_direct_compute_config(monkeypatch):
    monkeypatch.setenv("BHASHINI_COMPUTE_URL", "https://example.com/compute")
    monkeypatch.setenv("BHASHINI_SERVICE_ID", "asr-service")
    monkeypatch.setenv("BHASHINI_INFERENCE_API_KEY", "secret")
    monkeypatch.setenv("BHASHINI_INFERENCE_API_HEADER", "Authorization")
    monkeypatch.setenv("BHASHINI_SOURCE_LANGUAGE", "en")
    monkeypatch.setenv("BHASHINI_AUDIO_FORMAT", "wav")
    monkeypatch.setenv("BHASHINI_SAMPLING_RATE", "16000")

    captured = {}

    def fake_get(url, timeout):
        captured["audio_url"] = url
        captured["audio_timeout"] = timeout
        return DummyResponse(content=b"audio-bytes")

    def fake_post(url, headers, json, timeout):
        captured["compute_url"] = url
        captured["headers"] = headers
        captured["payload"] = json
        captured["compute_timeout"] = timeout
        return DummyResponse(
            payload={
                "pipelineResponse": [
                    {
                        "output": [
                            {"source": "Add case CRL.M.C. 320/2026"}
                        ]
                    }
                ]
            }
        )

    monkeypatch.setattr(stt_bhashini.requests, "get", fake_get)
    monkeypatch.setattr(stt_bhashini.requests, "post", fake_post)

    transcript = stt_bhashini.transcribe_audio("https://example.com/audio.wav")

    assert transcript == "Add case CRL.M.C. 320/2026"
    assert captured["audio_url"] == "https://example.com/audio.wav"
    assert captured["compute_url"] == "https://example.com/compute"
    assert captured["headers"]["Authorization"] == "secret"
    assert captured["payload"]["pipelineTasks"][0]["config"]["serviceId"] == "asr-service"
    assert captured["payload"]["inputData"]["audio"][0]["audioContent"] == base64.b64encode(b"audio-bytes").decode("ascii")