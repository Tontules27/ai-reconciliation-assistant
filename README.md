# AI Reconciliation Assistant

Invoice ↔ payment reconciliation built as a real entity-resolution pipeline —
**candidate generation → scoring → decisioning** — with deterministic,
auditable rules deciding everything financial, and AI strictly confined to
the presentation layer (explaining decisions, never making them).

## Quickstart

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1        # after this, plain `python` / `pytest` work
pip install -r requirements.txt

python cli.py                     # engine output as JSON
pytest                            # golden set + component tests (35)
python portal.py                  # portal at http://127.0.0.1:8050
```

No API key is required for anything above. Optional: copy `.env.example` to
`.env` and set `ANTHROPIC_API_KEY` and/or `GEMINI_API_KEY` to enable
LLM-phrased explanations (`python cli.py --llm`). Every failure mode — no
key, bad key, no credits, API down — falls back to deterministic templates.

> Running `pytest` outside the venv picks up a global interpreter without the
> project's dependencies and fails at collection — activate the venv first.

## What it does

Three input files (`data/invoices.csv`, `data/payments.csv`,
`data/notes.json`) go through the pipeline; every invoice comes out with a
status, matched payments, a transparent confidence score, an explanation,
remaining balance where applicable, and a suggested action. Orphan payments
are reported alongside.

| Stage | Module | What happens |
|---|---|---|
| Load | `reconciliation/loader.py` | CSV strings validated straight into `Decimal` — money never passes through a float |
| Notes → flags | `reconciliation/notes.py` | Deterministic keyword/regex extraction: partial payment, discount (+ amount), duplicate warning, name-typo confirmation, currency review |
| Candidate generation | `reconciliation/candidates.py` | Cheap filters first: invoice/PO cited in the reference, or same currency + amount band + minimally similar name. Most pairs die here |
| Scoring | `reconciliation/scoring.py` | Only survivors pay for the expensive work: `rapidfuzz` name similarity plus amount/currency/reference signals |
| Decisioning | `reconciliation/engine.py` | Severity-ordered rules assign the status; a `networkx` graph detects duplicates (2+ equal-amount payment edges) and orphans (isolated nodes) and **feeds the classification** |
| Explanation | `reconciliation/explain.py` | Deterministic templates by default; optional LLM rephrasing (see below) |

Statuses: `Matched`, `Partial Match`, `Needs Review`, `Unmatched`, `Suspicious`.

### Edge cases the rules handle (none are hardcoded)

| Case | Outcome | Why |
|---|---|---|
| Payer-name typo, exact id + amount (INV-1001) | Matched | Fuzzy similarity 96% clears the strong threshold |
| Compact reference `INV1002` | Matched | Reference tokens extracted by pattern, not exact string |
| Underpayment + partial-payment note (INV-1003) | Partial Match | Remaining balance `1300.00` computed in `Decimal` |
| PO + amount exact, payer "Unknown Vendor" (INV-1004) | Needs Review | The money adds up; the identity does not |
| 1490 vs 1500 + documented 10 USD discount (INV-1005) | Matched | Notes change outcomes: amount is note-adjusted before comparing |
| Two payments, same amount, same invoice (INV-1007) | Suspicious | Classic double-payment signature, corroborated by an ops note |
| Same amount, EUR vs USD (INV-1008) | Needs Review | Amounts in different currencies are never treated as equal |
| Payment with no reference and no plausible invoice (PAY-9010) | Unmatched orphan | Survives no candidate filter |

## Where the AI lives (and where it does not)

**Rules decide everything financial.** Same input → same output, byte for
byte (asserted by a test). The LLM's only job is *phrasing*: with `--llm`,
one API call (never one per pair) receives the already-decided facts and
rewords the explanations with schema-validated structured output. Providers
cascade — Anthropic first, then Gemini — and every returned row must pass a
fact-drift guard (known record id, correct status prefix, sane length) or it
keeps its deterministic template. Note parsing is deterministic
keyword/regex extraction, so the pipeline is identical with or without a key.

## Money

All amounts are `Decimal`, parsed directly from the CSV strings (never
through a float — `0.1 + 0.2 != 0.3` in binary floats and the drift breaks
comparisons and balances). Comparisons use an explicit tolerance, never `==`.
JSON output serializes `Decimal` as strings (`"1300.00"`) so consumers don't
degrade it either. Cents-as-integers was the equally valid alternative;
`Decimal` was chosen for readability and free pydantic validation.

## Evals

`tests/test_golden.py` is a golden set: the expected outcome of every dataset
row acts as labels, and `test_precision_recall` computes per-status
precision/recall against them. Every threshold and weight lives in
`reconciliation/config.py`, so tuning is a loop: change a value → `pytest` →
see exactly which status degraded. Guardrail tests keep the triage ordering
honest (every Matched must outrank every Needs Review/Suspicious in
confidence) and the engine free of UI imports. On this dataset the bar is
perfection; a production golden set would grow from reviewed operator
decisions and assert tuned minimums per status instead.

## Portal

`python portal.py` → http://127.0.0.1:8050

- **Triage queue** (the main view): invoices and orphans sorted by risk —
  severity first, lowest confidence first within a tier. The operator's
  workload, not a table dump.
- **Explainability as UI**: the detail panel shows the signal breakdown whose
  sum *is* the confidence score, linked payments, source notes, and the
  suggested action.
- **Network graph** (`dash-cytoscape`): vendors ◆, invoices ▢ (filled with
  their status color), payments ○; payment edges colored by status. The
  duplicate is visibly two red edges into one invoice; the orphan is an
  isolated dashed node. Every node is tappable — invoices show the decision,
  payments show their fields and where they landed, vendors show their
  portfolio.
- **Manual review + audit**: approve / reject / mark duplicate / resolved
  (+ optional note) from the detail panel, signed with the reviewer name.
  Stored in SQLite (`review.db`) — the *only* persistence in the system:
  `audit_log` is append-only (who/what/when; even clearing a decision is
  audited) and `review_decisions` holds the current decision per record.
  Reconciliation itself is recomputed from the source files on every start.

## REST API

Dash runs on Flask, so the engine is exposed as a plain route:

```
GET /reconciliation   →  the full engine JSON (same contract as cli.py)
```

## Project structure

```
reconciliation/   pure engine — never imports Dash/Flask (enforced by a test)
app/              Dash portal: data shaping, theme, figures, graph, layout,
                  callbacks, SQLite review store
tests/            golden set, component tests, store, API
cli.py            engine → JSON on stdout (--llm for LLM explanations)
portal.py         runs the portal
data/             the three source files
DECISIONS.md      every rule and threshold, one or two lines each
```

## Architecture at scale

This repo is the right size for its data. With millions of records it
becomes a different system — same seams, different implementations. The
skill is knowing *when* to jump, and the seams are already visible:

- **Candidate generation → blocking/indexing in Postgres.** The cheap
  filters (`candidates.py`) become indexed queries: extracted reference
  tokens, `(currency, amount_bucket)` composite indexes, trigram/phonetic
  indexes on normalized names. Relational truth stays in the database; you
  never score the cross product.
- **Matcher as a stateless service.** `reconcile()` is already a pure
  function of its inputs; at scale it becomes a horizontally scaled worker
  pulling candidate batches. No state means trivial retries and scaling.
- **Batch + streaming ingestion.** Nightly bank files (batch) and payment
  webhooks (streaming) feed the same pipeline.
- **Idempotency / dedup keys.** The same payment arrives twice via retries
  and file re-sends — critical in payments. A dedup key
  (source, external id, amount, date hash) makes re-processing a no-op at
  ingestion, distinct from the *business* duplicate detection that stays in
  the engine.
- **Human review as a queue.** The triage view becomes a work queue with
  assignment, SLAs and state transitions; decisions flow back as labels for
  the golden set (the eval loop closes itself).
- **Audit / outbox.** The append-only audit log pattern is already here;
  at scale it emits events through an outbox table so downstream systems
  (ERP, ledger) consume decisions reliably, exactly once.
- **Observability with business metrics.** auto-approve-rate,
  review-queue-depth, match-rate, time-to-resolution — dashboarded and
  alerted. A falling auto-match rate is an upstream drift detector (bank
  changed reference formats) long before anyone files a ticket.
- **Versioned rules with evals.** `config.py` becomes versioned rule sets;
  every change replays against the golden set before rollout, and results
  record which rule version produced them — the finance version of model
  governance.

## What I would improve next

- Split payments / many-to-many allocation (one payment across invoices).
- Currency conversion support with dated FX rates (today: never equated, by design).
- Vendor aliasing table learned from confirmed matches (feeds name matching).
- Reviewer auth instead of self-reported names.
- A `--format csv` export for the CLI.
