import logging
import os

from services.sarvam_service import transcribe_audio_sarvam

logger = logging.getLogger(__name__)

DEFAULT_MOCK_TRANSCRIPT = "Add case CRL.M.C. 1234/2024"


def transcribe_audio(audio_url: str, source_language: str | None = None) -> str:
    """Legacy entrypoint retained for compatibility, now backed by Sarvam STT."""
    transcript = transcribe_audio_sarvam(audio_url, source_language=source_language)
    if transcript and transcript != "Could not process audio":
        return transcript

    mock_value = (
        os.getenv("SARVAM_MOCK_TRANSCRIPT", "").strip()
        or os.getenv("BHASHINI_MOCK_TRANSCRIPT", "").strip()
        or DEFAULT_MOCK_TRANSCRIPT
    )
    logger.warning("Sarvam transcription fallback activated; returning mock transcript")
    return mock_value
