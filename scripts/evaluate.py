"""
scripts/evaluate.py
--------------------
Runs the reconciliation engine against the synthetic data in data/ and
scores it against data/answer_key.csv (the planted-break ground truth).

Reports, for BOTH "with evidence files" and "without evidence files" runs:
  - planted breaks caught (recall) vs missed
  - false positives (unplanted breaks the engine raised on "clean" data)
  - misclassified reason codes (planted break detected, wrong reason code)
  - per-reason-code precision and recall

This script prints REAL numbers computed from an actual run. It never
invents or rounds up a metric -- if something looks bad, it is reported as
bad, because that is more useful to a BA/interviewer than a flattering but
fake number.

Usage: python scripts/evaluate.py [--data-dir data] [--config config/tolerances.yaml]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recon_engine import Config, run_reconciliation
from recon_engine.security_master import load_security_master


def _load_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    return df


def load_inputs(data_dir: Path):
    cust = pd.read_csv(data_dir / "custodian_positions.csv")
    intl = pd.read_csv(data_dir / "internal_positions.csv")
    master = load_security_master(data_dir / "security_master.csv")
    pending = pd.read_csv(data_dir / "pending_trades.csv")
    pending = _load_dates(pending, ["trade_date", "expected_settlement_date"])
    corp = pd.read_csv(data_dir / "corporate_actions.csv")
    corp = _load_dates(corp, ["ex_date"])
    answer_key = pd.read_csv(data_dir / "answer_key.csv")
    run_date = pd.to_datetime(cust["business_date"]).dt.date.mode()[0]
    return cust, intl, master, pending, corp, answer_key, run_date


def _break_lookup(breaks) -> dict:
    """Maps a matching key to the break's reason_code. Two kinds of key are
    registered for every break so planted scenarios that reference either
    an internal_security_id or a custodian_security_code (unmapped cases
    have no internal id) can both be found."""
    lookup = {}
    for b in breaks:
        if b.internal_security_id:
            lookup[("id", b.account, b.internal_security_id)] = b
        if b.custodian_security_code:
            lookup[("code", b.account, b.custodian_security_code)] = b
    return lookup


# Maps an answer_key row to the lookup key(s) that should find its break.
SPECIAL_CODE_LOOKUPS = {
    "(unmapped)": "CUSTGHOST01",
    "SEC9002/SEC9003": "CUSTAMBIG1",
}


def score_run(breaks, answer_key: pd.DataFrame) -> dict:
    lookup = _break_lookup(breaks)
    all_break_keys_claimed = set()  # breaks matched to a planted scenario

    rows = []
    for _, ak in answer_key.iterrows():
        account = ak["account"]
        internal_id = ak["internal_security_id"]
        expected = ak["expected_reason_code"]

        found = None
        found_key = None
        if internal_id in SPECIAL_CODE_LOOKUPS:
            code = SPECIAL_CODE_LOOKUPS[internal_id]
            k = ("code", account, code)
            found = lookup.get(k)
            found_key = k
        else:
            k = ("id", account, internal_id)
            found = lookup.get(k)
            found_key = k

        if expected == "MATCHED":
            caught = found is None  # correctly matched = no break raised
            actual = "MATCHED" if caught else found.reason_code
        else:
            caught = found is not None and found.reason_code == expected
            actual = found.reason_code if found is not None else "NO_BREAK_RAISED"
            if found is not None:
                all_break_keys_claimed.add(found_key)

        rows.append({
            "account": account, "internal_security_id": internal_id,
            "scenario": ak["scenario"], "expected_reason_code": expected,
            "actual_reason_code": actual, "caught": caught,
        })

    detail = pd.DataFrame(rows)

    # False positives: breaks that exist but were never claimed by any
    # planted (non-MATCHED) scenario above.
    claimed_break_ids = set()
    for _, ak in answer_key.iterrows():
        if ak["expected_reason_code"] == "MATCHED":
            continue
        internal_id = ak["internal_security_id"]
        account = ak["account"]
        if internal_id in SPECIAL_CODE_LOOKUPS:
            k = ("code", account, SPECIAL_CODE_LOOKUPS[internal_id])
        else:
            k = ("id", account, internal_id)
        b = lookup.get(k)
        if b is not None:
            claimed_break_ids.add(id(b))

    false_positive_breaks = [b for b in breaks if id(b) not in claimed_break_ids]

    return {"detail": detail, "false_positive_breaks": false_positive_breaks}


def per_reason_precision_recall(detail: pd.DataFrame, false_positive_breaks, all_breaks) -> pd.DataFrame:
    reason_codes = sorted(set(detail["expected_reason_code"]) | {b.reason_code for b in all_breaks} - {"MATCHED"})
    rows = []
    for rc in reason_codes:
        planted = detail[detail["expected_reason_code"] == rc]
        n_planted = len(planted)
        n_recalled = int(planted["caught"].sum())
        recall = (n_recalled / n_planted) if n_planted else None

        n_predicted = sum(1 for b in all_breaks if b.reason_code == rc)
        n_predicted_correct = len(planted[planted["caught"]])
        precision = (n_predicted_correct / n_predicted) if n_predicted else None

        rows.append({
            "reason_code": rc, "planted_count": n_planted, "recalled_count": n_recalled,
            "recall": round(recall, 3) if recall is not None else None,
            "predicted_count": n_predicted, "precision": round(precision, 3) if precision is not None else None,
        })
    return pd.DataFrame(rows)


def run_and_score(cust, intl, master, run_date, config, answer_key, with_evidence: bool):
    pending_arg = pending_df if with_evidence else None
    corp_arg = corp_df if with_evidence else None
    result = run_reconciliation(
        cust, intl, master, run_date, config,
        pending_trades_df=pending_arg, corporate_actions_df=corp_arg,
    )
    scored = score_run(result.breaks, answer_key)
    pr = per_reason_precision_recall(scored["detail"], scored["false_positive_breaks"], result.breaks)
    return result, scored, pr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--config", type=str, default="config/tolerances.yaml")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    config = Config.load(args.config)

    global pending_df, corp_df
    cust, intl, master, pending_df, corp_df, answer_key, run_date = load_inputs(data_dir)

    print("=" * 78)
    print("RECONCILIATION ENGINE - EVALUATION AGAINST PLANTED ANSWER KEY")
    print(f"Run date: {run_date} | Planted scenarios: {len(answer_key)}")
    print("=" * 78)

    for label, with_evidence in [("WITH evidence files (pending_trades + corporate_actions)", True),
                                  ("WITHOUT evidence files", False)]:
        print(f"\n--- {label} ---")
        result, scored, pr = run_and_score(cust, intl, master, run_date, config, answer_key, with_evidence)
        detail = scored["detail"]
        n_caught = int(detail["caught"].sum())
        n_total = len(detail)
        print(f"Total positions reconciled: {result.kpis.get('total_positions_reconciled')}")
        print(f"Matched: {result.matched_count} | Breaks raised: {len(result.breaks)}")
        print(f"Planted scenarios caught correctly: {n_caught}/{n_total}")
        print(f"False positive breaks (unplanted, on 'clean' data): {len(scored['false_positive_breaks'])}")
        misclassified = detail[(~detail["caught"]) & (detail["expected_reason_code"] != "MATCHED") & (detail["actual_reason_code"] != "NO_BREAK_RAISED")]
        print(f"Misclassified (break raised, wrong reason code): {len(misclassified)}")
        if len(misclassified) > 0:
            print(misclassified[["scenario", "expected_reason_code", "actual_reason_code"]].to_string(index=False))
        missed = detail[(~detail["caught"]) & (detail["expected_reason_code"] != "MATCHED") & (detail["actual_reason_code"] == "NO_BREAK_RAISED")]
        if len(missed) > 0:
            print(f"Missed entirely (no break raised, expected one): {len(missed)}")
            print(missed[["scenario", "expected_reason_code"]].to_string(index=False))
        false_matched = detail[(detail["expected_reason_code"] == "MATCHED") & (~detail["caught"])]
        if len(false_matched) > 0:
            print(f"Planted MATCH cases that incorrectly broke: {len(false_matched)}")
            print(false_matched[["scenario", "actual_reason_code"]].to_string(index=False))
        print("\nPer-reason-code precision/recall:")
        print(pr.to_string(index=False))
        if len(scored["false_positive_breaks"]) > 0:
            print("\nFalse positive breaks:")
            for b in scored["false_positive_breaks"]:
                print(f"  {b.account} {b.internal_security_id} {b.reason_code}: {b.reason_detail}")

    print("\n" + "=" * 78)
    print("Done. These numbers are computed directly from this run; nothing above is estimated.")


if __name__ == "__main__":
    main()
