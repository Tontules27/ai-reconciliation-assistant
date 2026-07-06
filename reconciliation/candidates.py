"""Candidate generation: cheap deterministic filters run on every
(payment, invoice) pair; only survivors reach the (expensive) scoring stage.

At scale this whole module becomes blocking/indexing in the database
(e.g. Postgres indexes on extracted reference tokens, currency and amount
bands) — the pipeline seam stays the same.
"""

from pydantic import BaseModel

from .config import EngineConfig
from .models import Invoice, Payment
from .normalize import (
    extract_invoice_numbers,
    extract_po_numbers,
    invoice_number,
    name_similarity,
    po_number_token,
)


class CandidatePair(BaseModel):
    payment_id: str
    invoice_id: str
    via_reference: bool  # survived because the reference cites the invoice/PO


def generate_candidates(
    invoices: list[Invoice], payments: list[Payment], cfg: EngineConfig
) -> list[CandidatePair]:
    by_number = {invoice_number(inv.invoice_id): inv for inv in invoices}
    by_po = {po_number_token(inv.po_number): inv for inv in invoices}

    pairs: dict[tuple[str, str], CandidatePair] = {}
    for pay in payments:
        # Filter 1 — reference citation. Currency is deliberately NOT checked
        # here: a cited pair with a currency mismatch must survive so the
        # decision rules can flag it, not silently drop it.
        # Tokens keep their namespace: an invoice citation resolves only
        # against invoice numbers and a PO citation only against PO numbers —
        # a PO whose digits collide with another invoice's id must not bind
        # to that invoice.
        ref_hits = [by_number[t] for t in extract_invoice_numbers(pay.reference)
                    if t in by_number]
        ref_hits += [by_po[t] for t in extract_po_numbers(pay.reference)
                     if t in by_po]
        for inv in ref_hits:
            pairs[(pay.payment_id, inv.invoice_id)] = CandidatePair(
                payment_id=pay.payment_id,
                invoice_id=inv.invoice_id,
                via_reference=True,
            )

        # Filter 2 — no citation: same currency + plausible amount band +
        # minimally similar name. All three required, so a stray payment
        # ("Random Supplier", 600 USD) generates no candidates at all.
        for inv in invoices:
            key = (pay.payment_id, inv.invoice_id)
            if key in pairs:
                continue
            if pay.currency != inv.currency:
                continue
            if not (
                inv.amount * cfg.candidate_amount_floor
                <= pay.amount
                <= inv.amount * cfg.candidate_amount_ceiling
            ):
                continue
            if name_similarity(pay.payer_name, inv.vendor) < cfg.name_weak_threshold:
                continue
            pairs[key] = CandidatePair(
                payment_id=pay.payment_id, invoice_id=inv.invoice_id, via_reference=False
            )

    return list(pairs.values())
