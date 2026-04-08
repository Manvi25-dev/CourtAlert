from typing import Any

from court_sources import HTMLCauseListSource
from sources.base import SourceAdapter


class ECourtsHTMLAdapter(SourceAdapter):
    def __init__(
        self,
        district: str = "Sonepat",
        state_code: str = "HR",
        district_id: int = 13,
        name: str = "sonipat",
    ):
        self.impl = HTMLCauseListSource(
            name=name,
            district=district,
            state_code=state_code,
            district_id=district_id,
        )

    def fetch(self, hearing_date: str) -> str:
        # HTML source performs multi-step discovery internally in fetch_cases.
        return hearing_date

    def parse(self, content: Any, hearing_date: str) -> list[dict]:
        return self.impl.fetch_cases(hearing_date)
