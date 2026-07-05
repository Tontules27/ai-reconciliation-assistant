"""Decisioning: deterministic rules assign status, confidence and balance.

Pipeline: load -> notes-to-flags -> candidate generation -> scoring ->
assignment -> graph -> per-invoice decision. Same input always produces the
same output; no AI is involved in any decision. This module never imports
Dash/Flask.
"""

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import networkx as nx

from .candidates import generate_candidates
from .config import EngineConfig
from .loader import load_invoices, load_notes, load_payments
from .models import (
    Invoice,
    InvoiceResult,
    Note,
    NoteFlag,
    NoteFlagType,
    OrphanPaymentResult,
    Payment,
    ReconciliationResult,
    SignalContribution,
    Status,
)
from .notes import extract_flags
from .scoring import PairScore, score_pair

_CENT = Decimal("0.01")

# One suggested action per outcome — the operator's next step, not decoration.
_ACTIONS = {
    Status.MATCHED: "Approve and close the invoice.",
    Status.PARTIAL_MATCH: "Keep the invoice open and follow up on the remaining balance.",
    Status.UNMATCHED: "No payment received; follow up with the vendor before the due date.",
}


# --- Graph -------------------------------------------------------------------


def build_graph(
    invoices: list[Invoice],
    payments: list[Payment],
    links: dict[str, list[tuple[Payment, PairScore]]],
) -> nx.Graph:
    """Relationship graph: vendors -> invoices <- payments.

    Dual use (why it earns its place): the structure feeds classification
    below (2+ payment edges into one invoice = duplicate suspect, isolated
    payment = orphan), and Phase 5 renders the same graph with cytoscape.
    """
    g = nx.Graph()
    for inv in invoices:
        g.add_node(inv.invoice_id, kind="invoice")
        g.add_node(inv.vendor, kind="vendor")
        g.add_edge(inv.vendor, inv.invoice_id, kind="billed")
    for pay in payments:
        g.add_node(pay.payment_id, kind="payment")
    for invoice_id, linked in links.items():
        for payment, score in linked:
            g.add_edge(payment.payment_id, invoice_id, kind="paid", rank=score.rank)
    return g


def _payment_neighbors(g: nx.Graph, invoice_id: str) -> list[str]:
    return [n for n in g.neighbors(invoice_id) if g.nodes[n]["kind"] == "payment"]


def duplicate_suspects(g: nx.Graph, payments_by_id: dict[str, Payment],
                       cfg: EngineConfig) -> set[str]:
    """Invoices with 2+ incoming payments of the same amount.

    Two identical amounts against one invoice is the classic double-payment
    signature; distinct amounts (installments) are handled as partials.
    """
    suspects = set()
    for node, data in g.nodes(data=True):
        if data["kind"] != "invoice":
            continue
        amounts = [payments_by_id[p].amount for p in _payment_neighbors(g, node)]
        if len(amounts) >= 2 and any(
            abs(a - b) <= cfg.amount_tolerance
            for i, a in enumerate(amounts)
            for b in amounts[i + 1:]
        ):
            suspects.add(node)
    return suspects


def orphan_payment_ids(g: nx.Graph) -> set[str]:
    """Payment nodes with no edge to any invoice."""
    return {
        node
        for node, data in g.nodes(data=True)
        if data["kind"] == "payment" and g.degree(node) == 0
    }


# --- Per-invoice decision ----------------------------------------------------


def _decide_invoice(
    invoice: Invoice,
    linked: list[tuple[Payment, PairScore]],
    flags: list[NoteFlag],
    is_duplicate_suspect: bool,
    cfg: EngineConfig,
) -> InvoiceResult:
    related_notes = list(dict.fromkeys(f.note.text for f in flags))

    if not linked:
        return InvoiceResult(
            invoice_id=invoice.invoice_id,
            vendor=invoice.vendor,
            invoice_amount=invoice.amount,
            currency=invoice.currency,
            matched_payment_ids=[],
            status=Status.UNMATCHED,
            confidence=0.90,
            explanation=(
                "No candidate payment references this invoice or PO, and no "
                "payment matches by vendor, currency and amount."
            ),
            suggested_action=_ACTIONS[Status.UNMATCHED],
            signals=[SignalContribution(
                signal="no_candidates",
                detail="No payment survived candidate generation for this invoice.",
                points=0.90,
            )],
            related_notes=related_notes,
        )

    linked = sorted(linked, key=lambda ps: (-ps[1].rank, ps[0].payment_id))
    best_payment, best = linked[0]
    total_paid = sum((p.amount for p, _ in linked), Decimal("0"))
    discount = sum(
        (f.discount_amount for f in flags
         if f.type is NoteFlagType.DISCOUNT and f.discount_amount is not None),
        Decimal("0"),
    )
    flag_types = {f.type for f in flags}

    signals: list[SignalContribution] = []

    def add(signal: str, detail: str, points: float) -> None:
        signals.append(SignalContribution(signal=signal, detail=detail, points=points))

    # Evidence signals (shared by every outcome).
    if best.invoice_id_in_reference:
        add("reference", f"Payment reference cites invoice {invoice.invoice_id}.",
            cfg.w_ref_invoice_id)
    elif best.po_in_reference:
        add("reference", f"Payment reference cites PO {invoice.po_number}.",
            cfg.w_ref_po)

    add(
        "payer_name",
        f"Payer '{best_payment.payer_name}' vs vendor '{invoice.vendor}': "
        f"{best.name_similarity:.0f}% name similarity.",
        round(cfg.w_name_max * best.name_similarity / 100, 4),
    )

    currency_ok = all(p.currency == invoice.currency for p, _ in linked)
    if currency_ok:
        add("currency", f"Currencies match ({invoice.currency}).", cfg.w_currency)

    # Amount evaluation over the SUM of linked payments (handles installments),
    # with documented discounts applied before comparing. Tolerance, never ==.
    diff = invoice.amount - total_paid
    if abs(diff) <= cfg.amount_tolerance:
        amount_state = "exact"
        add("amount",
            f"Paid {total_paid} equals invoice amount {invoice.amount}.",
            cfg.w_amount_exact)
    elif discount > 0 and abs(diff - discount) <= cfg.amount_tolerance:
        amount_state = "note_adjusted"
        add("amount",
            f"Paid {total_paid} + documented discount {discount} equals "
            f"invoice amount {invoice.amount}.",
            cfg.w_amount_note_adjusted)
    elif diff > 0:
        amount_state = "underpaid"
        noted = NoteFlagType.PARTIAL_PAYMENT in flag_types
        add("amount",
            f"Paid {total_paid} of {invoice.amount}"
            + (" — a note confirms a partial payment." if noted
               else " with no note explaining the difference."),
            cfg.w_amount_partial_noted if noted else cfg.w_amount_partial)
    else:
        amount_state = "overpaid"
        add("amount", f"Paid {total_paid} exceeds invoice amount {invoice.amount}.", 0.0)

    # --- Status rules, most severe first. Conservative bias: anomalies go to
    # a human (Suspicious / Needs Review) before any auto-match applies. ---
    review_reasons: list[str] = []
    remaining: Decimal | None = None

    if is_duplicate_suspect:
        status = Status.SUSPICIOUS
        review_reasons.append("POSSIBLE_DUPLICATE")
        dup_ids = ", ".join(p.payment_id for p, _ in linked)
        add("duplicate",
            f"Two or more payments of the same amount ({dup_ids}) target this invoice.",
            cfg.p_duplicate)
        if NoteFlagType.DUPLICATE_WARNING in flag_types:
            add("note", "An ops note independently warns about a possible double payment.",
                cfg.w_note_corroboration)
        lead = "possible duplicate payment — the same amount was received more than once"
        action = "Investigate the duplicate payment before closing; refund or apply to another invoice."
    elif not currency_ok:
        status = Status.NEEDS_REVIEW
        review_reasons.append("CURRENCY_MISMATCH")
        pay_curr = ", ".join(sorted({p.currency for p, _ in linked if p.currency != invoice.currency}))
        add("currency",
            f"Payment currency ({pay_curr}) differs from invoice currency "
            f"({invoice.currency}); amounts in different currencies are never treated as equal.",
            cfg.p_currency_mismatch)
        lead = "payment currency differs from the invoice currency"
        action = "Confirm the expected currency with the vendor before applying the payment."
    elif best.name_similarity < cfg.name_weak_threshold:
        status = Status.NEEDS_REVIEW
        review_reasons.append("IDENTITY_MISMATCH")
        add("identity",
            f"Payer '{best_payment.payer_name}' does not resemble vendor "
            f"'{invoice.vendor}' — the money adds up but the identity does not.",
            cfg.p_identity_mismatch)
        lead = "the amount and reference match but the payer identity does not"
        action = "Verify the payer identity with the vendor before applying the payment."
    elif amount_state in ("exact", "note_adjusted"):
        status = Status.MATCHED
        if amount_state == "note_adjusted":
            lead = "amount matches once the documented early-payment discount is applied"
        else:
            lead = "reference, amount and payer identity all agree"
        action = _ACTIONS[Status.MATCHED]
        # Corroborating notes (typo confirmation, discount) add confidence.
        if NoteFlagType.NAME_TYPO_CONFIRMED in flag_types:
            add("note", "A note confirms the payer-name typo in the bank export.",
                cfg.w_note_corroboration)
    elif amount_state == "underpaid":
        status = Status.PARTIAL_MATCH
        remaining = (invoice.amount - total_paid - discount).quantize(_CENT)
        lead = f"partial payment received; {remaining} {invoice.currency} outstanding"
        action = _ACTIONS[Status.PARTIAL_MATCH]
        if NoteFlagType.PARTIAL_PAYMENT in flag_types:
            add("note", "A note confirms this is a partial payment with the balance to follow.",
                cfg.w_note_corroboration)
    else:  # overpaid without duplicate signature
        status = Status.NEEDS_REVIEW
        review_reasons.append("OVERPAYMENT")
        add("overpayment", "Total paid exceeds the invoice amount.", cfg.p_overpayment)
        lead = "total paid exceeds the invoice amount"
        action = "Review the overpayment with the vendor; refund or apply the excess."

    confidence = round(min(1.0, max(0.0, sum(s.points for s in signals))), 2)

    # Deterministic explanation (Phase 3 swaps in the template/LLM generator).
    evidence = "; ".join(s.detail.rstrip(".") for s in signals)
    explanation = f"{status.value}: {lead}. Evidence: {evidence}."

    return InvoiceResult(
        invoice_id=invoice.invoice_id,
        vendor=invoice.vendor,
        invoice_amount=invoice.amount,
        currency=invoice.currency,
        matched_payment_ids=[p.payment_id for p, _ in linked],
        status=status,
        confidence=confidence,
        explanation=explanation,
        remaining_balance=remaining,
        suggested_action=action,
        review_reasons=review_reasons,
        signals=signals,
        related_notes=related_notes,
    )


# --- Orchestration -----------------------------------------------------------


def reconcile(data_dir: str | Path = "data",
              cfg: EngineConfig | None = None) -> ReconciliationResult:
    """Run the full pipeline over the files in `data_dir`.

    Pure function of its inputs: reconciliation is recomputed from the files
    on every run; only manual review decisions are persisted elsewhere.
    """
    cfg = cfg or EngineConfig()
    data_dir = Path(data_dir)
    invoices = load_invoices(data_dir / "invoices.csv")
    payments = load_payments(data_dir / "payments.csv")
    notes = load_notes(data_dir / "notes.json")

    flags = extract_flags(notes, invoices, cfg)
    flags_by_invoice: dict[str, list[NoteFlag]] = defaultdict(list)
    for f in flags:
        for invoice_id in f.invoice_ids:
            flags_by_invoice[invoice_id].append(f)

    invoices_by_id = {inv.invoice_id: inv for inv in invoices}
    payments_by_id = {pay.payment_id: pay for pay in payments}

    # Candidate generation (cheap) then scoring (expensive) on survivors only.
    pairs = generate_candidates(invoices, payments, cfg)
    scored = [
        score_pair(payments_by_id[p.payment_id], invoices_by_id[p.invoice_id], cfg)
        for p in pairs
    ]

    # Assignment: each payment goes to its single best-ranked invoice
    # (deterministic tie-break by invoice id). One payment never pays two
    # invoices; split payments would need an allocation step at scale.
    best_by_payment: dict[str, PairScore] = {}
    for s in sorted(scored, key=lambda s: (s.payment_id, -s.rank, s.invoice_id)):
        best_by_payment.setdefault(s.payment_id, s)

    links: dict[str, list[tuple[Payment, PairScore]]] = defaultdict(list)
    for s in best_by_payment.values():
        links[s.invoice_id].append((payments_by_id[s.payment_id], s))

    # Graph structure feeds classification (duplicates, orphans) and is
    # reused by the Phase 5 visualization.
    graph = build_graph(invoices, payments, links)
    duplicates = duplicate_suspects(graph, payments_by_id, cfg)

    results = [
        _decide_invoice(
            inv,
            links.get(inv.invoice_id, []),
            flags_by_invoice.get(inv.invoice_id, []),
            inv.invoice_id in duplicates,
            cfg,
        )
        for inv in invoices
    ]

    orphans = [
        OrphanPaymentResult(
            payment_id=pay.payment_id,
            payer_name=pay.payer_name,
            amount=pay.amount,
            currency=pay.currency,
            reference=pay.reference,
            confidence=0.90,
            explanation=(
                "Unmatched: the reference cites no known invoice or PO, and no "
                "open invoice matches by vendor, currency and amount."
            ),
            suggested_action=(
                "Investigate the payment origin; possible advance payment or "
                "missing invoice."
            ),
        )
        for pay in payments
        if pay.payment_id in orphan_payment_ids(graph)
    ]

    status_counts = {s.value: 0 for s in Status}
    for r in results:
        status_counts[r.status.value] += 1

    return ReconciliationResult(
        summary={
            "total_invoices": len(invoices),
            "total_payments": len(payments),
            "orphan_payments": len(orphans),
            "status_counts": status_counts,
            # Business metric: share of invoices safe to auto-approve.
            "auto_match_rate": round(status_counts[Status.MATCHED.value] / len(invoices), 3)
            if invoices else 0.0,
        },
        invoices=results,
        orphan_payments=orphans,
    )
