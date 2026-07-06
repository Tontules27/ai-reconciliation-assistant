"""Dash app factory. The UI layer imports the engine; never the reverse."""

import dash

# dash-mantine-components >= 0.14 renders on React 18; Dash 2.x defaults to
# React 16, so pin it explicitly (Dash 3 would make this a no-op default).
from dash import _dash_renderer

_dash_renderer._set_react_version("18.2.0")

from .callbacks import register_callbacks
from .layout import build_layout


def create_app() -> dash.Dash:
    # suppress_callback_exceptions: the review controls (e.g. "review-note")
    # are created by the detail-panel callback, not the initial layout, so
    # Dash's load-time validation would flag them as missing otherwise.
    app = dash.Dash(__name__, title="Reconciliation Portal",
                    suppress_callback_exceptions=True)
    app.layout = build_layout()
    register_callbacks(app)
    return app
