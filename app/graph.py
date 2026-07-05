"""Network view: the engine's relationship graph rendered with cytoscape.

Same relationships the engine's networkx graph used for classification
(vendors -> invoices <- payments), same status colors as the rest of the
app. The structure is readable at a glance: an invoice with two payment
edges is the duplicate suspect; an isolated payment node is the orphan.
"""

from .data import get_data
from .theme import STATUS_COLORS


def build_elements() -> list[dict]:
    _, records = get_data()
    elements: list[dict] = []
    seen_vendors: set[str] = set()

    for r in records:
        if r["kind"] == "invoice":
            vendor_id = f"vendor::{r['party']}"
            if vendor_id not in seen_vendors:
                seen_vendors.add(vendor_id)
                elements.append({
                    "data": {"id": vendor_id, "label": r["party"],
                             "kind": "vendor", "vendor": r["party"]},
                    "classes": "vendor",
                })
            # kind + ids on the node data drive the per-kind detail panel
            # the tap callback renders (invoice / payment / vendor views).
            elements.append({
                "data": {"id": r["record_id"], "label": r["record_id"],
                         "color": STATUS_COLORS[r["status"]],
                         "kind": "invoice", "record_id": r["record_id"]},
                "classes": "invoice",
            })
            elements.append({
                "data": {"source": vendor_id, "target": r["record_id"]},
                "classes": "billed",
            })
            for p in r["payments"]:
                elements.append({
                    "data": {"id": p["payment_id"], "label": p["payment_id"],
                             "kind": "payment", "record_id": r["record_id"]},
                    "classes": "payment",
                })
                elements.append({
                    "data": {"source": p["payment_id"], "target": r["record_id"],
                             "color": STATUS_COLORS[r["status"]]},
                    "classes": "paid",
                })
        else:
            # Orphan payment: deliberately left disconnected — the isolation
            # IS the visual signal (mirrors degree-0 detection in the engine).
            elements.append({
                "data": {"id": r["record_id"], "label": r["record_id"],
                         "kind": "payment", "record_id": r["record_id"]},
                "classes": "payment orphan",
            })

    return elements


# Shapes carry node kind (never color alone): diamond = vendor,
# rounded square = invoice, circle = payment.
STYLESHEET = [
    {"selector": "node", "style": {
        "label": "data(label)",
        "font-size": "10px",
        "color": "#52514e",
        "text-valign": "bottom",
        "text-margin-y": 6,
        "width": 30, "height": 30,
    }},
    {"selector": ".vendor", "style": {
        "shape": "diamond",
        "background-color": "#c3c2b7",
        "width": 26, "height": 26,
    }},
    {"selector": ".invoice", "style": {
        "shape": "round-rectangle",
        "background-color": "data(color)",
    }},
    {"selector": ".payment", "style": {
        "shape": "ellipse",
        "background-color": "#ffffff",
        "border-width": 2,
        "border-color": "#898781",
        "width": 24, "height": 24,
    }},
    {"selector": ".orphan", "style": {
        "border-style": "dashed",
        "border-color": STATUS_COLORS["Unmatched"],
    }},
    {"selector": "edge", "style": {
        "width": 2.5,
        "curve-style": "bezier",
        "line-color": "data(color)",
    }},
    {"selector": ".billed", "style": {
        "width": 1.5,
        "line-style": "dashed",
        "line-color": "#e1e0d9",
    }},
    {"selector": ":selected", "style": {
        "overlay-color": "#4263eb",
        "overlay-opacity": 0.18,
    }},
]

GRAPH_LAYOUT = {"name": "cose", "animate": False, "padding": 24}
