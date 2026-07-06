"""Review store: current-decision projection + append-only audit trail."""

import pytest

from app.store import clear_decision, get_audit_log, get_decisions, record_decision


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "review-test.db"


def test_decision_roundtrip_with_who_what_when(db):
    record_decision("INV-1004", "rejected", "ana", "payer unverified", db_path=db)
    decision = get_decisions(db_path=db)["INV-1004"]
    assert decision["decision"] == "rejected"          # what
    assert decision["reviewer"] == "ana"               # who
    assert decision["note"] == "payer unverified"
    assert decision["decided_at"]                      # when (UTC ISO)


def test_new_decision_replaces_current_but_audit_keeps_both(db):
    record_decision("INV-1007", "marked_duplicate", "ana", db_path=db)
    record_decision("INV-1007", "resolved", "luis", "refund confirmed", db_path=db)

    assert get_decisions(db_path=db)["INV-1007"]["decision"] == "resolved"
    log = get_audit_log(db_path=db)
    assert [(e["action"], e["reviewer"]) for e in log] == [
        ("resolved", "luis"), ("marked_duplicate", "ana"),  # newest first
    ]


def test_clear_removes_decision_and_is_audited(db):
    record_decision("INV-1001", "approved", "ana", db_path=db)
    clear_decision("INV-1001", "ana", db_path=db)

    assert "INV-1001" not in get_decisions(db_path=db)
    assert get_audit_log(db_path=db)[0]["action"] == "cleared"


def test_clearing_nothing_adds_no_audit_noise(db):
    clear_decision("INV-9999", "ana", db_path=db)
    assert get_audit_log(db_path=db) == []


def test_unknown_decision_rejected(db):
    with pytest.raises(ValueError):
        record_decision("INV-1001", "shredded", "ana", db_path=db)
