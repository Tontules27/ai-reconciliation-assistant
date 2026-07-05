"""Shared visual vocabulary: status colors and severity order.

Status palette from the validated reference instance (dataviz skill):
CVD-separated; the two low-contrast steps (warning/serious) are mitigated by
the icon+label rule — a status is never conveyed by color alone. The same
mapping will color the graph edges in the network view, so the whole app
speaks one color language.
"""

STATUS_COLORS = {
    "Matched": "#0ca30c",        # good
    "Partial Match": "#fab219",  # warning
    "Needs Review": "#ec835a",   # serious
    "Suspicious": "#d03b3b",     # critical
    "Unmatched": "#898781",      # neutral — no signal either way
}

# Mantine theme-color names for badges (text stays in ink tokens).
BADGE_COLORS = {
    "Matched": "green",
    "Partial Match": "yellow",
    "Needs Review": "orange",
    "Suspicious": "red",
    "Unmatched": "gray",
}

# Triage order: the operator sees the riskiest work first.
SEVERITY_ORDER = ["Suspicious", "Needs Review", "Partial Match", "Unmatched", "Matched"]

# Chart chrome (light surface) — recessive grid, muted axis ink.
CHART = {
    "surface": "#fcfcfb",
    "grid": "#e1e0d9",
    "muted": "#898781",
    "ink": "#0b0b0b",
}
