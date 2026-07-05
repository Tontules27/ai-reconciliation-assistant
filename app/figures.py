"""Plotly figures for the portal.

Mark specs follow the dataviz method: thin horizontal bars with 4px rounded
data-ends, direct value labels (so no legend is needed — the axis names each
status), recessive hairline grid, muted axis ink, hover tooltip per mark.
"""

import plotly.graph_objects as go

from .theme import CHART, SEVERITY_ORDER, STATUS_COLORS


def status_bar_chart(status_counts: dict[str, int]) -> go.Figure:
    # Severity order top-to-bottom mirrors the triage queue ordering.
    labels = [s for s in SEVERITY_ORDER if s in status_counts]
    values = [status_counts[s] for s in labels]
    colors = [STATUS_COLORS[s] for s in labels]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colors),
            text=values,
            textposition="outside",
            textfont=dict(color=CHART["ink"], size=13),
            hovertemplate="%{y}: %{x} invoice(s)<extra></extra>",
        )
    )
    fig.update_layout(
        barcornerradius=4,
        bargap=0.45,  # thin marks
        showlegend=False,
        plot_bgcolor=CHART["surface"],
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=8, b=8),
        height=230,
        xaxis=dict(
            showgrid=True, gridcolor=CHART["grid"], zeroline=False,
            tickfont=dict(color=CHART["muted"], size=12),
            # headroom so outside value labels never clip
            range=[0, max(values) * 1.25 if values else 1],
        ),
        yaxis=dict(
            autorange="reversed",  # most severe on top
            showgrid=False,
            tickfont=dict(color=CHART["muted"], size=12),
        ),
    )
    return fig
