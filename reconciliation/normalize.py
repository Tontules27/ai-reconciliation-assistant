"""Normalization and reference-token extraction shared across the pipeline."""

import re

from rapidfuzz import fuzz

# Trailing legal-form tokens carry no identity signal ("Grupo Norte SA" and
# "Grupo Norte" are the same counterparty). Stripped from the END only, so
# meaningful words are never removed mid-name.
_LEGAL_SUFFIXES = {"llc", "inc", "ltd", "ltda", "sa", "srl", "corp", "co",
                   "gmbh", "plc", "llp", "cv", "sac"}

# Invoice numbers appear as "INV-1001", "INV1002" or "invoice 1001".
# Requiring 3+ digits avoids grabbing small figures like "10 USD".
_INVOICE_REF_RE = re.compile(
    r"\bINV[-\s]?(\d{3,})\b|\binvoice\s*#?\s*(\d{3,})\b", re.IGNORECASE
)
_PO_REF_RE = re.compile(r"\bPO[-\s]?(\d{3,})\b", re.IGNORECASE)


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, drop trailing legal suffixes."""
    tokens = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_similarity(a: str, b: str) -> float:
    """0-100 similarity between two party names, after normalization.

    token_sort_ratio is word-order independent, so abbreviation and typo
    variants ("Delta Technology Services" vs "Delta Tech Services") still
    score high, while unrelated names score low.
    """
    return fuzz.token_sort_ratio(normalize_name(a), normalize_name(b))


def extract_invoice_numbers(text: str) -> set[str]:
    """Numeric invoice tokens cited in free text, e.g. {'1001'}."""
    return {m.group(1) or m.group(2) for m in _INVOICE_REF_RE.finditer(text)}


def extract_po_numbers(text: str) -> set[str]:
    return {m.group(1) for m in _PO_REF_RE.finditer(text)}


def invoice_number(invoice_id: str) -> str:
    """Canonical numeric token of an invoice id: 'INV-1001' -> '1001'."""
    return re.sub(r"\D", "", invoice_id)


def po_number_token(po_number: str) -> str:
    """Canonical numeric token of a PO: 'PO-8891' -> '8891'."""
    return re.sub(r"\D", "", po_number)
