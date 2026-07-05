"""Domain and result models.

All monetary fields are Decimal. Pydantic validates CSV strings straight
into Decimal (string -> Decimal, never through float), which preserves
exact cents: Decimal("1250.00") == what the bank statement says.
"""

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class Status(str, Enum):
    MATCHED = "Matched"
    PARTIAL_MATCH = "Partial Match"
    NEEDS_REVIEW = "Needs Review"
    UNMATCHED = "Unmatched"
    SUSPICIOUS = "Suspicious"


# --- Input records ----------------------------------------------------------


class Invoice(BaseModel):
    invoice_id: str
    vendor: str
    invoice_date: date
    due_date: date
    currency: str
    amount: Decimal
    po_number: str
    status: str


class Payment(BaseModel):
    payment_id: str
    payment_date: date
    payer_name: str
    currency: str
    amount: Decimal
    reference: str


class Note(BaseModel):
    source: str
    text: str


# --- Notes -> structured flags ----------------------------------------------


class NoteFlagType(str, Enum):
    PARTIAL_PAYMENT = "partial_payment"
    DISCOUNT = "discount"
    DUPLICATE_WARNING = "duplicate_warning"
    NAME_TYPO_CONFIRMED = "name_typo_confirmed"
    CURRENCY_REVIEW = "currency_review"


class NoteFlag(BaseModel):
    """A deterministic, structured fact extracted from a free-text note.

    Flags never decide a status by themselves; they adjust amounts
    (discount), corroborate a decision (partial/duplicate), and feed
    explanations.
    """

    type: NoteFlagType
    invoice_ids: list[str]
    discount_amount: Decimal | None = None
    note: Note


# --- Results ----------------------------------------------------------------


class SignalContribution(BaseModel):
    """One transparent piece of evidence behind a decision.

    The full list is the audit trail for the confidence score:
    confidence == clamp(sum(points)).
    """

    signal: str
    detail: str
    points: float


class InvoiceResult(BaseModel):
    invoice_id: str
    vendor: str
    invoice_amount: Decimal
    currency: str
    matched_payment_ids: list[str]
    status: Status
    confidence: float
    explanation: str
    remaining_balance: Decimal | None = None
    suggested_action: str
    review_reasons: list[str] = []
    signals: list[SignalContribution] = []
    related_notes: list[str] = []


class OrphanPaymentResult(BaseModel):
    """A payment that matched no invoice — reported alongside invoices."""

    payment_id: str
    payer_name: str
    amount: Decimal
    currency: str
    reference: str
    status: Status = Status.UNMATCHED
    confidence: float
    explanation: str
    suggested_action: str


class ReconciliationResult(BaseModel):
    summary: dict
    invoices: list[InvoiceResult]
    orphan_payments: list[OrphanPaymentResult]
