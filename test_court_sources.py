import court_sources
from court_sources import HTMLCauseListSource


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, html_by_url: dict[str, str]):
        self.html_by_url = html_by_url

    def get(self, url: str, timeout: int = 20):
        if url not in self.html_by_url:
            return _FakeResponse("", 404)
        return _FakeResponse(self.html_by_url[url], 200)


def test_html_source_discovers_hierarchy_and_merges_cases():
    base = "https://ecourtsindia.com/causelist/HR/13"

    root_html = """
    <html><body>
      <select id='complex'>
        <option value='100'>District Court, Sonepat</option>
        <option value='200'>Judicial Complex, Gohana</option>
      </select>
    </body></html>
    """

    complex_100_html = """
    <html><body>
      <select id='judge'>
        <option value='501'>Sh. Azad Singh</option>
      </select>
    </body></html>
    """

    complex_200_html = """
    <html><body>
      <select id='judge'>
        <option value='601'>Sh. Example Judge</option>
      </select>
    </body></html>
    """

    cause_100_501 = """
    <html><body>
      <table>
        <tr>
          <th>Listing No</th><th>Case No</th><th>Date</th><th>Parties</th>
          <th>Court No</th><th>Advocate</th><th>Judge</th><th>Status</th>
        </tr>
        <tr>
          <td>1</td><td>CS/2312/2017</td><td>13-03-2026</td>
          <td>Anju Mangla Vs. Narain Singh</td>
          <td>30</td><td>Vijay Kumar Sharma</td><td>Sh. Azad Singh</td><td>Appearance</td>
        </tr>
      </table>
    </body></html>
    """

    cause_200_601 = """
    <html><body>
      <table>
        <tr>
          <th>Listing No</th><th>Case No</th><th>Date</th><th>Parties</th>
          <th>Court No</th><th>Advocate</th><th>Judge</th><th>Status</th>
        </tr>
        <tr>
          <td>1</td><td>MACP/458/2025</td><td>13-03-2026</td>
          <td>Chhanga Ram Vs. Narender</td>
          <td>12</td><td>Demo Advocate</td><td>Sh. Example Judge</td><td>Appearance</td>
        </tr>
      </table>
    </body></html>
    """

    html_by_url = {
        f"{base}": root_html,
        f"{base}/100": complex_100_html,
        f"{base}/200": complex_200_html,
        f"{base}/100/501/13-03-2026": cause_100_501,
        f"{base}/100/501/4-30/13-03-2026": cause_100_501,
        f"{base}/200/601/13-03-2026": cause_200_601,
        f"{base}/200/601/4-30/13-03-2026": cause_200_601,
    }

    src = HTMLCauseListSource(
        name="sonipat",
        district="Sonepat",
        base_url=base,
        timeout=5,
    )
    src.session = _FakeSession(html_by_url)

    cases = src.fetch_cases("2026-03-13")

    assert len(cases) == 2
    case_numbers = {c["case_number"] for c in cases}
    assert "CS/2312/2017" in case_numbers
    assert "MACP/458/2025" in case_numbers

    first = cases[0]
    for key in ["case_number", "title", "court_number", "judge", "status", "hearing_date", "district"]:
        assert key in first


def test_html_source_prefers_ecourts_api_when_configured(monkeypatch):
    src = HTMLCauseListSource(name="sonipat", district="Sonipat", state_code="HR", district_id=13)

    monkeypatch.setattr(court_sources, "is_ecourts_api_configured", lambda: True)
    monkeypatch.setattr(
        court_sources,
        "lookup_case_listings",
        lambda tracked, court_id, hearing_date, court_label=None: {
            "api_status": "success",
            "entries": [
                {
                    "case_number": "MACP/458/2025",
                    "party_names": "Chhanga Ram vs Narender",
                    "court_number": "12",
                    "hearing_date": hearing_date,
                    "judge": "Example Judge",
                    "status": "Listed",
                    "raw": {"case_number": "MACP/458/2025"},
                }
            ],
            "matches_found": 0,
        },
    )

    cases = src.fetch_cases("2026-04-14")

    assert len(cases) == 1
    assert cases[0]["case_number"] == "MACP/458/2025"
    assert cases[0]["title"] == "Chhanga Ram vs Narender"
    assert src.last_fetch_meta["source_mode"] == "api"
    assert src.last_fetch_meta["api_status"] == "success"
