from typing import Any

from sources.base import SourceAdapter


class CourtPortalFormAdapter(SourceAdapter):
    """Placeholder adapter for court portals requiring form post workflows."""

    def fetch(self, hearing_date: str) -> Any:
        return []

    def parse(self, content: Any, hearing_date: str) -> list[dict]:
        return []
