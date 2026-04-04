from typing import Any

from court_sources import HTMLCauseListSource
from sources.base import SourceAdapter


class ECourtsHTMLAdapter(SourceAdapter):
    def __init__(self, district: str = "Sonepat", base_url: str = "https://ecourtsindia.com/causelist/HR/13"):
        self.impl = HTMLCauseListSource(name="sonipat", district=district, base_url=base_url)

    def fetch(self, hearing_date: str) -> str:
        # HTML source performs multi-step discovery internally in fetch_cases.
        return hearing_date

    def parse(self, content: Any, hearing_date: str) -> list[dict]:
        return self.impl.fetch_cases(hearing_date)
