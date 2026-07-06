"""Portal layout: decision-oriented, not decorative.

Main view = the triage queue (the operator's actual workload) sorted by
risk. The detail panel is explainability-as-UI: it shows WHY the engine
decided — signal breakdown with points, linked payments, and source notes.
"""

import dash_cytoscape as cyto
import dash_mantine_components as dmc
from dash import dcc, html

from .data import get_data
from .figures import status_bar_chart
from .graph import GRAPH_LAYOUT, STYLESHEET, build_elements
from .theme import BADGE_COLORS, DECISION_COLORS, STATUS_COLORS


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


def queue_card(record: dict, selected: bool, decision: dict | None = None) -> html.Div:
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
                    dmc.Badge(f"✓ {decision['decision'].replace('_', ' ')}", size="xs",
                              variant="dot", color=DECISION_COLORS[decision["decision"]])
                    if decision else None,
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


def review_section(record_id: str, decision: dict | None) -> list:
    """Manual review controls: current decision (who/when) + action buttons.

    Only rendered in the triage detail panel so the pattern-matching button
    ids exist exactly once in the page.
    """
    del record_id  # the apply callback reads the selection from the store
    children = [dmc.Divider(label="Manual review", labelPosition="left", mt="sm")]
    if decision:
        children.append(dmc.Alert(
            f"{decision['decision'].replace('_', ' ')} by {decision['reviewer']} "
            f"at {decision['decided_at']}"
            + (f" — “{decision['note']}”" if decision["note"] else ""),
            title="Current decision",
            color=DECISION_COLORS[decision["decision"]], variant="light", radius="md",
        ))
    children += [
        dmc.TextInput(id="review-note", placeholder="Optional note for the audit trail…"),
        dmc.Group(
            [
                dmc.Button("Approve", color="green", size="xs",
                           id={"type": "review-btn", "action": "approved"}),
                dmc.Button("Reject", color="red", size="xs",
                           id={"type": "review-btn", "action": "rejected"}),
                dmc.Button("Mark duplicate", color="orange", size="xs",
                           id={"type": "review-btn", "action": "marked_duplicate"}),
                dmc.Button("Resolved", color="blue", size="xs",
                           id={"type": "review-btn", "action": "resolved"}),
                dmc.Button("Clear", color="gray", size="xs", variant="subtle",
                           id={"type": "review-btn", "action": "clear"},
                           display="block" if decision else "none"),
            ],
            gap="xs",
        ),
    ]
    return children


def detail_panel(record: dict, decision: dict | None = None,
                 with_review: bool = False) -> dmc.Stack:
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
    if with_review:
        children += review_section(record["record_id"], decision)

    return dmc.Stack([c for c in children if c is not None], gap="sm")


def _queue_tab(statuses: list[str]) -> dmc.Stack:
    return dmc.Stack(
        [
            # Filters: one row above the content they control.
            dmc.Group(
                [
                    dmc.TextInput(id="search", placeholder="Search id, vendor or payer…",
                                  w=320),
                    dmc.MultiSelect(id="status-filter", data=statuses,
                                    placeholder="Filter by status", w=360,
                                    clearable=True),
                ],
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
                gutter="md", mb="xl",
            ),
        ],
        gap="sm",
    )


def _legend_item(color: str, label: str) -> dmc.Group:
    swatch = html.Div(style={"width": 18, "height": 4, "borderRadius": 2,
                             "backgroundColor": color})
    return dmc.Group([swatch, dmc.Text(label, size="xs", c="dimmed")], gap=6)


def _graph_tab() -> dmc.Stack:
    legend = dmc.Group(
        [
            *(_legend_item(color, status) for status, color in STATUS_COLORS.items()),
            dmc.Text("◆ vendor · ▢ invoice · ○ payment (dashed = orphan)",
                     size="xs", c="dimmed", ml="md"),
        ],
        gap="md",
    )
    return dmc.Stack(
        [
            legend,
            dmc.Grid(
                [
                    dmc.GridCol(
                        dmc.Card(
                            cyto.Cytoscape(
                                id="network",
                                elements=build_elements(),
                                stylesheet=STYLESHEET,
                                layout=GRAPH_LAYOUT,
                                responsive=True,
                                style={"width": "100%", "height": "620px"},
                            ),
                            withBorder=True, radius="md", padding="xs",
                        ),
                        span=7,
                    ),
                    dmc.GridCol(
                        dmc.Card(
                            dmc.Text("Tap any node — invoice, payment or vendor — "
                                     "to inspect it.", c="dimmed", size="sm"),
                            id="graph-detail", withBorder=True, radius="md",
                            padding="lg",
                        ),
                        span=5,
                    ),
                ],
                gutter="md", mb="xl",
            ),
        ],
        gap="sm",
    )


def payment_panel(payment: dict, owner: dict) -> dmc.Stack:
    """Payment-centric view: the payment's own fields, plus where it landed."""
    is_orphan = owner["kind"] == "payment"
    children = [
        dmc.Group(
            [
                dmc.Title(payment["payment_id"], order=3),
                status_badge(owner["status"], size="lg") if is_orphan
                else dmc.Badge("payment", color="gray", variant="outline", size="lg"),
            ],
            justify="space-between",
        ),
        dmc.Text(payment["payer"], c="dimmed", size="sm"),
        _detail_table(
            ["Field", "Value"],
            [
                ["Date", payment["date"]],
                ["Amount", payment["amount"]],
                ["Reference", payment["reference"]],
            ],
        ),
    ]
    if is_orphan:
        children += [
            dmc.Alert(owner["explanation"], title="Why it is unmatched",
                      color="gray", variant="light", radius="md"),
            dmc.Alert(owner["suggested_action"], title="Suggested action",
                      color=BADGE_COLORS[owner["status"]], variant="light", radius="md"),
        ]
    else:
        children += [
            dmc.Divider(label="Applied to invoice", labelPosition="left", mt="sm"),
            dmc.Group(
                [
                    dmc.Text(owner["record_id"], fw=600),
                    status_badge(owner["status"]),
                    dmc.Text(owner["amount"], size="sm"),
                    dmc.Text(f"confidence {owner['confidence']:.2f}", size="sm", c="dimmed"),
                ],
                gap="md",
            ),
            dmc.Alert(owner["explanation"], title="Why this link", color="gray",
                      variant="light", radius="md"),
        ]
    return dmc.Stack(children, gap="sm")


def vendor_panel(vendor: str, invoices: list[dict]) -> dmc.Stack:
    """Vendor-centric view: every invoice billed by this counterparty."""
    counts: dict[str, int] = {}
    for r in invoices:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return dmc.Stack(
        [
            dmc.Group(
                [
                    dmc.Title(vendor, order=3),
                    dmc.Badge("vendor", color="gray", variant="outline", size="lg"),
                ],
                justify="space-between",
            ),
            dmc.Group([status_badge(s) for s in counts for _ in range(counts[s])], gap="xs"),
            dmc.Divider(label="Invoices from this vendor", labelPosition="left", mt="sm"),
            _detail_table(
                ["Invoice", "Status", "Amount", "Confidence"],
                [[r["record_id"], r["status"], r["amount"], f"{r['confidence']:.2f}"]
                 for r in invoices],
            ),
        ],
        gap="sm",
    )


def audit_table(entries: list[dict]) -> dmc.Stack:
    """Who / what / when — the append-only history, newest first."""
    if not entries:
        return dmc.Stack([
            dmc.Text("No review activity yet.", c="dimmed", size="sm"),
            dmc.Text("Decisions made in the triage queue appear here with "
                     "reviewer, action and timestamp.", c="dimmed", size="xs"),
        ], gap=4)
    return dmc.Stack([
        dmc.Text(f"{len(entries)} entries (append-only; clearing a decision is "
                 "itself an audited action)", size="xs", c="dimmed"),
        _detail_table(
            ["When (UTC)", "Record", "Action", "Reviewer", "Note"],
            [[e["at"], e["record_id"], e["action"].replace("_", " "),
              e["reviewer"], e["note"]] for e in entries],
        ),
    ], gap="sm")


def build_layout() -> dmc.MantineProvider:
    summary, records = get_data()
    needs_attention = (summary["status_counts"]["Needs Review"]
                       + summary["status_counts"]["Suspicious"])
    statuses = list(STATUS_COLORS)

    return dmc.MantineProvider(
        dmc.Container(
            [
                # Selection state; defaults to the riskiest record (None on
                # an empty dataset — the detail panel shows a placeholder).
                dcc.Store(id="selected",
                          data=records[0]["record_id"] if records else None),
                # Timestamp of the graph tab becoming visible (drives re-layout).
                dcc.Store(id="graph-visible"),
                # Bumped after every manual decision; re-renders queue/detail/audit.
                dcc.Store(id="decisions-version", data=0),

                dmc.Group(
                    [
                        dmc.Title("Reconciliation Portal", order=2),
                        dmc.Group(
                            [
                                dmc.Text("reconciliation recomputed from source files on start",
                                         size="xs", c="dimmed"),
                                # Who: no auth in scope — the reviewer signs their
                                # decisions by name (persisted in the browser).
                                dmc.TextInput(id="reviewer", placeholder="Reviewer name",
                                              w=180, size="xs",
                                              persistence=True, persistence_type="local"),
                            ],
                            gap="md",
                        ),
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

                dmc.Tabs(
                    [
                        dmc.TabsList([
                            dmc.TabsTab("Triage queue", value="queue"),
                            dmc.TabsTab("Network graph", value="graph"),
                            dmc.TabsTab("Audit log", value="audit"),
                        ]),
                        dmc.TabsPanel(_queue_tab(statuses), value="queue", pt="md"),
                        dmc.TabsPanel(_graph_tab(), value="graph", pt="md"),
                        dmc.TabsPanel(
                            dmc.Card(id="audit-log", withBorder=True, radius="md",
                                     padding="lg", mb="xl"),
                            value="audit", pt="md",
                        ),
                    ],
                    id="main-tabs", value="queue",
                    # Both panels stay mounted so the shared selection Store
                    # can drive the detail panel in either tab.
                    keepMounted=True, mt="md",
                ),
            ],
            size="xl",
        ),
        forceColorScheme="light",
    )
