"""
kpis.py
-------
Stage 9 of the pipeline: aggregates a list of BreakRecord (plus the matched
count and run date) into the KPI dictionary the app's Summary tab renders.

Pure function, no I/O.
"""
from __future__ import annotations

from datetime import date

from .config import Config


def compute_kpis(matched_count: int, breaks: list, run_date: date, config: Config) -> dict:
    total_positions = matched_count + len(breaks)
    break_count = len(breaks)
    break_rate = (break_count / total_positions * 100.0) if total_positions else 0.0

    by_reason: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for b in breaks:
        by_reason[b.reason_code] = by_reason.get(b.reason_code, 0) + 1
        by_tier[b.materiality_tier] = by_tier.get(b.materiality_tier, 0) + 1

    gross_exposure = sum(b.abs_value_impact for b in breaks)
    net_exposure = sum(b.signed_value_impact for b in breaks)
    net_exposure_pct_aum = (abs(net_exposure) / config.aum_inr * 100.0) if config.aum_inr else 0.0

    explainable_reasons = {"TIMING", "CORP", "PRICE", "TRADE", "SETUP", "DUPLICATE", "CCY_MISMATCH", "MISSING_INTERNAL", "MISSING_CUSTODIAN"}
    auto_explained = sum(1 for b in breaks if b.reason_code in explainable_reasons)
    unexplained = sum(1 for b in breaks if b.reason_code == "UNEXPLAINED")
    auto_explained_share = (auto_explained / break_count * 100.0) if break_count else 0.0

    due_same_day = sum(1 for b in breaks if b.sla_due_date == run_date)

    aging_buckets = {"0 (due today)": 0, "1": 0, "2-3": 0, "4+": 0, "overdue": 0}
    for b in breaks:
        days = (b.sla_due_date - run_date).days
        if days < 0:
            aging_buckets["overdue"] += 1
        elif days == 0:
            aging_buckets["0 (due today)"] += 1
        elif days == 1:
            aging_buckets["1"] += 1
        elif days <= 3:
            aging_buckets["2-3"] += 1
        else:
            aging_buckets["4+"] += 1

    escalated_count = sum(1 for b in breaks if b.escalated)

    return {
        "run_date": str(run_date),
        "total_positions_reconciled": total_positions,
        "matched_count": matched_count,
        "break_count": break_count,
        "break_rate_pct": round(break_rate, 2),
        "breaks_by_reason_code": by_reason,
        "breaks_by_materiality_tier": by_tier,
        "gross_exposure_diff_inr": round(gross_exposure, 2),
        "net_exposure_diff_inr": round(net_exposure, 2),
        "net_exposure_pct_of_aum": round(net_exposure_pct_aum, 4),
        "auto_explained_count": auto_explained,
        "unexplained_count": unexplained,
        "auto_explained_share_pct": round(auto_explained_share, 2),
        "items_due_same_day": due_same_day,
        "aging": aging_buckets,
        "escalated_count": escalated_count,
    }
