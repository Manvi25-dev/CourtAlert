# CourtAlert Backend Prototype

A WhatsApp-first, backend-driven system for tracking Delhi High Court cases and sending automated alerts.

## 🚀 Overview

CourtAlert allows users to track legal cases via voice or text messages on WhatsApp. The system automatically:
1.  **Receives requests** (Voice/Text) via WhatsApp webhook.
2.  **Transcribes voice** using Bhashini API.
3.  **Stores tracked cases** in a SQLite database.
4.  **Fetches cause lists** from the Delhi High Court website.
5.  **Parses PDFs** to extract hearing details.
6.  **Matches cases** against the user's watchlist.
7.  **Sends alerts** via WhatsApp when a case is listed.

## 📂 Project Structure

```
courtalert/
├── models.py              # Database schema and operations (SQLite)
├── cause_list_fetcher.py  # Fetches and parses cause list PDFs
├── case_matcher.py        # Matches tracked cases with parsed listings
├── stt_bhashini.py        # Speech-to-Text integration (Bhashini API)
├── whatsapp_handler.py    # Mock WhatsApp webhook and message processing
├── orchestrator.py        # Main pipeline orchestration and scheduler
├── test_workflow.py       # End-to-end test suite
└── courtalert.db          # SQLite database (auto-generated)
```

## 🛠️ Setup & Usage

### 1. Install Dependencies
```bash
pip install requests pdfplumber pydantic
```

### 2. Initialize Database
The database is automatically initialized when running any module that requires it. You can also manually init it:
```bash
python3 models.py
```

### 3. Run End-to-End Test
Verify the complete workflow with sample data:
```bash
python3 test_workflow.py
```

### 4. Run the Scheduler
Start the background job to fetch cause lists and generate alerts periodically:
```bash
python3 orchestrator.py
```

## 🧩 Modules Description

### `models.py`
- **Users**: Stores WhatsApp phone numbers.
- **TrackedCases**: Stores case numbers (e.g., `CRL.M.C. 320/2026`) linked to users.
- **Hearings**: Stores parsed hearing details (Date, Bench, Item #).
- **Alerts**: Logs alerts sent to users.

### `cause_list_fetcher.py`
- Scrapes the Delhi High Court cause list page.
- Identifies Regular and Supplementary list PDFs.
- Downloads PDFs and extracts text using `pdfplumber`.
- Parses unstructured text into structured case entries.

### `case_matcher.py`
- Normalizes case numbers to handle formatting variations.
- Compares tracked cases against parsed cause list entries.
- Generates "Hearing Alert" payloads for matches.

### `stt_bhashini.py`
- Integrates with Bhashini API for Indian language speech recognition.
- Includes a mock fallback for testing without API keys.
- Extracts intent (Add Case, Status) and entities (Case Number) from text.

### `whatsapp_handler.py`
- Mocks a WhatsApp Business API webhook.
- **Secured**: Implements rate limiting and strict input validation.
- Handles incoming payloads for Text and Voice messages.
- Routes intents to appropriate backend functions.
- Returns structured JSON responses simulating WhatsApp replies.

### `security.py`
- **Rate Limiting**: Sliding window algorithm (IP: 60/min, User: 20/min).
- **Input Validation**: Pydantic schemas for strict payload validation.
- **Sanitization**: Helper functions to clean user inputs.
- **Key Management**: Secure retrieval of API keys from environment variables.

## 📝 Example Workflow

1.  **User sends voice note**: "Add case CRL.M.C. 320 of 2026"
2.  **Backend**:
    - Transcribes audio -> "Add case CRL.M.C. 320/2026"
    - Extracts case number -> `CRL.M.C. 320/2026`
    - Stores in DB linked to user's phone.
3.  **Scheduler**:
    - Downloads tomorrow's cause list PDF.
    - Parses PDF and finds `CRL.M.C. 320/2026` listed in Court No. 32.
4.  **Alert**:
    - System generates alert: "📅 Hearing Alert: Case CRL.M.C. 320/2026 listed on 19 Jan in Court 32".
    - Sends WhatsApp message to user.
