"""Scoring: compute match signals for candidate pairs only.

The expensive work (fuzzy name similarity) runs here, after candidate
generation has discarded most pairs. `rank` is a transparent weighted sum
used to pick the best invoice when a payment has several candidates; the
final status is decided by rules in engine.py, never by this number alone.
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


class PairScore(BaseModel):
    payment_id: str
    invoice_id: str
    invoice_id_in_reference: bool
    po_in_reference: bool
    amount_equal: bool      # within cfg.amount_tolerance — never Decimal ==
    underpaid: bool         # payment below invoice amount (partial candidate)
    currency_match: bool
    name_similarity: float  # 0-100
    rank: float             # assignment score, from cfg weights


def score_pair(payment: Payment, invoice: Invoice, cfg: EngineConfig) -> PairScore:
    cited_ids = extract_invoice_numbers(payment.reference)
    cited_pos = extract_po_numbers(payment.reference)
    id_ref = invoice_number(invoice.invoice_id) in cited_ids
    po_ref = po_number_token(invoice.po_number) in cited_pos

    diff = invoice.amount - payment.amount
    amount_equal = abs(diff) <= cfg.amount_tolerance
    underpaid = diff > cfg.amount_tolerance

    sim = name_similarity(payment.payer_name, invoice.vendor)
    currency_match = payment.currency == invoice.currency

    rank = (
        (cfg.w_ref_invoice_id if id_ref else cfg.w_ref_po if po_ref else 0.0)
        + (cfg.w_amount_exact if amount_equal else cfg.w_amount_partial if underpaid else 0.0)
        + cfg.w_name_max * sim / 100
        + (cfg.w_currency if currency_match else 0.0)
    )
    return PairScore(
        payment_id=payment.payment_id,
        invoice_id=invoice.invoice_id,
        invoice_id_in_reference=id_ref,
        po_in_reference=po_ref,
        amount_equal=amount_equal,
        underpaid=underpaid,
        currency_match=currency_match,
        name_similarity=sim,
        rank=rank,
    )
