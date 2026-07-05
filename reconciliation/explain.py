"""Explanation generation: deterministic templates + optional LLM phrasing.

The engine decides everything; this module only puts decisions into words.
Two paths:

- Template (default): deterministic composition from the signal breakdown.
  Always available, no network, same input -> same text.
- LLM (opt-in): a single API call rephrases ALL rows at once (never one call
  per pair/row) with schema-validated structured output. Providers cascade:
  Anthropic first, then Gemini; a provider that has no key or whose call
  fails is skipped. The LLM receives already-decided facts and may only
  reword them; every returned row is validated identically regardless of
  provider, and if everything fails the templates stand.
"""

import json
import os

from pydantic import BaseModel

from .models import ReconciliationResult, SignalContribution, Status

# Phrasing quality matters (these sentences are the triage queue copy), so
# each provider uses its current general-purpose tier.
ANTHROPIC_MODEL = "claude-opus-4-8"
GEMINI_MODEL = "gemini-2.5-flash"

_SYSTEM_PROMPT = """\
You write one explanation per record for an invoice-payment reconciliation report,
read by a finance operator deciding what to do next.

Hard rules:
- The facts (status, amounts, currencies, ids, reasons) are already decided and
  provided as structured evidence. NEVER alter, add or omit a fact. Never guess.
- Each explanation MUST start with the given status followed by a colon,
  e.g. "Needs Review: ".
- 1-3 plain, professional sentences. No markdown, no bullet points.
- Return one item per input record, keyed by the given record_id."""


def compose_explanation(status: Status, lead: str,
                        signals: list[SignalContribution]) -> str:
    """Deterministic template: decision lead + semicolon-joined evidence."""
    evidence = "; ".join(s.detail.rstrip(".") for s in signals)
    return f"{status.value}: {lead}. Evidence: {evidence}."


# --- Optional LLM path --------------------------------------------------------


class _LLMItem(BaseModel):
    record_id: str
    explanation: str


class _LLMExplanations(BaseModel):
    items: list[_LLMItem]


def _rows_for_llm(result: ReconciliationResult) -> list[dict]:
    rows = [
        {
            "record_id": r.invoice_id,
            "status": r.status.value,
            "vendor": r.vendor,
            "evidence": [s.detail for s in r.signals],
            "review_reasons": r.review_reasons,
            "remaining_balance": str(r.remaining_balance) if r.remaining_balance else None,
            "related_notes": r.related_notes,
        }
        for r in result.invoices
    ]
    rows += [
        {
            "record_id": o.payment_id,
            "status": o.status.value,
            "payer": o.payer_name,
            "evidence": [o.explanation],
            "review_reasons": [],
            "remaining_balance": None,
            "related_notes": [],
        }
        for o in result.orphan_payments
    ]
    return rows


def _anthropic_call(rows: list[dict]) -> list[_LLMItem]:
    import anthropic  # lazy: only needed on the opt-in path

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(rows)}],
        output_format=_LLMExplanations,
    )
    return response.parsed_output.items


def _gemini_call(rows: list[dict]) -> list[_LLMItem]:
    from google import genai  # lazy: only needed on the opt-in path

    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=json.dumps(rows),
        config={
            "system_instruction": _SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": _LLMExplanations,
        },
    )
    if response.parsed is None:
        raise ValueError("Gemini returned no parseable structured output")
    return response.parsed.items


# Cascade order: Anthropic (primary stack) then Gemini (alternative).
_PROVIDERS = [
    ("anthropic", "ANTHROPIC_API_KEY", _anthropic_call),
    ("gemini", "GEMINI_API_KEY", _gemini_call),
]


def _accept(items: list[_LLMItem], rows: list[dict]) -> dict[str, str]:
    """Guard against fact drift: a rewritten row is accepted only if it
    exists, keeps its status prefix, and has a sane length. Rejected rows
    keep the deterministic template — partial acceptance is fine."""
    status_by_id = {r["record_id"]: r["status"] for r in rows}
    return {
        item.record_id: item.explanation.strip()
        for item in items
        if item.record_id in status_by_id
        and item.explanation.strip().startswith(f"{status_by_id[item.record_id]}:")
        and 0 < len(item.explanation.strip()) <= 600
    }


def llm_explanations(result: ReconciliationResult) -> tuple[ReconciliationResult, str]:
    """Rephrase explanations via the provider cascade; templates on any failure.

    Returns (result, note). The result always carries valid explanations —
    template ones whenever no provider succeeds or a row fails validation.
    """
    rows = _rows_for_llm(result)
    attempts = []
    for name, env_var, call in _PROVIDERS:
        if not os.environ.get(env_var):
            attempts.append(f"{name}: no {env_var} set")
            continue
        try:
            items = call(rows)
        except Exception as exc:  # any API/parse failure -> next provider
            attempts.append(f"{name}: {type(exc).__name__}")
            continue
        accepted = _accept(items, rows)
        if not accepted:
            attempts.append(f"{name}: output failed validation")
            continue
        updated = result.model_copy(update={
            "invoices": [
                r.model_copy(update={"explanation": accepted[r.invoice_id]})
                if r.invoice_id in accepted else r
                for r in result.invoices
            ],
            "orphan_payments": [
                o.model_copy(update={"explanation": accepted[o.payment_id]})
                if o.payment_id in accepted else o
                for o in result.orphan_payments
            ],
        })
        return updated, f"llm/{name} ({len(accepted)}/{len(rows)} rows rephrased)"

    return result, "templates (" + "; ".join(attempts) + ")"
