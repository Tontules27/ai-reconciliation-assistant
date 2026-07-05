"""Component tests on synthetic data — proof the rules generalize beyond
the shipped dataset (the engine never hardcodes dataset answers)."""

from datetime import date
from decimal import Decimal

from reconciliation.config import EngineConfig
from reconciliation.engine import build_graph, duplicate_suspects, orphan_payment_ids
from reconciliation.models import Invoice, Note, Payment
from reconciliation.normalize import (
    extract_invoice_numbers,
    extract_po_numbers,
    name_similarity,
    normalize_name,
)
from reconciliation.notes import extract_flags
from reconciliation.scoring import score_pair

CFG = EngineConfig()


def _invoice(**overrides) -> Invoice:
    base = dict(invoice_id="INV-1", vendor="Test Vendor", invoice_date=date(2026, 1, 1),
                due_date=date(2026, 2, 1), currency="USD", amount=Decimal("100.00"),
                po_number="PO-1", status="open")
    return Invoice(**{**base, **overrides})


def _payment(**overrides) -> Payment:
    base = dict(payment_id="PAY-1", payment_date=date(2026, 1, 15),
                payer_name="Test Vendor", currency="USD", amount=Decimal("100.00"),
                reference="INV-1")
    return Payment(**{**base, **overrides})


# --- Normalization ------------------------------------------------------------


def test_legal_suffixes_stripped_from_end_only():
    assert normalize_name("Grupo Norte SA") == "grupo norte"
    assert normalize_name("ACME Logistics LLC") == "acme logistics"
    # "co" mid-name must survive; only trailing legal tokens are dropped.
    assert normalize_name("Co Op Foods Inc") == "co op foods"


def test_name_similarity_handles_typos_and_abbreviations():
    assert name_similarity("ACME Logistcs", "ACME Logistics") >= CFG.name_strong_threshold
    assert name_similarity("Delta Technology Services",
                           "Delta Tech Services") >= CFG.name_strong_threshold
    assert name_similarity("Unknown Vendor", "ACME Logistics LLC") < CFG.name_weak_threshold


def test_reference_extraction_variants():
    assert extract_invoice_numbers("Payment for invoice 1001") == {"1001"}
    assert extract_invoice_numbers("INV1002 wire") == {"1002"}
    # "No invoice reference" cites no number; "10 USD" is not an invoice id.
    assert extract_invoice_numbers("No invoice reference") == set()
    assert extract_invoice_numbers("applied a 10 USD discount") == set()
    assert extract_po_numbers("Partial payment PO-8893") == {"8893"}


# --- Notes -> flags -----------------------------------------------------------


def test_discount_amount_extracted_as_decimal():
    invoices = [_invoice(invoice_id="INV-770", po_number="PO-770")]
    notes = [Note(source="slack", text="Vendor applied a 12.50 USD discount for invoice INV-770.")]
    (flag,) = [f for f in extract_flags(notes, invoices, CFG) if f.discount_amount]
    assert flag.discount_amount == Decimal("12.50")
    assert flag.invoice_ids == ["INV-770"]


def test_note_with_explicit_id_does_not_leak_to_similar_vendor():
    # Two near-identical vendors; the note cites INV-10 explicitly, so the
    # vendor-name fallback must NOT attach it to INV-20 as well.
    invoices = [
        _invoice(invoice_id="INV-10", vendor="ACME Logistics", po_number="PO-10"),
        _invoice(invoice_id="INV-20", vendor="ACME Logistics LLC", po_number="PO-20"),
    ]
    notes = [Note(source="email", text="ACME Logistics confirmed payment for invoice INV-10.")]
    flags = extract_flags(notes, invoices, CFG)
    assert all(f.invoice_ids == ["INV-10"] for f in flags)


# --- Graph feeds classification ------------------------------------------------


def test_duplicate_and_orphan_detection_on_synthetic_graph():
    invoice = _invoice()
    pay_a = _payment(payment_id="PAY-A")
    pay_b = _payment(payment_id="PAY-B")   # same amount -> duplicate signature
    stray = _payment(payment_id="PAY-C", reference="nothing", payer_name="Someone Else")
    links = {
        invoice.invoice_id: [
            (pay_a, score_pair(pay_a, invoice, CFG)),
            (pay_b, score_pair(pay_b, invoice, CFG)),
        ]
    }
    graph = build_graph([invoice], [pay_a, pay_b, stray], links)
    payments_by_id = {p.payment_id: p for p in (pay_a, pay_b, stray)}

    assert duplicate_suspects(graph, payments_by_id, CFG) == {"INV-1"}
    assert orphan_payment_ids(graph) == {"PAY-C"}


def test_different_amounts_are_installments_not_duplicates():
    invoice = _invoice(amount=Decimal("300.00"))
    pay_a = _payment(payment_id="PAY-A", amount=Decimal("100.00"))
    pay_b = _payment(payment_id="PAY-B", amount=Decimal("200.00"))
    links = {
        invoice.invoice_id: [
            (pay_a, score_pair(pay_a, invoice, CFG)),
            (pay_b, score_pair(pay_b, invoice, CFG)),
        ]
    }
    graph = build_graph([invoice], [pay_a, pay_b], links)
    payments_by_id = {p.payment_id: p for p in (pay_a, pay_b)}

    assert duplicate_suspects(graph, payments_by_id, CFG) == set()
