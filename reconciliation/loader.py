"""Load the three input files into validated models.

csv.DictReader yields raw strings; pydantic validates "1250.00" straight
into Decimal without ever constructing a float, so amounts stay exact.
"""

import csv
import json
from pathlib import Path

from .models import Invoice, Note, Payment


def load_invoices(path: Path) -> list[Invoice]:
    with open(path, newline="", encoding="utf-8") as f:
        return [Invoice(**row) for row in csv.DictReader(f)]


def load_payments(path: Path) -> list[Payment]:
    with open(path, newline="", encoding="utf-8") as f:
        return [Payment(**row) for row in csv.DictReader(f)]


def load_notes(path: Path) -> list[Note]:
    with open(path, encoding="utf-8") as f:
        return [Note(**item) for item in json.load(f)]
