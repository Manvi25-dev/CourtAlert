import whatsapp_handler


class _FakeSource:
    def __init__(self):
        self.last_fetch_meta = {"api_status": "success"}

    def fetch_cases(self, hearing_date: str):
        return [
            {
                "case_number": "LPA/171/2019",
                "court_number": "2",
                "hearing_date": hearing_date,
                "judge": "Example Judge",
            }
        ]


def test_detects_cnr_and_tracks_without_strict_format(monkeypatch):
    monkeypatch.setattr(
        whatsapp_handler,
        "extract_intent_with_confidence",
        lambda message, user_context=None: {
            "intent": "UNCLEAR",
            "confidence": 0.2,
            "entities": {"case_number": None, "court": None, "action_type": None},
            "reasoning": "",
            "suggested_next_action": "",
        },
    )
    monkeypatch.setattr(whatsapp_handler, "_get_user_context", lambda phone: {"tracked_cases": []})
    monkeypatch.setattr(whatsapp_handler, "handle_add_case", lambda phone, text: "ok")

    decision = whatsapp_handler.decide_next_best_action("+911111111111", "CNR:GJDH020024462018")

    assert decision["intent"] == "TRACK_CASE"
    assert decision["case_number"] == "GJDH020024462018"
    assert "Tracking case GJDH020024462018" in decision["response"]


def test_infers_case_from_loose_number_year(monkeypatch):
    monkeypatch.setattr(
        whatsapp_handler,
        "extract_intent_with_confidence",
        lambda message, user_context=None: {
            "intent": "UNCLEAR",
            "confidence": 0.1,
            "entities": {"case_number": None, "court": None, "action_type": None},
            "reasoning": "",
            "suggested_next_action": "",
        },
    )
    monkeypatch.setattr(whatsapp_handler, "_get_user_context", lambda phone: {"tracked_cases": ["LPA/171/2019"]})
    monkeypatch.setattr(whatsapp_handler, "handle_add_case", lambda phone, text: "ok")

    decision = whatsapp_handler.decide_next_best_action("+911111111111", "case 171 of 2019")

    assert decision["intent"] == "TRACK_CASE"
    assert "Did you mean case" in decision["response"]


def test_uses_context_for_when_is_it(monkeypatch):
    monkeypatch.setattr(
        whatsapp_handler,
        "extract_intent_with_confidence",
        lambda message, user_context=None: {
            "intent": "QUERY_STATUS",
            "confidence": 0.9,
            "entities": {"case_number": None, "court": None, "action_type": "check"},
            "reasoning": "",
            "suggested_next_action": "fetch_case_status",
        },
    )
    monkeypatch.setattr(whatsapp_handler, "_get_user_context", lambda phone: {"tracked_cases": ["LPA/171/2019"]})
    monkeypatch.setattr(whatsapp_handler, "_resolve_live_source_key", lambda case_number, court_name=None: "fake")
    monkeypatch.setitem(whatsapp_handler.court_sources, "fake", _FakeSource())

    decision = whatsapp_handler.decide_next_best_action("+911111111111", "when is it?")

    assert decision["intent"] == "QUERY_STATUS"
    assert decision["case_number"] == "LPA/171/2019"
    assert "listed on" in decision["response"].lower()
