# AGENTS.md — Rules for AI Agents Working on This Codebase

This file exists so a future Claude Code / Codex / other AI agent session
picks up this project without breaking its core design guarantees. Read
this before making changes.

## Non-negotiable architecture rules

1. **The engine (`src/recon_engine/*.py`) must never import Streamlit,
   never make a network call, and never read a file path that wasn't
   passed in by the caller.** It takes DataFrames/dataclasses in and
   returns DataFrames/dataclasses out. `app.py` is the ONLY place UI
   framework code belongs.
2. **Every threshold lives in `config/tolerances.yaml`, never hard-coded.**
   If you find yourself writing a numeric literal for a tolerance,
   materiality band, escalation limit, or lookback window anywhere in
   `src/recon_engine/`, stop — it belongs in the config file and should be
   read through the `Config` object.
3. **The engine is deterministic.** Same input + same config = same
   output, every time. Do not introduce randomness, wall-clock reads
   (other than the `run_date` the caller supplies), or unordered
   dict/set iteration that could change output ordering.
4. **No break is ever silently dropped.** An unmapped identifier, a
   duplicate key, a validation failure — all of these must surface as a
   visible row (a break, or a validation issue), never a row that quietly
   disappears from the counts.
5. **The classifier never forces a label.** If you add a new rule, it
   must go into the documented, ordered chain in `classify.py`
   (`classify_matched_break`) and it must only fire when its condition is
   genuinely met. The UNEXPLAINED fallback and its "evidence file not
   supplied" note must remain reachable and honest.
6. **Every classification decision writes an `AuditEntry`** (rule name,
   evidence description, values compared, outcome) — this is not
   optional instrumentation, it's the audit trail the whole project is
   built around.
7. **Tests must stay green.** Run `pytest tests/ -q` before and after any
   change. If you change a rule's behaviour, update or add the
   corresponding test in the same commit — do not leave a stale test
   passing by accident.
8. **Rule-based only.** Do not add a machine-learning classifier, LLM
   call, or "smart" heuristic into `src/recon_engine/`. If asked to add
   ML-assisted suggestions, treat that as a new, clearly-labelled feature
   built alongside the existing rule-based path, not a replacement for it
   — and update the honesty language in `README.md`,
   `docs/INTERVIEW_PITCH.md` and the BRD accordingly, since "rule-based,
   no ML" is a stated, load-bearing claim in this project's docs.

## When you add a new reason code or rule

1. Add it to `ReasonCode` in `models.py`.
2. Implement it in `classify.py`, in the correct position in the
   documented rule order (update the module docstring's order list too).
3. Add a `suggest_action` entry.
4. Add a unit test in `tests/test_pipeline.py` that constructs a minimal
   fixture proving the rule fires ONLY when its condition holds (test both
   the positive case and at least one near-miss that should NOT fire it).
5. Consider adding a planted scenario to `scripts/generate_data.py` and a
   corresponding row to the answer key, then re-run `scripts/evaluate.py`
   and update the real numbers pasted into `README.md` — never hand-edit
   those numbers without re-running the script.
6. Update `docs/architecture.md` (Mermaid) and re-run
   `scripts/generate_diagrams.py` to refresh the decision-tree PNG.

## When you change a threshold or add a config option

1. Add it to `config/tolerances.yaml` with a comment marking it as an
   illustrative assumption (matching the style already there).
2. Read it through the `Config` dataclass in `config.py` — do not read the
   raw YAML dict directly from other modules.
3. If it affects the Streamlit tolerance editor, add the corresponding
   widget in `app.py`'s sidebar expander.

## Regenerating derivative artifacts

These are checked in but derived — regenerate rather than hand-edit:

- `data/*.csv` ← `python scripts/generate_data.py --seed 42 --out-dir data`
- `docs/diagrams/*.png` and `docs/architecture.md` ← `python scripts/generate_diagrams.py`
- The evaluation numbers in `README.md` ← `python scripts/evaluate.py`
  (copy the real printed output; never type in numbers by hand)

## Honesty requirements (do not weaken these)

- Never claim a threshold is an industry standard or benchmark — it isn't.
- Never invent or round up an evaluation metric; always compute it via
  `scripts/evaluate.py` and paste the real output.
- Keep the "no ML" claim accurate — check it every time you touch
  `classify.py`.
- Keep the scope boundary (positions only, two-book only, no fuzzy
  matching) explicit in the README/BRD/pitch docs; don't let scope creep
  into the code without updating the docs that promise it isn't there.
