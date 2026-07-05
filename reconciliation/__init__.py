"""Pure reconciliation engine — no Dash/Flask imports anywhere in this package."""

from .engine import reconcile

__all__ = ["reconcile"]
