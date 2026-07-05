"""Explanation layer: deterministic templates + safe LLM provider cascade."""

from reconciliation.engine import reconcile
from reconciliation.explain import _accept, _LLMItem, compose_explanation, llm_explanations
from reconciliation.models import SignalContribution, Status


def test_template_starts_with_status_and_joins_evidence():
    signals = [
        SignalContribution(signal="reference", detail="Reference cites invoice X.", points=0.35),
        SignalContribution(signal="amount", detail="Amounts match.", points=0.30),
    ]
    text = compose_explanation(Status.MATCHED, "everything agrees", signals)
    assert text == "Matched: everything agrees. Evidence: Reference cites invoice X; Amounts match."


def test_cascade_falls_back_safely_without_any_key(monkeypatch):
    # The whole system must run without API keys: same result object back,
    # template explanations untouched, and a note saying why per provider.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = reconcile("data")
    updated, note = llm_explanations(result)
    assert updated == result
    assert "anthropic: no ANTHROPIC_API_KEY" in note
    assert "gemini: no GEMINI_API_KEY" in note


def test_failed_provider_falls_through_to_next(monkeypatch):
    # Anthropic key set but API unreachable -> its failure is recorded and the
    # cascade moves on to Gemini (no key here), ending in templates. No
    # exception may escape.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")  # nothing listens here
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = reconcile("data")
    updated, note = llm_explanations(result)
    assert updated == result
    assert note.startswith("templates (anthropic:")
    assert "gemini: no GEMINI_API_KEY" in note


def test_fact_drift_guard_rejects_bad_rows():
    rows = [{"record_id": "INV-1", "status": "Matched"},
            {"record_id": "INV-2", "status": "Suspicious"}]
    items = [
        _LLMItem(record_id="INV-1", explanation="Matched: all good."),          # ok
        _LLMItem(record_id="INV-2", explanation="Matched: relabeled status."),  # wrong prefix
        _LLMItem(record_id="INV-9", explanation="Matched: unknown record."),    # unknown id
    ]
    accepted = _accept(items, rows)
    assert accepted == {"INV-1": "Matched: all good."}
