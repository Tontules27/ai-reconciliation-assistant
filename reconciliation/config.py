"""Tunable parameters for the reconciliation engine.

Every threshold and weight lives here, in one place, so they can be tuned
against the golden set (Phase 2 tests) instead of living as magic numbers
scattered through the code. Confidence weights are plain floats (confidence
is a score, not money); anything that touches money is Decimal.
"""

from decimal import Decimal

from pydantic import BaseModel


class EngineConfig(BaseModel):
    # Money is compared with an explicit tolerance, never with ==.
    amount_tolerance: Decimal = Decimal("0.01")

    # Fuzzy name similarity thresholds (rapidfuzz token_sort_ratio, 0-100).
    # strong: treat as the same entity (typos, abbreviations, legal suffixes).
    # weak: below this the payer identity does NOT match -> Needs Review.
    name_strong_threshold: float = 80.0
    name_weak_threshold: float = 55.0

    # Candidate generation without a reference hit: same currency, plausible
    # amount band, minimally similar name. These cheap filters are the seam
    # that becomes blocking/indexing in a database at scale.
    candidate_amount_floor: Decimal = Decimal("0.40")    # payment >= 40% of invoice
    candidate_amount_ceiling: Decimal = Decimal("1.02")  # allow tiny overpayment

    # Attaching a note to an invoice via vendor name (only when the note
    # contains no explicit invoice/PO id — ids always win to avoid a note
    # about "ACME Logistics" leaking onto "ACME Logistics LLC").
    note_vendor_threshold: float = 88.0

    # --- Confidence weights: positive evidence -----------------------------
    w_ref_invoice_id: float = 0.35   # reference cites the invoice number
    w_ref_po: float = 0.30           # reference cites the PO number
    w_amount_exact: float = 0.30
    w_amount_note_adjusted: float = 0.25  # exact once a documented discount is applied
    w_amount_partial_noted: float = 0.20  # underpayment corroborated by a note
    w_amount_partial: float = 0.10        # underpayment with no corroboration
    w_name_max: float = 0.20         # scaled by similarity/100
    w_currency: float = 0.10
    w_note_corroboration: float = 0.05

    # --- Confidence penalties: anomalies -----------------------------------
    # Rules (not the score) decide the status; penalties only push anomalous
    # cases down the triage queue.
    p_currency_mismatch: float = -0.25
    p_identity_mismatch: float = -0.30
    p_duplicate: float = -0.35
    p_overpayment: float = -0.20
