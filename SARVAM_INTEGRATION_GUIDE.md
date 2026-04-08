# Sarvam API Integration for WhatsApp Legal Assistant

## Goal
Understand ANY user message and convert it into structured actions with minimal rejection.

---

## STEP 1: INPUT

User messages processed:

```
"add case CNR:GJDH020024462018"
"when is it?"
"LPA 171/2019"
"track this"
```

Context passed to Sarvam:

```json
{
  "tracked_cases": ["LPA/171/2019", "CRL.M.C. 320/2026"],
  "last_case": "LPA/171/2019",
  "last_action": "tracked"
}
```

---

## STEP 2: SARVAM LLM REQUEST

**Location:** `services/sarvam_service.py` → `extract_intent_with_confidence()`

```python
prompt = f"""You are an intelligent legal assistant for Indian court case tracking.

ANALYZE this user message and return STRICT JSON with intent and case identifier.

USER CONTEXT:
- Currently tracking: {tracked}
- Last accessed case: {last_case}
- Last action: {last_action}

USER MESSAGE: "{message_text}"

TASK:
1. Identify primary INTENT
2. Extract CASE_IDENTIFIER (CNR or case number)
3. Identify CASE_TYPE (CNR, CASE_NUMBER, or NONE)
4. Assess CONFIDENCE (0-1) based on message clarity

INTENT CLASSIFICATION:
- TRACK_CASE: User wants to add/track a new case
- QUERY_STATUS: User asks "when", "status", "hearing date"
- LIST_CASES: User wants to see tracked cases
- REMOVE_CASE: User wants to delete/stop tracking
- UNKNOWN: Ambiguous or unclear intent

CASE IDENTIFIER RULES:
- CNR: 16 alphanumeric chars (GJDH020024462018)
- CASE_NUMBER: LPA 171/2019, CRL.M.C. 320/2026, case 171 of 2019
- Accept flexible formats
- If "when is it?" with tracked cases → use context

RETURN ONLY valid JSON:
{
  "intent": "TRACK_CASE|QUERY_STATUS|LIST_CASES|REMOVE_CASE|UNKNOWN",
  "case_identifier": "GJDH020024462018 or LPA/171/2019 or null",
  "case_type": "CNR|CASE_NUMBER|NONE",
  "confidence": 0.90,
  "entities": {
    "case_number": "...",
    "court": "...",
    "action_type": "add|remove|list|check"
  },
  "reasoning": "explanation",
  "suggested_next_action": "actionable directive"
}"""

payload = {
    "model": "sarvam-m",
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.2,      # Low for consistency
    "max_tokens": 400
}

response = requests.post(
    SARVAM_LLM_URL,
    headers={"Authorization": f"Bearer {SARVAM_API_KEY}"},
    json=payload,
    timeout=4
)
```

---

## STEP 3: RESPONSE PARSING

**Strict JSON Response:**

```python
{
    "intent": "TRACK_CASE",           # One of 5 valid intents
    "case_identifier": "LPA/171/2019", # Extracted case/CNR or None
    "case_type": "CASE_NUMBER",        # CNR | CASE_NUMBER | NONE
    "confidence": 0.92,                # 0.0 - 1.0
    "entities": {
        "case_number": "LPA/171/2019",
        "court": null,
        "action_type": "add"
    },
    "reasoning": "User explicitly asked to track a case number",
    "suggested_next_action": "add_case"
}
```

**Confidence Scoring:**

| Range | Meaning |
|-------|---------|
| 0.95+ | Clear case + explicit intent |
| 0.85-0.94 | Case present, phrasing loose |
| 0.70-0.84 | Weak signals, ambiguous |
| 0.50-0.69 | Very unclear |
| <0.50 | No recognizable pattern |

---

## STEP 4: DECISION ROUTING

**Location:** `whatsapp_handler.py` → `decide_next_best_action()`

```python
def decide_next_best_action(phone: str, message: str) -> dict:
    user_context = _get_user_context(phone)
    
    # Call Sarvam with context
    intent_result = extract_intent_with_confidence(message, user_context)
    intent = intent_result.get("intent", "UNKNOWN")
    case_identifier = intent_result.get("case_identifier")
    confidence = intent_result.get("confidence", 0.0)
    case_type = intent_result.get("case_type")
    
    # Fallback to regex if Sarvam confidence low
    if confidence < 0.6 or intent == "UNKNOWN":
        extracted = _extract_identifiers_flexible(message)
        case_identifier = case_identifier or extracted.get("resolved_identifier")
        intent = _fallback_intent(message, extracted.get("case_like"))
    
    # Route based on intent
    if intent == "TRACK_CASE" and confidence > 0.6:
        return handle_track_case(phone, case_identifier)
    
    elif intent == "QUERY_STATUS" and confidence > 0.6:
        return handle_query_status(phone, case_identifier)
    
    elif intent == "LIST_CASES" and confidence > 0.6:
        return handle_list_cases(phone)
    
    elif intent == "REMOVE_CASE" and confidence > 0.6:
        return handle_remove_case(phone, case_identifier)
    
    else:
        return {"intent": "UNKNOWN", "response": WELCOME_MESSAGE}
```

---

## STEP 5: ACTION HANDLERS

### Track Case
```python
if intent == "TRACK_CASE":
    # Add to database, validate format
    response = handle_add_case(phone, f"Add case {case_identifier}")
    
    # Enhance response based on extraction quality
    if case_type == "CNR":
        response = f"Got it. Tracking case {case_identifier}."
    elif extracted.get("inferred_from_loose"):
        response = f"Did you mean case {suggestion}? I started tracking it."
    
    return {
        "intent": "TRACK_CASE",
        "confidence": confidence,
        "case_number": case_identifier,
        "response": response,
        "action_taken": "case_added_to_tracking"
    }
```

### Query Status
```python
if intent == "QUERY_STATUS":
    # Use case_identifier or fallback to last_case from context
    query_case = case_identifier or tracked_cases[0]
    
    # Live lookup from API/scraper
    source = court_sources.get(resolve_court_from_case(query_case))
    live_entries = source.fetch_cases(today_iso())
    
    match = match_case_listing(query_case, live_entries)
    response = build_case_status_message(query_case, match)
    
    return {
        "intent": "QUERY_STATUS",
        "confidence": confidence,
        "case_number": query_case,
        "response": response,
        "action_taken": "fetch_case_status"
    }
```

### List Cases
```python
if intent == "LIST_CASES":
    return {
        "intent": "LIST_CASES",
        "response": handle_list_cases(phone),
        "action_taken": "list_cases_retrieved"
    }
```

### Remove Case
```python
if intent == "REMOVE_CASE":
    case_to_remove = case_identifier or extracted.get("resolved_identifier")
    
    return {
        "intent": "REMOVE_CASE",
        "case_number": case_to_remove,
        "response": handle_remove_case(phone, f"Remove {case_to_remove}"),
        "action_taken": "case_removed_from_tracking"
    }
```

---

## STEP 6: FALLBACK REGEX PARSING

When Sarvam confidence < 0.6 or API unavailable:

```python
def _extract_identifiers_flexible(message: str) -> dict:
    text_upper = message.upper()
    
    # CNR: 16 alphanumeric
    cnr_match = _CNR_FLEX_RE.search(text_upper)
    normalized_cnr = extract_and_normalize(cnr_match)
    
    # Case: "LPA 171/2019", "case 171 of 2019"
    case_match = _CASE_FLEX_RE.search(text_upper)
    normalized_case = extract_and_normalize(case_match)
    
    # Loose: "171 of 2019"
    loose_match = _LOOSE_NUM_YEAR_RE.search(text_upper)
    inferred_case = infer_from_tracked(loose_match)
    
    return {
        "resolved_identifier": normalized_cnr or normalized_case or inferred_case,
        "identifier_type": "CNR" if normalized_cnr else "CASE_NUMBER",
        "case_like": bool(resolved_identifier),
        "inferred_from_loose": inferred_case is not None
    }
```

---

## STEP 7: RESPONSE

All handlers return:

```python
{
    "intent": "TRACK_CASE|QUERY_STATUS|LIST_CASES|REMOVE_CASE|UNKNOWN",
    "confidence": 0.95,
    "case_number": "LPA/171/2019",
    "response": "Human-friendly message sent to user",
    "action_taken": "system_action_identifier"
}
```

---

## ENVIRONMENT VARIABLES

```bash
# .env
SARVAM_API_KEY=sk_<your-key>
SARVAM_LLM_URL=https://api.sarvam.ai/v1/chat/completions
SARVAM_LLM_MODEL=sarvam-m
SARVAM_TIMEOUT_SECONDS=4
```

---

## Example Flows

### ✅ Clear Format
```
User: "add case LPA 171/2019"

Sarvam: {
  "intent": "TRACK_CASE",
  "case_identifier": "LPA/171/2019",
  "case_type": "CASE_NUMBER",
  "confidence": 0.95
}

→ Track case → "Got it. Tracking LPA/171/2019."
```

### ✅ CNR
```
User: "CNR:GJDH020024462018"

Sarvam: {
  "intent": "TRACK_CASE",
  "case_identifier": "GJDH020024462018",
  "case_type": "CNR",
  "confidence": 0.98
}

→ Track case → "Got it. Tracking GJDH020024462018."
```

### ✅ Context-Aware
```
User: "when is it?"
Context: {"tracked_cases": ["LPA/171/2019"]}

Sarvam: {
  "intent": "QUERY_STATUS",
  "case_identifier": "LPA/171/2019",
  "confidence": 0.88
}

→ Live lookup → "Next hearing: 2026-04-15, Court #2"
```

### ↩️ Loose Format (Fallback)
```
User: "case 171 of 2019"

Sarvam: {
  "intent": "UNKNOWN",
  "confidence": 0.45
}

Regex fallback: "case 171 of 2019" → CASE_NUMBER

→ Track inferred → "Did you mean case 171/2019? I started tracking it."
```

### ❌ No Pattern
```
User: "hello there"

Sarvam: {
  "intent": "UNKNOWN",
  "case_identifier": null,
  "confidence": 0.2
}

→ No action → "Welcome to CourtAlert..."
```

---

## Testing

```bash
# Flexible input tests
python -m pytest test_whatsapp_flexible_input.py -v

# Sarvam structure tests
python -m pytest test_sarvam_structured_intent.py -v

# All WhatsApp tests
python -m pytest test_whatsapp_flexible_input.py test_sarvam_structured_intent.py -v
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER (WhatsApp)                              │
│              Voice Message / Text Message                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────┐
        │  Twilio Webhook (WhatsApp API) │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │ process_whatsapp_message()     │
        │ - Validate webhook              │
        │ - Handle voice (STT)            │
        │ - Extract text                  │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │ Sarvam STT (if audio)          │
        │ Returns: transcript text        │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────────────┐
        │ decide_next_best_action()              │
        │ ┌──────────────────────────────────────┤
        │ │ 1. Get user context                  │
        │ │ 2. SARVAM INTENT EXTRACTION          │
        │ │    ├─ confidence >= 0.6 ? YES        │
        │ │    │  └─ Use Sarvam result           │
        │ │    └─ confidence < 0.6 ? NO          │
        │ │       └─ Fallback to regex           │
        │ │ 3. Route to action handler           │
        │ └──────────────────────────────────────┘
        └────────────┬───────────────────────────┘
                     │
              ┌──────┴──────┬─────────┬─────────┐
              ▼             ▼         ▼         ▼
        TRACK_CASE   QUERY_STATUS LIST_CASES  REMOVE_CASE
        (add db)     (live lookup) (show all) (delete db)
              │             │         │         │
              └──────────────┴─────────┴─────────┘
                             │
                             ▼
        ┌────────────────────────────────┐
        │ send_whatsapp_response()       │
        │ → User receives message        │
        └────────────────────────────────┘
```

---

## Integration Points

| Component | File | Purpose |
|-----------|------|---------|
| Sarvam Service | `services/sarvam_service.py` | LLM API, JSON parsing, response formatting |
| WhatsApp Handler | `whatsapp_handler.py` | Intent routing, action handlers, fallback logic |
| Case Matcher | `case_matcher.py` | Case normalization, format validation |
| Court Sources | `court_sources.py` | Live data fetching (API-first) |
| Models | `models.py` | Database (case tracking, users) |
| Main | `main.py` | Webhook endpoint, payload processing |

---

## Key Principles

✅ **Accept Anything** - Minimal hard rejections
✅ **Infer When Possible** - Use context and fallback patterns
✅ **Soft Confirmations** - Clarify ambiguous cases without blocking
✅ **Context-Aware** - Remember tracked cases and intent history
✅ **Two-Layer Parsing** - LLM primary, regex fallback
✅ **Structured Output** - Always return intent, case_identifier, case_type


        │ │    - Route by intent type            │
        │ │    - Check confidence threshold      │
        │ │    - Apply smart inference           │
        │ │    - Handle missing info             │
        │ │                                      │
        │ │ 4. Execute action                    │
        │ │    - Database operation              │
        │ │    - Status query                    │
        │ │    - Clarification prompt            │
        │ └──────────────────────────────────────┤
        └────────────┬───────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │  Database Operations           │
        │  - add_tracked_case()          │
        │  - remove_tracked_case()       │
        │  - get_user_cases()            │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │  Format Response               │
        │  - Plain text (no markdown)    │
        │  - WhatsApp-ready tone         │
        │  - Emojis for clarity          │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │  Return to Twilio              │
        │  - Send as WhatsApp message    │
        │  - Back to user phone          │
        └────────────────────────────────┘
```

## Intent Types & Decision Logic

### 1. TRACK_CASE
**User wants to add a case to tracking**

```
Intent: TRACK_CASE
Confidence: 0.95
Entities:
  - case_number: "CRL.M.C./1234/2024"
  
Decision Engine Flow:
  ✓ If case_number extracted:
    → validate case format
    → add_tracked_case(phone, case_number)
    → "✅ Started tracking: CRL.M.C./1234/2024"
    
  ✗ If case_number missing:
    → "Please share case number like: CRL.M.C./1234/2024"
    
Examples:
  User: "LPA/171/2019"               → Auto-detect case number
  User: "Track CRL.M.C./1234/2024"   → Extract from command
  User: "Add case to tracking"        → Prompt for case number
```

### 2. QUERY_STATUS
**User wants to know case status/hearing date**

```
Intent: QUERY_STATUS
Confidence: 0.90
Entities:
  - case_number: "CRL.M.C./1234/2024" (may be None)
  
Decision Engine Flow:
  ✓ If case_number in message:
    → fetch_case_status(case_number)
    → "Listed: Item No. 5 | Court No. 15 | Hearing: 15 Jan 2024"
    
  ✓ If case_number NOT in message BUT user has tracked cases:
    → SMART INFERENCE: Use last/first tracked case
    → "Checking {inferred_case}..."
    → fetch_case_status(inferred_case)
    
  ✗ If no case specified AND no tracked cases:
    → "Which case? Please share case number or track first."
    
Examples:
  User: "When is my hearing?"        → Infer from tracked cases
  User: "Status of CRL.M.C./1234?"   → Use specified case
  User: "Is it listed?"              → Smart inference + status
```

### 3. LIST_CASES
**User wants to see all tracked cases**

```
Intent: LIST_CASES
Confidence: 0.92
Entities:
  - action_type: "list"
  
Decision Engine Flow:
  ✓ If user has tracked cases:
    → get_user_cases(phone)
    → Return formatted list with status
    
  ✗ If no tracked cases:
    → "You're not tracking any cases yet.
       Share a case number to get started."
    
Examples:
  User: "Show my cases"
  User: "What am I tracking?"
  User: "List cases"
```

### 4. REMOVE_CASE
**User wants to stop tracking a case**

```
Intent: REMOVE_CASE
Confidence: 0.88
Entities:
  - case_number: "CRL.M.C./1234/2024" (may be None)
  
Decision Engine Flow:
  ✓ If case_number specified:
    → remove_tracked_case(phone, case_number)
    → "Removed: CRL.M.C./1234/2024"
    
  ✗ If case_number NOT specified:
    → "Which case to remove?
       You're tracking: [list]"
    
Examples:
  User: "Remove CRL.M.C./1234/2024"
  User: "Stop tracking case LPA/171/2019"
  User: "Delete" (needs clarification)
```

### 5. UNCLEAR
**Intent is ambiguous or system confidence is low**

```
Intent: UNCLEAR
Confidence: 0.45
Entities:
  - (various, but low confidence)
  
Decision Engine Flow:
  ✓ If message looks like case number (regex match):
    → HIGH confidence pattern match
    → "Detected case: LPA/171/2019"
    
  ✗ Otherwise:
    → Show WELCOME_MESSAGE with instructions
    → Offer quick command examples
    
Examples:
  User: "Hello"                      → Show help
  User: "Random text"                → Prompt for valid input
  User: "Tell me about law"          → Outside scope, show help
```

## Smart Inference & Context

### "When is it?" Problem
User asks "when is it?" but system doesn't know which case.

**Solution: Context-aware inference**

```python
# User has tracked cases
user_context = {
    "tracked_cases": ["CRL.M.C./1234/2024", "LPA/171/2019"],
    "last_query": "CRL.M.C./1234/2024",
    "last_action": "TRACK_CASE"
}

# User message: "when is it?"
# Sarvam extracts: intent=QUERY_STATUS, case_number=None

# Decision engine:
if not case_number and tracked_cases:
    inferred_case = tracked_cases[0]  # Use most recent
    return {
        "intent": "QUERY_STATUS",
        "case_number": inferred_case,  # INFERRED
        "action_taken": "inferred_case_from_context",
        "response": f"Checking {inferred_case}..."
    }
```

### Pattern-Based Fallback
If Sarvam confidence is low, use regex patterns:

```python
# User: "LPA/171/2019"
# Sarvam: confidence=0.4 (uncertain)
# BUT: Regex pattern matches 100% case format

if extract_case_number(message):  # Regex match
    return {
        "intent": "TRACK_CASE",
        "confidence": 0.95,  # Override with pattern confidence
        "case_number": extracted,
        "action_taken": "case_number_pattern_detected"
    }
```

## Entity Extraction

Sarvam extracts structured data from user messages:

```json
{
  "entities": {
    "case_number": "CRL.M.C./1234/2024 or null",
    "court": "Delhi High Court or null",
    "action_type": "add|remove|list|check|none"
  }
}
```

**Examples:**

| User Message | Case Number Extracted | Court Extracted | Action Type |
|---|---|---|---|
| "Track CRL.M.C./1234/2024" | CRL.M.C./1234/2024 | None | add |
| "Delhi HC case LPA/171" | LPA/171 | Delhi High Court | check |
| "Remove from Delhi District" | None | Delhi District | remove |
| "What cases?" | None | None | list |

## Confidence Scoring

Sarvam returns confidence 0.0-1.0 for each intent:

```
Confidence 0.9-1.0:  ✅ High confidence → Execute action immediately
  - User: "Track LPA/171/2019"
  
Confidence 0.6-0.9:  ⚠️  Medium confidence → Confirm before acting
  - User: "Can you check my case?"
  
Confidence 0.0-0.6:  ❌ Low confidence → Ask for clarification
  - User: "Hello"
```

## Response Examples

### Track Case Success
```
User: "LPA/171/2019"
System: "✅ Started tracking: LPA/171/2019
         I'll alert you when it's listed in court."
```

### Smart Inference (Status Query)
```
User: "When is the hearing?"
System: "Checking CRL.M.C./1234/2024...
         Listed: ✅ Item 5 | Court 15
         Hearing: Next Monday, 10:30 AM"
```

### Missing Info (Prompt)
```
User: "Remove case"
System: "Which case? You're tracking:
         • CRL.M.C./1234/2024
         • LPA/171/2019
         
         Reply: Remove CRL.M.C./1234/2024"
```

### Clarification (Low Confidence)
```
User: "Hello there"
System: "Welcome to CourtAlert!

         Send:
         • Case number (CRL.M.C./1234/2024)
         • Commands: check, list, remove
         • Status updates automatically sent"
```

## Integration Points

### 1. Twilio Webhook
```python
POST /webhook/whatsapp
{
    "user_phone_number": "whatsapp:+919876543210",
    "message_type": "text",  # or "voice", "audio"
    "message_content": "Track LPA/171/2019"
}

Returns:
{
    "status": "success",
    "response": {
        "message_text": "✅ Started tracking: LPA/171/2019"
    }
}
```

### 2. Sarvam LLM API
```python
POST https://api.sarvam.ai/v1/chat/completions
{
    "model": "sarvam-m",
    "messages": [{
        "role": "user",
        "content": "Extract intent from: 'Track LPA/171/2019'"
    }],
    "temperature": 0.3,
    "max_tokens": 300
}

Returns:
{
    "choices": [{
        "message": {
            "content": "{\"intent\": \"TRACK_CASE\", ...}"
        }
    }]
}
```

### 3. Database
```python
add_tracked_case(phone="...", case_number="LPA/171/2019")
get_user_cases(phone="...")
remove_tracked_case(phone="...", case_number="...")
```

### 4. Court Ingestion Pipeline
```python
# When QUERY_STATUS triggers:
from ecourts_pipeline import fetch_ecourts_causelist

result = fetch_ecourts_causelist(
    state_code="DL",
    district_id="1",
    case_list=[inferred_case]
)
```

## Testing

### Unit Test Script
```bash
python test_sarvam_decision_engine.py
```

### Manual Testing
```python
from whatsapp_handler import process_message_with_decision_details

result = process_message_with_decision_details(
    phone="+919876543210",
    message="Track LPA/171/2019"
)

print(result)
# {
#     "user_phone": "+919876543210",
#     "message": "Track LPA/171/2019",
#     "decision": {
#         "intent": "TRACK_CASE",
#         "confidence": 0.95,
#         "case_number": "LPA/171/2019",
#         "action_taken": "case_added_to_tracking"
#     },
#     "response": "✅ Started tracking: LPA/171/2019"
# }
```

## Error Handling & Fallbacks

| Scenario | Fallback |
|---|---|
| Sarvam API timeout | Use regex-based intent detection |
| Low confidence intent | Ask clarification + show help |
| Missing case number | Prompt user for input or suggest from context |
| Database error | Return error message + retry option |
| Invalid case format | Suggest correct format |

## Next Steps

1. **Context Persistence**: Store `last_action`, `last_query` in DB
2. **Hearing Notifications**: Real-time alerts when case is listed
3. **Multi-language**: Support Hindi, Punjabi via Sarvam STT
4. **Voice Responses**: Use Sarvam TTS for voice callbacks
5. **Advanced Analytics**: Track user intent patterns, popular queries
