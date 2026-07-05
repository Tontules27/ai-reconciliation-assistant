"""Portal callbacks: filter/search the queue, select a record, show detail.

Structure matters here: the queue children are rebuilt ONLY when filters
change. Selection updates card styles via a pattern-matching output instead —
re-creating the clicked components would reset their n_clicks counters and
make every card clickable only once.
"""

import dash_mantine_components as dmc
from dash import ALL, Input, Output, State, ctx, no_update

from .data import find_payment, find_record, get_data, vendor_invoices
from .layout import card_style, detail_panel, payment_panel, queue_card, vendor_panel


def register_callbacks(app) -> None:
    @app.callback(
        Output("queue", "children"),
        Input("search", "value"),
        Input("status-filter", "value"),
        State("selected", "data"),
    )
    def render_queue(search, statuses, selected):
        _, records = get_data()
        needle = (search or "").strip().lower()
        rows = [
            r for r in records
            if (not statuses or r["status"] in statuses)
            and (not needle
                 or needle in r["record_id"].lower()
                 or needle in r["party"].lower()
                 or any(needle in p["payment_id"].lower() for p in r["payments"]))
        ]
        if not rows:
            return dmc.Text("No records match the current filters.", c="dimmed", size="sm")
        return [queue_card(r, selected=(r["record_id"] == selected)) for r in rows]

    @app.callback(
        Output("selected", "data"),
        Input({"type": "queue-card", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def select_record(clicks):
        # Queue re-renders also fire this input with all-None clicks; ignore.
        if not clicks or not any(clicks):
            return no_update
        return ctx.triggered_id["index"]

    @app.callback(
        Output({"type": "queue-card", "index": ALL}, "style"),
        Input("selected", "data"),
        State({"type": "queue-card", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def highlight_selected(selected, ids):
        styles = []
        for card_id in ids:
            record = find_record(card_id["index"])
            styles.append(card_style(record["status"], card_id["index"] == selected))
        return styles

    @app.callback(Output("detail", "children"), Input("selected", "data"))
    def render_detail(selected):
        record = find_record(selected)
        if record is None:
            return dmc.Text("Select a record from the queue.", c="dimmed")
        return detail_panel(record)

    @app.callback(
        Output("graph-detail", "children"),
        Input("network", "tapNodeData"),
        prevent_initial_call=True,
    )
    def render_graph_detail(node):
        # Every node kind gets its own view: invoices show the decision,
        # payments show their fields + where they landed, vendors show
        # their invoice portfolio.
        if not node:
            return no_update
        if node.get("kind") == "invoice":
            return detail_panel(find_record(node["record_id"]))
        if node.get("kind") == "payment":
            payment, owner = find_payment(node["id"])
            if payment is None:
                return no_update
            return payment_panel(payment, owner)
        if node.get("kind") == "vendor":
            return vendor_panel(node["vendor"], vendor_invoices(node["vendor"]))
        return no_update

    # The graph mounts inside a hidden tab: the canvas starts at size 0 and
    # the initial fit leaves a broken camera (zoom=1e50, pan=null). When the
    # tab becomes visible, repair it client-side in one ordered sequence:
    # resize the canvas, re-run the layout, and re-fit the viewport.
    app.clientside_callback(
        """
        function(tab) {
            if (tab !== "graph") { return window.dash_clientside.no_update; }
            setTimeout(function () {
                const el = document.getElementById("network");
                const cy = el && el._cyreg && el._cyreg.cy;
                if (!cy) { return; }
                cy.resize();
                cy.layout({name: "cose", animate: false, padding: 24}).run();
                cy.fit(undefined, 30);
            }, 120);
            return Date.now();
        }
        """,
        Output("graph-visible", "data"),
        Input("main-tabs", "value"),
        prevent_initial_call=True,
    )
