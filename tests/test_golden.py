"""Golden-set tests: the expected outcome of every row in the dataset.

These expectations are the labels for the eval loop: thresholds and weights
in config.py may be tuned freely, as long as precision/recall against this
set stays at 1.0. On a real-scale dataset the golden set would grow from
reviewed operator decisions and the bar would be a tuned trade-off rather
than perfection; the mechanism is the same.

Tests assert dataset outcomes (allowed); the engine itself never hardcodes
them — general rules must produce these results.
"""

import subprocess
import sys
from decimal import Decimal

import pytest

from reconciliation.engine import reconcile
from reconciliation.models import Status

# --- Labels: one entry per invoice, plus expected orphan payments -----------

GOLDEN = {
    # Name typo, but invoice id + exact amount agree.
    "INV-1001": dict(status=Status.MATCHED, payments={"PAY-9001"},
                     remaining=None, reasons=[]),
    # Compact reference "INV1002"; legal suffix stripped from vendor name.
    "INV-1002": dict(status=Status.MATCHED, payments={"PAY-9002"},
                     remaining=None, reasons=[]),
    # Underpayment corroborated by a partial-payment note.
    "INV-1003": dict(status=Status.PARTIAL_MATCH, payments={"PAY-9003"},
                     remaining=Decimal("1300.00"), reasons=[]),
    # PO and amount exact, but payer identity does not match the vendor.
    "INV-1004": dict(status=Status.NEEDS_REVIEW, payments={"PAY-9004"},
                     remaining=None, reasons=["IDENTITY_MISMATCH"]),
    # 1490 + 10 documented discount == 1500 -> notes change the outcome.
    "INV-1005": dict(status=Status.MATCHED, payments={"PAY-9005"},
                     remaining=None, reasons=[]),
    # Same-currency (MXN) exact match with a minor name variant.
    "INV-1006": dict(status=Status.MATCHED, payments={"PAY-9006"},
                     remaining=None, reasons=[]),
    # Two payments of the same amount -> possible duplicate.
    "INV-1007": dict(status=Status.SUSPICIOUS, payments={"PAY-9007", "PAY-9008"},
                     remaining=None, reasons=["POSSIBLE_DUPLICATE"]),
    # Amount identical but EUR != USD -> currencies are never equated.
    "INV-1008": dict(status=Status.NEEDS_REVIEW, payments={"PAY-9009"},
                     remaining=None, reasons=["CURRENCY_MISMATCH"]),
}

EXPECTED_ORPHANS = {"PAY-9010"}


@pytest.fixture(scope="session")
def result():
    return reconcile("data")


@pytest.fixture(scope="session")
def by_id(result):
    return {r.invoice_id: r for r in result.invoices}


# --- Per-row assertions ------------------------------------------------------


@pytest.mark.parametrize("invoice_id", GOLDEN)
def test_invoice_outcome(by_id, invoice_id):
    expected = GOLDEN[invoice_id]
    got = by_id[invoice_id]
    assert got.status == expected["status"]
    assert set(got.matched_payment_ids) == expected["payments"]
    assert got.remaining_balance == expected["remaining"]
    assert got.review_reasons == expected["reasons"]


def test_orphan_payments(result):
    assert {o.payment_id for o in result.orphan_payments} == EXPECTED_ORPHANS
    assert all(o.status == Status.UNMATCHED for o in result.orphan_payments)


# --- Eval metrics: golden statuses as labels ---------------------------------


def test_precision_recall(by_id):
    """Per-status precision/recall with GOLDEN as ground truth.

    This is the tuning harness: change a threshold in config.py, rerun, and
    see exactly which status degrades and how.
    """
    labels = {inv_id: g["status"] for inv_id, g in GOLDEN.items()}
    preds = {inv_id: by_id[inv_id].status for inv_id in GOLDEN}

    report = {}
    for status in Status:
        tp = sum(1 for i in labels if labels[i] == status and preds[i] == status)
        fp = sum(1 for i in labels if labels[i] != status and preds[i] == status)
        fn = sum(1 for i in labels if labels[i] == status and preds[i] != status)
        if tp + fp + fn == 0:
            continue  # status absent from both labels and predictions
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        report[status.value] = (precision, recall)

    for status, (precision, recall) in report.items():
        print(f"{status}: precision={precision:.2f} recall={recall:.2f}")

    # On this dataset the engine must be perfect; a larger golden set would
    # assert tuned minimums per status instead (e.g. Matched precision first).
    assert all(p == 1.0 and r == 1.0 for p, r in report.values()), report


# --- Structural guardrails ----------------------------------------------------


def test_remaining_balance_is_exact_decimal(by_id):
    balance = by_id["INV-1003"].remaining_balance
    assert isinstance(balance, Decimal)
    assert balance == Decimal("1300.00")  # 4300.00 - 3000.00, no float drift


def test_confidence_bounds(result):
    assert all(0.0 <= r.confidence <= 1.0 for r in result.invoices)


def test_triage_separation(result):
    """Every auto-matched invoice must outrank every review case.

    Guardrail for weight tuning: if this breaks, the triage queue would
    surface a Matched invoice above a Suspicious one.
    """
    matched = [r.confidence for r in result.invoices if r.status == Status.MATCHED]
    review = [r.confidence for r in result.invoices
              if r.status in (Status.NEEDS_REVIEW, Status.SUSPICIOUS)]
    assert min(matched) > max(review)


def test_deterministic_output():
    # Same input, same output — byte for byte. Reproducibility is the audit
    # requirement behind keeping every decision rule-based.
    assert reconcile("data").model_dump_json() == reconcile("data").model_dump_json()


def test_engine_has_no_ui_dependencies():
    """The reconciliation package must stay importable without Dash/Flask.

    Checked in a clean subprocess: under pytest, Dash's own pytest plugin
    already lives in sys.modules, so inspecting this process would lie.
    """
    code = (
        "import sys; import reconciliation; "
        "ui = [m for m in sys.modules if m in ('dash', 'flask') "
        "or m.startswith(('dash.', 'flask.'))]; "
        "assert not ui, ui"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
