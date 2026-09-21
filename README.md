# Position Reconciliation Engine (Prototype)

A working prototype of a **custodian-vs-internal-books position
reconciliation engine**, built as an interview project for a Business
Analyst role at Indus Valley Partners (IVP). Rule-based, deterministic,
fully auditable — and honest about what it doesn't do.

> **This is a prototype on entirely synthetic data.** Every threshold in
> `config/tolerances.yaml` is an illustrative assumption, not an industry
> benchmark. There is no machine learning anywhere in this codebase. Not
> affiliated with or endorsed by IVP.

## What it does

Given three CSV files — a custodian's position file, the firm's internal
position file, and a security master mapping between the two — plus two
optional evidence files (pending trades, corporate actions), the engine:

1. **Validates** every input (required columns, business date, numeric
   fields, position-count deviation, control totals, and security-master
   quality checks).
2. **Standardises** and maps custodian codes to internal IDs via the
   security master, applying unit multipliers (e.g. bond face value vs.
   units) so a units-convention difference never manufactures a false
   break.
3. **Matches** both books on (business date, account, internal security
   ID) — a key with more than one row on either side becomes a DUPLICATE
   break, never a silent (or arbitrary) pairing.
4. **Compares** matched pairs against per-asset-class tolerances and flags
   currency disagreements.
5. **Classifies** every break's root cause using six fixed, ordered rules
   (SETUP → CCY_MISMATCH → TIMING → CORP → PRICE → TRADE), falling back
   honestly to UNEXPLAINED when nothing fits — and writes a full audit
   trail (rule name, evidence, values compared) for every decision.
6. **Prioritises** by value impact into materiality tiers with SLA due
   dates (business-day aware, skipping weekends/holidays) and applies
   escalation rules.
7. **Suggests** a plain-English next action per reason code.
8. **Rolls up KPIs**: break rate, gross/net exposure, auto-explained share,
   aging.

All of this is exposed through a Streamlit app (`app.py`) with a Summary
dashboard, a filterable break blotter, a break-detail drill-down (with the
full audit trail), a file-validation report, a searchable security master,
and a "How it works" tab.

## Real evaluation numbers (not estimated)

A seeded synthetic-data generator (`scripts/generate_data.py`) produces
~290 positions across 5 accounts and ~65 securities, and plants 16 break
scenarios covering every reason code plus edge cases (a rounding
difference that must still match, a duplicate, a currency mismatch, an
unmapped code, an inactive security, an ambiguous mapping, a bond reported
in face value vs. units, a split processed on one side, a pending
settlement, a price-only difference, a missing position on each side, a
recent booking error, and two genuinely unexplained breaks). An answer key
(`data/answer_key.csv`) records the expected outcome for each.

`scripts/evaluate.py` runs the engine against this data **with and
without** the optional evidence files and scores it against the answer
key. Actual output from the last run (seed 42):

```
--- WITH evidence files (pending_trades + corporate_actions) ---
Total positions reconciled: 291
Matched: 277 | Breaks raised: 14
Planted scenarios caught correctly: 16/16
False positive breaks (unplanted, on 'clean' data): 0
Misclassified (break raised, wrong reason code): 0

Per-reason-code precision/recall: 1.00 / 1.00 on every reason code.

--- WITHOUT evidence files ---
Planted scenarios caught correctly: 12/16
Misclassified (break raised, wrong reason code): 4
  split_processed_one_side          CORP    -> UNEXPLAINED
  pending_settlement_explains_gap   TIMING  -> UNEXPLAINED
  timing_only_with_evidence         TIMING  -> UNEXPLAINED
  recent_booking_error              TRADE   -> UNEXPLAINED

UNEXPLAINED precision without evidence: 0.333 (recall 1.00)
```

This is exactly the intended, honest behaviour: **without the optional
evidence files, the engine correctly and transparently degrades** — it
does not guess, it relabels the 4 evidence-dependent breaks as UNEXPLAINED
with a note naming which file was missing, rather than mislabelling them
or crashing. That degradation is the evidence files' entire value
proposition, made visible and measured rather than asserted.

**Stated test threshold:** the automated end-to-end test
(`tests/test_end_to_end.py`) asserts recall ≥ 90% on planted scenarios with
evidence supplied; the actual achieved recall on this run is 100% (16/16).

## Project layout

```
config/tolerances.yaml        All thresholds, illustrative and editable
src/recon_engine/             Pure engine (no Streamlit, no network)
  models.py                   Dataclasses/enums shared across stages
  config.py                   Config loader + business-day maths
  validation.py                Stage 1: validate
  security_master.py          Security master loading, mapping, quality checks
  standardise.py               Stage 2: standardise
  matching.py                  Stage 3: match
  classify.py                  Stages 4 & 6: compare + root-cause classify
  prioritise.py                Stage 7: materiality/SLA/escalation
  kpis.py                       Stage 9: KPI aggregation
  report.py                     Orchestrates the full pipeline + reporting
app.py                        Thin Streamlit UI over recon_engine
scripts/
  generate_data.py             Seeded synthetic data + answer key
  evaluate.py                   Scores the engine against the answer key
  generate_diagrams.py          Renders the Graphviz PNGs + Mermaid doc
data/                          Sample data (generated)
tests/                         pytest suite (38 tests)
docs/
  BRD_Position_Reconciliation.docx
  UAT_TestCases.xlsx
  INTERVIEW_PITCH.md
  architecture.md               Mermaid sources for all 4 diagrams
  diagrams/*.png                Graphviz renders
```

## Running it

```bash
# Install (editable) — requires Python 3.10+
pip install -e . --break-system-packages   # or use a venv

# Regenerate the sample data (optional — data/ is already checked in)
python scripts/generate_data.py --seed 42 --out-dir data

# Run the full test suite
pytest tests/ -q

# Run the evaluation script (prints the numbers shown above)
python scripts/evaluate.py

# Render the diagrams (optional — already rendered under docs/diagrams/)
python scripts/generate_diagrams.py

# Launch the app
streamlit run app.py
```

## Assumptions worth knowing before an interview

- **AUM and every threshold** in `config/tolerances.yaml` are illustrative
  assumptions I invented for this prototype — not industry benchmarks, not
  a real client's SLAs.
- **Unit convention**: the custodian side is assumed to report fixed
  income/derivative quantities in market convention (e.g. bond face value)
  while the internal book already stores the multiplier-adjusted economic
  quantity; the custodian side is the one normalised. A real onboarding
  would confirm this per custodian.
- **Trade timing convention**: internal books are assumed to book a trade
  on trade date; the custodian is assumed to reflect it only once settled.
  This drives the sign convention in the TIMING rule.
- **Settlement cycle**: T+1 business days assumed for all asset classes in
  the sample data, configurable per class.
- All security master data (ISINs, tickers used as labels, codes) is
  synthetic; ISINs are format-valid but fake.

## What's explicitly out of scope (roadmap)

Cash reconciliation · trade-vs-trade (activity) reconciliation · NAV/P&L
reconciliation · intraday runs · N-way (multi-custodian) matching ·
derivatives margin · private-fund capital commitments · real custodian
file formats · multi-currency base-currency conversion · fuzzy identifier
matching · AI/ML-assisted resolution suggestions (unlike IVP's production
Reconciliation Solution, this prototype is rule-based only).

See `docs/BRD_Position_Reconciliation.docx` (Section 11–12) for the full
risk/limitation and roadmap discussion, and `docs/INTERVIEW_PITCH.md` for
a pitch, demo script and likely panel Q&A.

## Untested / not fully verified

- The Streamlit app was smoke-tested for startup and manually reasoned
  through tab-by-tab, but does not have automated UI tests (Streamlit apps
  are hard to unit test meaningfully; the engine underneath it is the part
  that's thoroughly tested).
- Excel/Word output was verified by rendering to PDF and visual
  inspection, and the xlsx was passed through a recalculation check with
  zero formula errors — but neither was opened in a licensed copy of MS
  Office.
- The generator's random seed (42) produces a fixed data set; a different
  seed has not been separately verified to hit the same 16/16 recall,
  though the underlying rules are seed-independent.
