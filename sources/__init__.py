from datetime import date

from sources.court_portal_form import CourtPortalFormAdapter
from sources.ecourts_html import ECourtsHTMLAdapter

court_sources = {
    "delhi_hc": CourtPortalFormAdapter(),
    "gurugram": ECourtsHTMLAdapter(district="Gurugram", state_code="HR", district_id=6, name="gurugram"),
    "sonipat": ECourtsHTMLAdapter(district="Sonepat", state_code="HR", district_id=13, name="sonipat"),
}


def today_iso() -> str:
    return date.today().isoformat()
