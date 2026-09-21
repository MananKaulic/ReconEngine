"""
End-to-end test: runs the seeded generator into a temp directory, runs the
full reconciliation pipeline on the output, and asserts recall against the
planted answer key meets a stated threshold.

THRESHOLD STATED HERE (and in README/docs): with evidence files supplied,
this prototype targets 100% recall on its own planted scenarios (16/16),
because every scenario was deliberately constructed to trigger exactly one
documented rule. We assert >= 90% as the CI gate to leave a small margin
for future changes to the generator's random seed, while still catching
any real regression in the rule chain.
"""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from recon_engine import Config, run_reconciliation
from recon_engine.security_master import load_security_master

RECALL_THRESHOLD = 0.90


@pytest.fixture(scope="module")
def generated_data(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("e2e_data")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_data.py"), "--seed", "42", "--out-dir", str(out_dir)],
        check=True, cwd=ROOT,
    )
    return out_dir


def test_generator_produces_all_files(generated_data):
    for fname in ["custodian_positions.csv", "internal_positions.csv", "security_master.csv",
                  "pending_trades.csv", "corporate_actions.csv", "answer_key.csv"]:
        assert (generated_data / fname).exists()


def test_end_to_end_recall_meets_threshold(generated_data):
    cust = pd.read_csv(generated_data / "custodian_positions.csv")
    intl = pd.read_csv(generated_data / "internal_positions.csv")
    master = load_security_master(generated_data / "security_master.csv")
    pending = pd.read_csv(generated_data / "pending_trades.csv")
    pending["trade_date"] = pd.to_datetime(pending["trade_date"]).dt.date
    pending["expected_settlement_date"] = pd.to_datetime(pending["expected_settlement_date"]).dt.date
    corp = pd.read_csv(generated_data / "corporate_actions.csv")
    corp["ex_date"] = pd.to_datetime(corp["ex_date"]).dt.date
    answer_key = pd.read_csv(generated_data / "answer_key.csv")

    run_date = pd.to_datetime(cust["business_date"]).dt.date.mode()[0]
    config = Config.load(ROOT / "config" / "tolerances.yaml")

    result = run_reconciliation(
        cust, intl, master, run_date, config,
        pending_trades_df=pending, corporate_actions_df=corp,
    )

    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate import score_run

    scored = score_run(result.breaks, answer_key)
    detail = scored["detail"]
    recall = detail["caught"].sum() / len(detail)
    assert recall >= RECALL_THRESHOLD, (
        f"Recall {recall:.2%} on planted scenarios fell below the stated "
        f"threshold of {RECALL_THRESHOLD:.0%}:\n{detail[~detail['caught']]}"
    )
    assert len(scored["false_positive_breaks"]) == 0, "Unplanted breaks appeared on otherwise clean data"


def test_engine_does_not_crash_without_evidence_files(generated_data):
    cust = pd.read_csv(generated_data / "custodian_positions.csv")
    intl = pd.read_csv(generated_data / "internal_positions.csv")
    master = load_security_master(generated_data / "security_master.csv")
    run_date = pd.to_datetime(cust["business_date"]).dt.date.mode()[0]
    config = Config.load(ROOT / "config" / "tolerances.yaml")

    result = run_reconciliation(cust, intl, master, run_date, config)  # no evidence files
    assert result.kpis["break_count"] >= 0  # simply must not raise
