# Decisions

Every rule, threshold and design choice, one or two lines each. File and
symbol references point at the implementation.

## Money

- **String → `Decimal`, never through float** (`loader.py`, `notes.py`):
  binary floats can't represent most decimals; drift breaks `payment ==
  invoice` and running balances. Cents-as-integers was equally valid.
- **Tolerance, never `==`** (`config.amount_tolerance = 0.01`): money
  equality is always "within a cent", stated explicitly.
- **`Decimal` serializes to JSON strings** (`"1300.00"`): consumers must not
  degrade exact amounts to floats on parse.

## Candidate generation (`candidates.py`)

- **Reference citation is the primary filter**: invoice/PO numbers extracted
  from free text (`INV-1001`, `INV1002`, `invoice 1001`). Cheap, exact,
  kills most of the cross product — the seam that becomes DB blocking at scale.
- **Tokens keep their namespace**: an invoice citation resolves only against
  invoice numbers, a PO citation only against PO numbers — a PO whose digits
  collide with another invoice's id must not bind to that invoice.
- **Currency is deliberately NOT checked on cited pairs**: a currency
  mismatch must reach the decision rules to be flagged, not silently drop.
- **Uncited pairs need all three**: same currency + amount band (40%–102% of
  invoice) + name similarity ≥ weak threshold. A stray payment ("Random
  Supplier", 600 USD) generates no candidates at all.
- **Reference tokens need 3+ digits**: keeps figures like "10 USD" from
  parsing as invoice ids.

## Name matching (`normalize.py`)

- **Legal suffixes stripped from the end only** (`SA`, `LLC`, `Inc`…):
  "Grupo Norte SA" ≡ "Grupo Norte", but mid-name words are never removed.
- **`token_sort_ratio` on normalized names**: word-order independent, so
  abbreviations ("Delta Technology Services" ~ "Delta Tech Services") score high.
- **Two thresholds** (`config.py`: strong 80, weak 55): ≥ strong = same
  entity (typos, abbreviations); < weak = identity mismatch → Needs Review.
  Tunable against the golden set like every other number here.

## Notes → flags (`notes.py`)

- **Deterministic extraction only**: keyword/regex, no LLM — the pipeline
  must be identical with or without an API key.
- **Explicit ids win over vendor names**: a note citing INV-1001 attaches
  only there; fuzzy vendor matching is a fallback for id-less notes, so a
  note about "ACME Logistics" can't leak onto "ACME Logistics LLC".
- **Discount amounts must be currency-anchored AND adjacent to "discount"**
  ("10 USD … discount" / "discount of 10 USD"): bare numbers are never money,
  and a paid amount stated elsewhere in the note is never read as the discount.
- **Discount amounts require an explicit invoice/PO citation**: an id-less
  vendor-level note attaches to every invoice of that vendor, and applying
  its amount everywhere could silently write off money genuinely outstanding.
  The flag survives for display; the amount does not.
- **Flags adjust amounts and corroborate; they never set a status.**
  A note cannot waive an identity mismatch.

## Decision rules (`engine.py`, most severe first)

- **Severity-ordered cascade**: the worst applicable diagnosis wins. INV-1007
  is technically overpaid, but the duplicate rule fires first.
- **Duplicate → Suspicious**: 2+ payments of the same amount into one
  invoice (graph degree ≥ 2 with equal amounts) — unless together they settle
  the invoice exactly, in which case they are legitimate equal installments
  (a 50/50 split). Distinct amounts are always installments, not duplicates.
- **Currency mismatch → Needs Review**: amounts in different currencies are
  never equated, even when numerically identical — including in the signal
  breakdown: cross-currency pairs earn no exact-amount confidence at all.
- **Identity mismatch → Needs Review**: reference and amount agree but the
  payer doesn't resemble the vendor — money adds up, identity doesn't.
- **Exact or note-adjusted amount → Matched**: sum of linked payments equals
  the invoice within tolerance, optionally after documented discounts.
- **Underpayment → Partial Match** with `remaining_balance` net of documented
  discounts — positive by construction (never a negative balance); a
  partial-payment note raises confidence but isn't required.
- **Overpayment without duplicate signature → Needs Review** — including the
  case where a documented discount exceeds the shortfall (paid + discount
  above the invoice is money in above the effective amount due).
- **No candidates → Unmatched** (invoice awaiting payment / orphan payment).
- **Conservative bias throughout**: when in doubt, a human looks at it. A
  wrong auto-match in finance costs more than a manual review.

## Assignment & graph

- **Each payment goes to its single best-ranked invoice** (deterministic
  tie-break). Split payments are out of scope, noted in the roadmap.
- **The graph is logic, not decoration** (`build_graph`): duplicate suspects
  = invoice nodes with 2+ equal-amount payment edges; orphans = degree-0
  payment nodes. The same structure renders in the portal's network view.

## Confidence (`engine.py` + weights in `config.py`)

- **Confidence = clamped sum of the visible signal contributions** — the
  list shown in the UI *is* the formula, auditable line by line.
- **Anomalies subtract** (duplicate −0.35, identity −0.30, currency −0.25):
  risky cases sink in the triage queue.
- **Confidence never decides status**: rules classify; the score only orders
  the queue. A high score can't auto-approve an anomalous case.
- **All weights/thresholds are parameters** tuned against the golden set,
  not magic numbers in code.

## Explanations (`explain.py`)

- **Templates are the default**: deterministic, offline, reproducible.
- **LLM is opt-in, one call for all rows, presentation-layer only**:
  schema-validated structured output; provider cascade (Anthropic → Gemini);
  per-row fact-drift guard (id exists, status prefix intact, sane length);
  any failure anywhere falls back to templates. The LLM can, at most, write
  better prose — never change a fact.

## Persistence & audit (`app/store.py`)

- **SQLite stores only human decisions**: reconciliation is recomputed from
  the source files every run; derived state is never persisted.
- **The database path is anchored to the project root** (not the launch
  directory): every working directory shares one audit trail.
- **`audit_log` is append-only** — the source of truth for who/what/when;
  even clearing a decision is an audited action. `review_decisions` is just
  the current-state projection.

## Portal (`app/`)

- **Triage queue sorted by risk**: severity first, lowest confidence first
  within a tier — the least-supported case is the most urgent.
- **Explainability as UI**: the detail panel shows the signal breakdown,
  payments and notes — the "why" is the trust mechanism.
- **Status always ships as text** (badges, axis labels), never color alone;
  status palette is CVD-checked.
- **UI imports the engine, never the reverse** — enforced by a test that
  imports `reconciliation` in a clean subprocess and asserts no Dash/Flask.
- **Callback validation stays on app-wide**: dynamically created review
  controls are declared in a `validation_layout` superset instead of
  suppressing Dash's load-time id validation everywhere.
