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

# An amount is only trusted as a discount figure when it is (a) anchored to a
# currency code ("10 USD") so invoice numbers are never mistaken for money,
# AND (b) adjacent to the word "discount" — a note that also states the paid
# amount must not have that amount read as the discount. Two shapes:
# "10 USD [up to 3 words] discount" and "discount of 10 USD".
_DISCOUNT_AMOUNT_RE = re.compile(
    r"\b(\d+(?:\.\d{1,2})?)\s*(?:usd|eur|mxn)\b(?:\s+\w+){0,3}\s+discount"
    r"|discount\s+of\s+(\d+(?:\.\d{1,2})?)\s*(?:usd|eur|mxn)\b",
    re.IGNORECASE,
)
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


def _target_invoices(note: Note, invoices: list[Invoice],
                     cfg: EngineConfig) -> tuple[list[str], bool]:
    """(invoice ids this note talks about, whether they were cited explicitly).

    Explicit ids win: if the note cites an invoice or PO number, attach only
    there (each token resolved in its own namespace). Vendor-name fuzzy
    matching is a fallback for id-less notes only — otherwise a note naming
    "ACME Logistics" would also leak onto "ACME Logistics LLC" and could
    corrupt an unrelated decision.
    """
    by_number = {invoice_number(inv.invoice_id): inv.invoice_id for inv in invoices}
    by_po = {po_number_token(inv.po_number): inv.invoice_id for inv in invoices}

    targets = sorted(
        {by_number[n] for n in extract_invoice_numbers(note.text) if n in by_number}
        | {by_po[n] for n in extract_po_numbers(note.text) if n in by_po}
    )
    if targets:
        return targets, True

    norm_text = normalize_name(note.text)
    return sorted(
        inv.invoice_id
        for inv in invoices
        if fuzz.partial_ratio(normalize_name(inv.vendor), norm_text)
        >= cfg.note_vendor_threshold
    ), False


def extract_flags(
    notes: list[Note], invoices: list[Invoice], cfg: EngineConfig
) -> list[NoteFlag]:
    flags = []
    for note in notes:
        targets, explicit = _target_invoices(note, invoices, cfg)
        if not targets:
            continue
        for flag_type in _detect_flag_types(note.text):
            discount = None
            # A discount amount is only trusted when the note cites the exact
            # invoice/PO: a vendor-level note attaches to EVERY invoice of
            # that vendor, and applying its amount everywhere could silently
            # write off money that is genuinely outstanding.
            if flag_type is NoteFlagType.DISCOUNT and explicit:
                m = _DISCOUNT_AMOUNT_RE.search(note.text)
                # Decimal from the matched string — same no-float rule as CSV.
                discount = Decimal(m.group(1) or m.group(2)) if m else None
            flags.append(
                NoteFlag(
                    type=flag_type,
                    invoice_ids=targets,
                    discount_amount=discount,
                    note=note,
                )
            )
    return flags
