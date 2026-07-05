"""Portal layout: decision-oriented, not decorative.

Main view = the triage queue (the operator's actual workload) sorted by
risk. The detail panel is explainability-as-UI: it shows WHY the engine
decided — signal breakdown with points, linked payments, and source notes.
"""

import dash_mantine_components as dmc
from dash import dcc, html

from .data import get_data
from .figures import status_bar_chart
from .theme import BADGE_COLORS, STATUS_COLORS


def status_badge(status: str, **kwargs) -> dmc.Badge:
    # Icon+label rule: the status name is always written out, never color alone.
    return dmc.Badge(status, color=BADGE_COLORS[status], variant="light", **kwargs)


def _kpi_card(label: str, value: str, hint: str = "") -> dmc.Card:
    return dmc.Card(
        [
            dmc.Text(label, size="xs", c="dimmed", tt="uppercase", fw=600),
            dmc.Text(value, size="28px", fw=700, mt=4),
            dmc.Text(hint, size="xs", c="dimmed") if hint else None,
        ],
        withBorder=True, radius="md", padding="md",
    )


def card_style(status: str, selected: bool) -> dict:
    """Style of the clickable wrapper. Shared by the initial render and the
    highlight callback, so selection restyles cards WITHOUT re-creating them
    (re-creation would reset n_clicks and swallow subsequent clicks)."""
    del status  # kept in the signature: status-dependent styling lives on the card
    return {
        "cursor": "pointer",
        "borderRadius": "8px",
        # Selection is shown by outline, not by repainting status colors.
        "outline": "2px solid #4263eb" if selected else "none",
    }


def queue_card(record: dict, selected: bool) -> html.Div:
    # dmc.Card has NO n_clicks prop, so the pattern-matching id lives on a
    # plain html.Div wrapper — the one Dash component guaranteed clickable.
    card = dmc.Card(
        [
            dmc.Group(
                [
                    dmc.Stack(
                        [
                            dmc.Text(record["record_id"], fw=600, size="sm"),
                            dmc.Text(record["party"], size="xs", c="dimmed"),
                        ],
                        gap=0,
                    ),
                    dmc.Stack(
                        [
                            status_badge(record["status"]),
                            dmc.Text(record["amount"], size="sm", ta="right"),
                        ],
                        gap=4, align="flex-end",
                    ),
                ],
                justify="space-between", wrap="nowrap",
            ),
            dmc.Group(
                [
                    dmc.Text(f"confidence {record['confidence']:.2f}", size="xs", c="dimmed"),
                    *(dmc.Badge(reason, size="xs", variant="outline", color="gray")
                      for reason in record["review_reasons"]),
                ],
                gap="xs", mt=6,
            ),
        ],
        withBorder=True, radius="md", padding="sm",
        style={"borderLeft": f"4px solid {STATUS_COLORS[record['status']]}"},
    )
    return html.Div(
        card,
        id={"type": "queue-card", "index": record["record_id"]},
        style=card_style(record["status"], selected),
    )


def _detail_table(head: list[str], body: list[list]) -> dmc.Table:
    return dmc.Table(
        data={"head": head, "body": body},
        striped=True, highlightOnHover=False, withTableBorder=True,
        verticalSpacing="xs", horizontalSpacing="sm",
    )


def detail_panel(record: dict) -> dmc.Stack:
    """The WHY view: decision, evidence breakdown, money, notes, next step."""
    signals_rows = [
        [s["detail"], f"{s['points']:+.2f}"] for s in record["signals"]
    ]
    payments_rows = [
        [p["payment_id"], p["date"], p["payer"], p["amount"], p["reference"]]
        for p in record["payments"]
    ]

    children = [
        dmc.Group(
            [
                dmc.Title(record["record_id"], order=3),
                status_badge(record["status"], size="lg"),
            ],
            justify="space-between",
        ),
        dmc.Text(record["party"], c="dimmed", size="sm"),
        dmc.Group(
            [
                dmc.Text(f"Amount: {record['amount']}", size="sm", fw=500),
                dmc.Text(f"Confidence: {record['confidence']:.2f}", size="sm", fw=500),
                dmc.Text(f"Remaining: {record['remaining_balance']}", size="sm", fw=500,
                         c="orange") if record["remaining_balance"] else None,
            ],
            gap="lg",
        ),
        dmc.Alert(record["explanation"], title="Why this decision", color="gray",
                  variant="light", radius="md"),
        dmc.Alert(record["suggested_action"], title="Suggested action",
                  color=BADGE_COLORS[record["status"]], variant="light", radius="md"),
    ]

    if signals_rows:
        children += [
            dmc.Divider(label="Signal breakdown (sums to the confidence score)",
                        labelPosition="left", mt="sm"),
            _detail_table(["Evidence", "Points"], signals_rows),
        ]
    if payments_rows:
        children += [
            dmc.Divider(label="Linked payments", labelPosition="left", mt="sm"),
            _detail_table(["Payment", "Date", "Payer", "Amount", "Reference"], payments_rows),
        ]
    if record["related_notes"]:
        children += [
            dmc.Divider(label="Related notes", labelPosition="left", mt="sm"),
            *(dmc.Blockquote(note, color="gray", radius="md", mt="xs")
              for note in record["related_notes"]),
        ]

    return dmc.Stack([c for c in children if c is not None], gap="sm")


def build_layout() -> dmc.MantineProvider:
    summary, records = get_data()
    needs_attention = (summary["status_counts"]["Needs Review"]
                       + summary["status_counts"]["Suspicious"])
    statuses = list(STATUS_COLORS)

    return dmc.MantineProvider(
        dmc.Container(
            [
                # Selection state; defaults to the riskiest record.
                dcc.Store(id="selected", data=records[0]["record_id"]),

                dmc.Group(
                    [
                        dmc.Title("Reconciliation Portal", order=2),
                        dmc.Text("read-only · recomputed from source files on start",
                                 size="xs", c="dimmed"),
                    ],
                    justify="space-between", mt="md",
                ),

                dmc.SimpleGrid(
                    [
                        _kpi_card("Invoices", str(summary["total_invoices"])),
                        _kpi_card("Auto-match rate", f"{summary['auto_match_rate']:.0%}",
                                  "share safe to auto-approve"),
                        _kpi_card("Needs attention", str(needs_attention),
                                  "review + suspicious"),
                        _kpi_card("Orphan payments", str(summary["orphan_payments"]),
                                  "no matching invoice"),
                    ],
                    cols=4, mt="md",
                ),

                dmc.Card(
                    dcc.Graph(figure=status_bar_chart(summary["status_counts"]),
                              config={"displayModeBar": False}),
                    withBorder=True, radius="md", padding="xs", mt="md",
                ),

                # Filters: one row above the content they control.
                dmc.Group(
                    [
                        dmc.TextInput(id="search", placeholder="Search id, vendor or payer…",
                                      w=320),
                        dmc.MultiSelect(id="status-filter", data=statuses,
                                        placeholder="Filter by status", w=360,
                                        clearable=True),
                    ],
                    mt="md",
                ),

                dmc.Grid(
                    [
                        dmc.GridCol(
                            dmc.ScrollArea(
                                dmc.Stack(id="queue", gap="xs"),
                                h=620, type="auto",
                            ),
                            span=5,
                        ),
                        dmc.GridCol(
                            dmc.Card(id="detail", withBorder=True, radius="md",
                                     padding="lg"),
                            span=7,
                        ),
                    ],
                    gutter="md", mt="sm", mb="xl",
                ),
            ],
            size="xl",
        ),
        forceColorScheme="light",
    )
