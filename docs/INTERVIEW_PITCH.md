# Interview Pitch — Position Reconciliation Engine

## 30-second pitch

"I built a working prototype of a position reconciliation engine — the kind
of control that catches when a fund's internal books disagree with what the
custodian reports. It's rule-based, not ML: every threshold lives in one
config file, every classification decision writes an audit-trail entry
naming the rule and evidence it used, and I proved it against 16 planted
break scenarios covering every reason code — 16 out of 16 caught correctly
with zero false positives. It's scoped to positions only, on synthetic
data, and I can walk through exactly where it would and wouldn't hold up
in production."

## 2-minute structure

1. **The business problem (20s).** Position reconciliation is one of the
   most common controls at a fund — it's the first line of defence against
   NAV misstatement and undetected counterparty risk. Manual versions of
   this exist mostly as one analyst's judgement in a spreadsheet, which
   doesn't scale and doesn't satisfy an audit.
2. **What I built (40s).** A pipeline: validate the three input files
   (custodian positions, internal positions, security master) → standardise
   and map identifiers → match on date/account/security → compare against
   configurable tolerances → classify any break's root cause using six
   fixed rules, in order, falling back honestly to UNEXPLAINED when nothing
   fits → prioritise by value impact into materiality tiers and SLAs →
   suggest a plain-English next action → roll up into KPIs.
3. **How I proved it works (30s).** I wrote a seeded synthetic-data
   generator that plants one scenario per reason code plus edge cases
   (rounding inside tolerance, a bond reported in face value vs. units, an
   ambiguous security-master mapping), saved an answer key, and wrote an
   evaluation script that scores the engine against it. Result: 16/16
   caught with the optional evidence files supplied, and a clean,
   explainable degradation to UNEXPLAINED for the 4 scenarios that need
   those files when they're withheld.
4. **What's honest about it (30s).** It's rule-based, not the AI/ML that
   IVP's actual product uses for suggestions — I made that trade-off
   deliberately so every decision stays fully explainable in this
   interview. It's two-book, positions-only. Every tolerance number is an
   assumption I made up and labelled as such, not an industry benchmark.

## 3-minute demo script

1. Open the Streamlit app, "Use sample data", click Run. Land on the
   **Summary** tab — call out total positions, break rate, gross vs. net
   exposure, and the by-reason-code chart.
2. Go to **Break blotter**, filter to `reason_code = SETUP`, sort by value
   impact. Point out that even an unmapped custodian code never
   disappears — it's a row in the blotter, not a silent drop.
3. Click into **Break detail** on one TIMING break. Show the side-by-side
   custodian vs. internal values, the pending-trade evidence cited, and the
   audit-trail entry naming the exact rule and values compared.
4. Open **File validation**, point out the security-master quality checks
   (ambiguous mapping, duplicate ID) surfaced there, separate from the
   position-level breaks.
5. Open **Security master**, search for a ticker, show the asset-class/
   multiplier/status fields that drive tolerance selection and SETUP
   detection.
6. Briefly show **How it works** — the plain-English rule order and the
   decision-tree diagram — as the "if a panelist asks how X is decided"
   answer.
7. Close by opening `config/tolerances.yaml` in a text editor, change the
   Equity value tolerance, re-run, and show a break flip to MATCHED (or
   vice versa) — proving nothing is hard-coded.

## Likely panel questions with short answers

**What is a security master and why does it matter here?**
It's the reference table that maps a custodian's security code to the
firm's own internal ID, and carries the asset class, currency, unit
multiplier and lifecycle status (active/inactive/effective date) needed to
compare two books correctly. Without it you can't even key both books on
the same identifier, let alone pick the right tolerance or unit
convention — which is why I treat mapping failures (unmapped, ambiguous,
inactive, not-yet-effective) as their own first-class SETUP break rather
than a mysterious quantity mismatch.

**How does matching work?**
Both books are keyed on (business date, account, internal_security_id)
after the security-master mapping step. A key with exactly one row on each
side is a match candidate; more than one row on either side becomes a
DUPLICATE break rather than an arbitrary pairing, and a key present on only
one side becomes MISSING_INTERNAL or MISSING_CUSTODIAN.

**What does a SETUP break mean?**
It means the reconciliation itself couldn't be trusted for that position
before any value comparison even happened — the custodian code doesn't map
to any internal ID, maps ambiguously to more than one, or maps to a
security that's inactive or not yet effective as of the run date. It's
deliberately checked first, ahead of every value-based rule, because a bad
mapping makes every other comparison meaningless.

**Why rules, not ML?**
Three reasons: explainability (I can name the exact rule and evidence for
every decision, which matters for audit and for this interview),
reproducibility (deterministic — same input, same output, no model
versioning or drift to manage), and data reality (a defensible ML
classifier needs a lot more labelled break history than a prototype has;
16 planted scenarios is nowhere near enough to train anything responsibly).
IVP's actual product layers AI/ML suggestions on top of rule-based
matching — I scoped that out to keep this project auditable end to end.

**How is TIMING distinguished from CORP?**
Both start from the same signal — a quantity gap that isn't fully
explained by the tolerance — but they check different evidence. TIMING
checks pending_trades.csv for an unsettled trade whose settlement date is
after the run date, and requires the net signed quantity of those trades to
exactly explain the gap. CORP checks corporate_actions.csv for an action
whose ratio explains the gap (quantity × ratio equal on one side) *and*
where the processed_internally/processed_at_custodian flags disagree. They
run in a fixed order (TIMING checked first) so a security with both an
unsettled trade and a stale corporate action doesn't get an ambiguous
label — whichever evidence actually explains the numeric gap wins.

**What happens to ambiguous items?**
An ambiguous security-master mapping (one custodian code, two internal
IDs) is flagged at file-validation time as an ERROR-severity issue, and any
position using that code still surfaces as its own SETUP break in the
blotter — it's never silently matched to either candidate ID, and it's
never dropped.

**How would this scale?**
The engine itself is pandas-based and comfortably handles thousands of
positions in memory; the real scaling questions are elsewhere — ingesting
real custodian file formats instead of a standardised CSV schema, running
N-way across multiple custodians instead of one, and moving from a
Streamlit prototype to a proper workflow/ticketing integration so breaks
get assigned, tracked and closed rather than just displayed.

**What would you improve next?**
In priority order: fuzzy identifier matching (ISIN/SEDOL/CUSIP/ticker
cross-referencing) so a small custodian-code typo doesn't need a manual
master fix; cash and trade-vs-trade reconciliation, which are the natural
next controls to layer on; and a real (versioned, governed) security master
instead of the flat file here.

## How this maps to IVP's Reconciliation Solution and Security & Reference Master

IVP's product reconciles positions, activity and cash "any to any" across
prime brokers, custodians and administrators, using rule-based plus fuzzy
matching, and goes beyond break detection into classification, materiality
prioritisation, resolution suggestions (AI/ML-assisted) and audit trail.
This prototype deliberately covers a narrow, honest slice of that: two-book
position reconciliation only, rule-based only (no fuzzy matching, no ML),
but it does implement the same *shape* of value — classify, prioritise by
materiality, suggest a next action, and keep a full audit trail — and it
treats a security master as a first-class input the way IVP's Security &
Reference Master product implies it should be, rather than an afterthought
lookup table.

## Honest limitations

- Synthetic data only; no result here is a claim about real-world break
  rates or timelines.
- Every threshold in `config/tolerances.yaml` is an illustrative assumption
  I invented, not an industry benchmark or a real client's SLA.
- Positions only — no cash, trade-vs-trade, NAV or P&L reconciliation.
- Exact identifier matching only — no fuzzy logic.
- Rule-based only — no machine learning anywhere in this prototype.
- The security master here has no lifecycle governance, no vendor feed,
  and no history beyond a single `effective_from` date.
- Two-book (custodian vs. internal) only — no N-way matching.
