from abc import ABC, abstractmethod
from typing import Any


class SourceAdapter(ABC):
    """Base adapter contract for heterogeneous court-source ingestion."""

    @abstractmethod
    def fetch(self, hearing_date: str) -> Any:
        """Fetch raw source content for a hearing date."""

    @abstractmethod
    def parse(self, content: Any, hearing_date: str) -> list[dict]:
        """Parse raw source content into normalized rows."""

    def fetch_cases(self, hearing_date: str) -> list[dict]:
        content = self.fetch(hearing_date)
        return self.parse(content, hearing_date)
