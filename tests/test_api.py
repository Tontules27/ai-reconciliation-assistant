"""REST surface: GET /reconciliation returns the engine's JSON."""

import pytest

from app.main import create_app


@pytest.fixture(scope="module")
def client():
    return create_app().server.test_client()


def test_reconciliation_endpoint_returns_engine_json(client):
    resp = client.get("/reconciliation")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"

    data = resp.get_json()
    assert data["summary"]["total_invoices"] == 8
    assert {i["invoice_id"] for i in data["invoices"]} == {
        f"INV-100{n}" for n in range(1, 9)
    }
    assert data["orphan_payments"][0]["payment_id"] == "PAY-9010"

    # Money stays exact: Decimal serializes as a JSON string, never a float.
    inv_1003 = next(i for i in data["invoices"] if i["invoice_id"] == "INV-1003")
    assert inv_1003["remaining_balance"] == "1300.00"
