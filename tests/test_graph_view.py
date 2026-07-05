"""Network-view elements mirror the engine's relationships exactly."""

from app.graph import build_elements


def _nodes(elements, cls=None):
    return [e for e in elements if "id" in e["data"]
            and (cls is None or cls in e["classes"].split())]


def _edges(elements, cls=None):
    return [e for e in elements if "source" in e["data"]
            and (cls is None or cls in e["classes"].split())]


def test_graph_structure_matches_engine_output():
    elements = build_elements()
    assert len(_nodes(elements, "invoice")) == 8
    assert len(_nodes(elements, "vendor")) == 8   # all vendors distinct in dataset
    assert len(_nodes(elements, "payment")) == 10
    assert len(_edges(elements, "billed")) == 8   # vendor -> invoice
    assert len(_edges(elements, "paid")) == 9     # every payment except the orphan


def test_duplicate_invoice_has_two_payment_edges_and_orphan_is_isolated():
    elements = build_elements()
    inv_1007_edges = [e for e in _edges(elements, "paid")
                      if e["data"]["target"] == "INV-1007"]
    assert len(inv_1007_edges) == 2  # the duplicate signature, visible as structure

    orphan = next(n for n in _nodes(elements, "payment")
                  if n["data"]["id"] == "PAY-9010")
    assert "orphan" in orphan["classes"]
    touching = [e for e in _edges(elements)
                if "PAY-9010" in (e["data"]["source"], e["data"]["target"])]
    assert touching == []  # disconnected node IS the unmatched signal


def test_every_clickable_node_routes_to_a_record():
    elements = build_elements()
    for node in _nodes(elements, "payment") + _nodes(elements, "invoice"):
        assert node["data"].get("record_id"), node["data"]["id"]
