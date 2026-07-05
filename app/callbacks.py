"""Portal callbacks: filter/search the queue, select a record, show detail.

Structure matters here: the queue children are rebuilt ONLY when filters
change. Selection updates card styles via a pattern-matching output instead —
re-creating the clicked components would reset their n_clicks counters and
make every card clickable only once.
"""

import dash_mantine_components as dmc
from dash import ALL, Input, Output, State, ctx, no_update

from .data import find_record, get_data
from .layout import card_style, detail_panel, queue_card


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
