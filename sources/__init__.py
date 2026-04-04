from datetime import date

from sources.court_portal_form import CourtPortalFormAdapter
from sources.ecourts_html import ECourtsHTMLAdapter
from sources.pdf_causelist import PDFCauseListAdapter

court_sources = {
    "delhi_hc": CourtPortalFormAdapter(),
    "gurugram": PDFCauseListAdapter(district="Gurugram"),
    "sonipat": ECourtsHTMLAdapter(district="Sonepat"),
}


def today_iso() -> str:
    return date.today().isoformat()
