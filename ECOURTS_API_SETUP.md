# eCourts API Environment Setup

Place all eCourts API credentials in the project root `.env` file (same folder as `main.py`).

## Required

- `ECOURTS_API_URL`https://ecourtsindia.com/
- `ECOURTS_API_KEY`eci_live_4otl81ruwtog3u2gjm4gqif56e5ohhsd

If either is missing, CourtAlert automatically falls back to legacy HTML scraping for court sources.

## Optional

- `ECOURTS_API_KEY_HEADER` (default: `Authorization`)
- `ECOURTS_API_KEY_PREFIX` (default: `Bearer`)
- `ECOURTS_API_COURT_PARAM` (default: `court_id`)
- `ECOURTS_API_DATE_PARAM` (default: `date`)
- `ECOURTS_API_TIMEOUT_SECONDS` (default: `20`)
- `ECOURTS_API_RETRIES` (default: `3`)

## Example `.env` block

```env
ECOURTS_API_URL=https://example.gov/api/cause-list
ECOURTS_API_KEY=your_live_key_here
ECOURTS_API_KEY_HEADER=Authorization
ECOURTS_API_KEY_PREFIX=Bearer
ECOURTS_API_COURT_PARAM=court_id
ECOURTS_API_DATE_PARAM=date
ECOURTS_API_TIMEOUT_SECONDS=20
ECOURTS_API_RETRIES=3
```
