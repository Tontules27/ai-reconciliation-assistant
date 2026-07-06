"""Dash app factory. The UI layer imports the engine; never the reverse."""

import dash
import dash_mantine_components as dmc
from dash import html
from flask import Response

# dash-mantine-components >= 0.14 renders on React 18; Dash 2.x defaults to
# React 16, so pin it explicitly (Dash 3 would make this a no-op default).
from dash import _dash_renderer

_dash_renderer._set_react_version("18.2.0")

from reconciliation.engine import reconcile

from .callbacks import register_callbacks
from .layout import build_layout


def create_app() -> dash.Dash:
    app = dash.Dash(__name__, title="Reconciliation Portal")
    app.layout = build_layout()
    # Load-time id validation stays ON app-wide (a typoed component id in any
    # callback still fails fast). Only the review controls are created
    # dynamically by the detail-panel callback, so declare them in a
    # validation-only superset instead of suppressing validation everywhere.
    app.validation_layout = html.Div([
        app.layout,
        dmc.TextInput(id="review-note"),
    ])
    register_callbacks(app)

    # REST surface: Dash runs on Flask, so the engine's JSON is one route
    # away. Recomputed from the source files on every request — same
    # contract as the CLI (Decimal serialized as strings).
    @app.server.route("/reconciliation")
    def reconciliation_json() -> Response:
        return Response(reconcile("data").model_dump_json(),
                        mimetype="application/json")

    return app
