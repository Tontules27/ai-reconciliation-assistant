"""The portal must start (not crash) when the dataset yields zero records."""

import app.graph as graph_module
import app.layout as layout_module
from reconciliation.models import Status


def test_portal_layout_survives_empty_dataset(monkeypatch):
    empty_summary = {
        "total_invoices": 0,
        "total_payments": 0,
        "orphan_payments": 0,
        "status_counts": {s.value: 0 for s in Status},
        "auto_match_rate": 0.0,
    }

    def fake_get_data(data_dir="data"):
        return empty_summary, []

    monkeypatch.setattr(layout_module, "get_data", fake_get_data)
    monkeypatch.setattr(graph_module, "get_data", fake_get_data)

    layout = layout_module.build_layout()  # must not raise IndexError
    assert layout is not None
