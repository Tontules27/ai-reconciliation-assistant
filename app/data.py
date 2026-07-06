"""Portal data access: run the engine once per process, shape rows for the UI.

Reconciliation state is derived, never persisted: it is recomputed from the
source files at process start (manual review decisions live in store.py).
This module is the only place the UI touches the engine. Invoices and orphan
payments are unified into "queue records" sorted by risk — that ordering IS
the triage queue.
"""

from functools import lru_cache
from pathlib import Path

from reconciliation.engine import reconcile
from reconciliation.loader import load_payments
from reconciliation.models import ReconciliationResult

from .theme import SEVERITY_ORDER

_SEVERITY_RANK = {status: rank for rank, status in enumerate(SEVERITY_ORDER)}


def _payment_row(payment) -> dict:
    return {
        "payment_id": payment.payment_id,
        "date": payment.payment_date.isoformat(),
        "payer": payment.payer_name,
        "amount": f"{payment.amount} {payment.currency}",
        "reference": payment.reference,
    }


def _build_records(result: ReconciliationResult, payments_by_id: dict) -> list[dict]:
    records = []
    for r in result.invoices:
        records.append({
            "record_id": r.invoice_id,
            "kind": "invoice",
            "party": r.vendor,
            "status": r.status.value,
            "confidence": r.confidence,
            "amount": f"{r.invoice_amount} {r.currency}",
            "remaining_balance": (
                f"{r.remaining_balance} {r.currency}" if r.remaining_balance is not None else None
            ),
            "explanation": r.explanation,
            "suggested_action": r.suggested_action,
            "review_reasons": r.review_reasons,
            "signals": [s.model_dump() for s in r.signals],
            "related_notes": r.related_notes,
            "payments": [_payment_row(payments_by_id[pid]) for pid in r.matched_payment_ids],
        })
    for o in result.orphan_payments:
        records.append({
            "record_id": o.payment_id,
            "kind": "payment",
            "party": o.payer_name,
            "status": o.status.value,
            "confidence": o.confidence,
            "amount": f"{o.amount} {o.currency}",
            "remaining_balance": None,
            "explanation": o.explanation,
            "suggested_action": o.suggested_action,
            "review_reasons": [],
            "signals": [],
            "related_notes": [],
            "payments": [_payment_row(payments_by_id[o.payment_id])],
        })

    # Risk sort: severity first, then LOWEST confidence first within a
    # severity tier — the least-supported case is the most urgent one.
    records.sort(key=lambda r: (_SEVERITY_RANK[r["status"]], r["confidence"]))
    return records


@lru_cache(maxsize=1)
def get_data(data_dir: str = "data") -> tuple[dict, list[dict]]:
    """(summary, risk-sorted queue records) — computed once per process."""
    result = reconcile(data_dir)
    payments_by_id = {p.payment_id: p for p in load_payments(Path(data_dir) / "payments.csv")}
    return result.summary, _build_records(result, payments_by_id)


def find_record(record_id: str) -> dict | None:
    _, records = get_data()
    return next((r for r in records if r["record_id"] == record_id), None)


def find_payment(payment_id: str) -> tuple[dict, dict] | tuple[None, None]:
    """(payment row, owning queue record) — the record is the orphan itself
    when the payment matched no invoice."""
    _, records = get_data()
    for r in records:
        for p in r["payments"]:
            if p["payment_id"] == payment_id:
                return p, r
    return None, None


def vendor_invoices(vendor: str) -> list[dict]:
    _, records = get_data()
    return [r for r in records if r["kind"] == "invoice" and r["party"] == vendor]
