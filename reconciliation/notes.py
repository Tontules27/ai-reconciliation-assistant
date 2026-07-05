"""Turn free-text notes into structured, deterministic flags.

This is the only place unstructured text enters the pipeline. Extraction is
keyword/regex based so the engine runs identically with or without an LLM;
Phase 3 may use an LLM to *phrase* explanations, never to change these facts.
"""

import re
from decimal import Decimal

from rapidfuzz import fuzz

from .config import EngineConfig
from .models import Invoice, Note, NoteFlag, NoteFlagType
from .normalize import (
    extract_invoice_numbers,
    extract_po_numbers,
    invoice_number,
    normalize_name,
    po_number_token,
)

# An amount is only trusted as a discount figure when it is anchored to a
# currency code ("10 USD"), so invoice numbers in the same sentence are
# never mistaken for money.
_CURRENCY_AMOUNT_RE = re.compile(r"\b(\d+(?:\.\d{1,2})?)\s*(usd|eur|mxn)\b", re.IGNORECASE)
_CURRENCY_CODE_RE = re.compile(r"\b(usd|eur|mxn)\b", re.IGNORECASE)


def _detect_flag_types(text: str) -> list[NoteFlagType]:
    t = text.lower()
    types = []
    if "partial" in t:
        types.append(NoteFlagType.PARTIAL_PAYMENT)
    if "discount" in t:
        types.append(NoteFlagType.DISCOUNT)
    if any(k in t for k in ("twice", "duplicate", "double payment", "same payment")):
        types.append(NoteFlagType.DUPLICATE_WARNING)
    if "typo" in t:
        types.append(NoteFlagType.NAME_TYPO_CONFIRMED)
    if "review" in t and _CURRENCY_CODE_RE.search(t):
        types.append(NoteFlagType.CURRENCY_REVIEW)
    return types


def _target_invoices(note: Note, invoices: list[Invoice], cfg: EngineConfig) -> list[str]:
    """Which invoices does this note talk about?

    Explicit ids win: if the note cites an invoice or PO number, attach only
    there. Vendor-name fuzzy matching is a fallback for id-less notes only —
    otherwise a note naming "ACME Logistics" would also leak onto
    "ACME Logistics LLC" and could corrupt an unrelated decision.
    """
    by_number = {invoice_number(inv.invoice_id): inv.invoice_id for inv in invoices}
    by_po = {po_number_token(inv.po_number): inv.invoice_id for inv in invoices}

    cited = extract_invoice_numbers(note.text) | extract_po_numbers(note.text)
    targets = sorted(
        {by_number[n] for n in cited if n in by_number}
        | {by_po[n] for n in cited if n in by_po}
    )
    if targets:
        return targets

    norm_text = normalize_name(note.text)
    return sorted(
        inv.invoice_id
        for inv in invoices
        if fuzz.partial_ratio(normalize_name(inv.vendor), norm_text)
        >= cfg.note_vendor_threshold
    )


def extract_flags(
    notes: list[Note], invoices: list[Invoice], cfg: EngineConfig
) -> list[NoteFlag]:
    flags = []
    for note in notes:
        targets = _target_invoices(note, invoices, cfg)
        if not targets:
            continue
        for flag_type in _detect_flag_types(note.text):
            discount = None
            if flag_type is NoteFlagType.DISCOUNT:
                m = _CURRENCY_AMOUNT_RE.search(note.text)
                # Decimal from the matched string — same no-float rule as CSV.
                discount = Decimal(m.group(1)) if m else None
            flags.append(
                NoteFlag(
                    type=flag_type,
                    invoice_ids=targets,
                    discount_amount=discount,
                    note=note,
                )
            )
    return flags
