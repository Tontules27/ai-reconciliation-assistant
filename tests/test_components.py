"""Component tests on synthetic data — proof the rules generalize beyond
the shipped dataset (the engine never hardcodes dataset answers)."""

from datetime import date
from decimal import Decimal

from reconciliation.candidates import generate_candidates
from reconciliation.config import EngineConfig
from reconciliation.engine import (_decide_invoice, build_graph,
                                   duplicate_suspects, orphan_payment_ids)
from reconciliation.models import Invoice, Note, NoteFlag, NoteFlagType, Payment, Status
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


def test_discount_amount_must_be_adjacent_to_the_word_discount():
    # A note that also states the paid amount must not have that amount
    # read as the discount.
    invoices = [_invoice(invoice_id="INV-770", po_number="PO-770")]
    notes = [Note(source="email",
                  text="Vendor paid 1490.00 USD for invoice INV-770; "
                       "a 10 USD early payment discount applies.")]
    (flag,) = [f for f in extract_flags(notes, invoices, CFG)
               if f.type is NoteFlagType.DISCOUNT]
    assert flag.discount_amount == Decimal("10")


def test_vendor_level_discount_note_carries_no_amount():
    # An id-less note attaches to EVERY invoice of the vendor, so trusting
    # its amount could write off money genuinely outstanding on an unrelated
    # invoice. The flag survives for display; the amount does not.
    invoices = [
        _invoice(invoice_id="INV-770", vendor="Gamma Foods", po_number="PO-770"),
        _invoice(invoice_id="INV-771", vendor="Gamma Foods", po_number="PO-771"),
    ]
    notes = [Note(source="email", text="Gamma Foods applied a 10 USD discount.")]
    flags = [f for f in extract_flags(notes, invoices, CFG)
             if f.type is NoteFlagType.DISCOUNT]
    assert flags
    assert all(f.discount_amount is None for f in flags)


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


# --- Candidate generation -------------------------------------------------------


def test_po_citation_never_binds_to_colliding_invoice_number():
    # Invoice A's number and invoice B's PO share the digits "2001": a
    # payment citing PO-2001 must bind to B only, never to A.
    inv_a = _invoice(invoice_id="INV-2001", vendor="Alpha Corp",
                     po_number="PO-111", amount=Decimal("500.00"))
    inv_b = _invoice(invoice_id="INV-3000", vendor="Beta Corp",
                     po_number="PO-2001", amount=Decimal("700.00"))
    pay = _payment(payment_id="PAY-X", payer_name="Beta Corp",
                   amount=Decimal("700.00"), reference="PO-2001")

    ref_pairs = [p for p in generate_candidates([inv_a, inv_b], [pay], CFG)
                 if p.via_reference]
    assert [p.invoice_id for p in ref_pairs] == ["INV-3000"]


# --- Decision rules on synthetic cases ------------------------------------------


def test_discount_exceeding_shortfall_is_overpayment_not_negative_balance():
    # Paid 990 + documented 100 discount on a 1000 invoice = money above the
    # effective amount due: Needs Review (overpayment), never a Partial
    # Match with a negative remaining balance.
    invoice = _invoice(amount=Decimal("1000.00"))
    payment = _payment(amount=Decimal("990.00"))
    flag = NoteFlag(type=NoteFlagType.DISCOUNT, invoice_ids=[invoice.invoice_id],
                    discount_amount=Decimal("100"),
                    note=Note(source="email", text="100 USD discount agreed"))
    result = _decide_invoice(invoice, [(payment, score_pair(payment, invoice, CFG))],
                             [flag], False, CFG)
    assert result.status == Status.NEEDS_REVIEW
    assert result.review_reasons == ["OVERPAYMENT"]
    assert result.remaining_balance is None


def test_cross_currency_equal_amounts_earn_no_equality_signal():
    # Numerically equal amounts in different currencies must not add the
    # exact-amount confidence nor claim equality in the evidence.
    invoice = _invoice(currency="USD", amount=Decimal("100.00"))
    payment = _payment(currency="EUR", amount=Decimal("100.00"))
    result = _decide_invoice(invoice, [(payment, score_pair(payment, invoice, CFG))],
                             [], False, CFG)
    assert result.status == Status.NEEDS_REVIEW
    assert "CURRENCY_MISMATCH" in result.review_reasons
    amount_signals = [s for s in result.signals if s.signal == "amount"]
    assert all(s.points == 0.0 for s in amount_signals)
    assert any("not compared" in s.detail for s in amount_signals)


# --- Graph feeds classification ------------------------------------------------


def _dup_suspects(invoice, payments):
    links = {invoice.invoice_id: [(p, score_pair(p, invoice, CFG)) for p in payments]}
    graph = build_graph([invoice], payments, links)
    return duplicate_suspects(graph, {p.payment_id: p for p in payments},
                              {invoice.invoice_id: invoice}, CFG)


def test_duplicate_and_orphan_detection_on_synthetic_graph():
    invoice = _invoice()
    pay_a = _payment(payment_id="PAY-A")
    pay_b = _payment(payment_id="PAY-B")   # same amount, overpays -> duplicate
    stray = _payment(payment_id="PAY-C", reference="nothing", payer_name="Someone Else")
    links = {
        invoice.invoice_id: [
            (pay_a, score_pair(pay_a, invoice, CFG)),
            (pay_b, score_pair(pay_b, invoice, CFG)),
        ]
    }
    graph = build_graph([invoice], [pay_a, pay_b, stray], links)
    payments_by_id = {p.payment_id: p for p in (pay_a, pay_b, stray)}

    assert duplicate_suspects(graph, payments_by_id,
                              {invoice.invoice_id: invoice}, CFG) == {"INV-1"}
    assert orphan_payment_ids(graph) == {"PAY-C"}


def test_different_amounts_are_installments_not_duplicates():
    invoice = _invoice(amount=Decimal("300.00"))
    suspects = _dup_suspects(invoice, [
        _payment(payment_id="PAY-A", amount=Decimal("100.00")),
        _payment(payment_id="PAY-B", amount=Decimal("200.00")),
    ])
    assert suspects == set()


def test_equal_installments_settling_the_invoice_are_not_duplicates():
    # Two identical halves that sum exactly to the invoice are a legitimate
    # 50/50 split, not a double payment.
    invoice = _invoice(amount=Decimal("1000.00"))
    suspects = _dup_suspects(invoice, [
        _payment(payment_id="PAY-A", amount=Decimal("500.00")),
        _payment(payment_id="PAY-B", amount=Decimal("500.00")),
    ])
    assert suspects == set()
