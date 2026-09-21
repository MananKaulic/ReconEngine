"""
prioritise.py
-------------
Stage 7 of the pipeline: turns a classified break into a fully prioritised
BreakRecord by computing value impact, materiality tier, SLA due date
(skipping weekends and holidays) and escalation flags.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .config import Config, add_business_days


def compute_value_impact(custodian_value: Optional[float], internal_value: Optional[float]) -> tuple[float, float]:
    """Returns (abs_value_impact, signed_value_impact). signed = custodian - internal
    (positive means custodian shows MORE value than our books)."""
    c = custodian_value or 0.0
    i = internal_value or 0.0
    signed = c - i
    return abs(signed), signed


def materiality_and_sla(abs_value_impact: float, run_date: date, config: Config) -> tuple[str, date]:
    tier = config.tier_for_value(abs_value_impact)
    due = add_business_days(run_date, tier.sla_business_days, config.holiday_calendar)
    return tier.name, due


def escalation_flags(abs_value_impact: float, net_exposure_running_total: float, config: Config) -> tuple[bool, Optional[str]]:
    """Per-break escalation: a single break above the configured threshold.
    Net-exposure escalation (vs AUM) is a PORTFOLIO-level check, applied
    once across all breaks -- see kpis.py / report.py, not here."""
    threshold = config.escalation["single_break_value_inr"]
    if abs_value_impact > threshold:
        return True, f"Single break value {abs_value_impact:,.2f} exceeds escalation threshold {threshold:,.2f} -> senior ops"
    return False, None


def net_exposure_escalation(net_exposure_total: float, config: Config) -> tuple[bool, Optional[str]]:
    pct_of_aum = abs(net_exposure_total) / config.aum_inr * 100.0 if config.aum_inr else 0.0
    threshold_pct = config.escalation["net_exposure_pct_of_aum"]
    if pct_of_aum > threshold_pct:
        return True, (f"Net exposure difference {net_exposure_total:,.2f} is {pct_of_aum:.3f}% of AUM, "
                       f"exceeding the {threshold_pct}% threshold -> portfolio manager")
    return False, None
