"""
config.py
---------
Loads config/tolerances.yaml into a typed, dict-like structure and provides
business-day arithmetic (used for SLA due dates and settlement-cycle logic).

Pure functions only. No I/O side effects beyond reading the one YAML file
the caller points at.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Tier:
    name: str
    min_value_inr: float
    sla_business_days: int


@dataclass
class Config:
    aum_inr: float
    asset_class_tolerances: dict
    price_tolerance_pct: float
    materiality_tiers: list  # list[Tier], sorted descending by min_value_inr
    escalation: dict
    settlement_cycle_business_days: dict
    validation: dict
    holiday_calendar: set  # set[date]
    raw: dict = field(default_factory=dict)

    @staticmethod
    def load(path: str | Path) -> "Config":
        with open(path, "r") as f:
            raw = yaml.safe_load(f)

        tiers = [
            Tier(t["name"], float(t["min_value_inr"]), int(t["sla_business_days"]))
            for t in raw["materiality_tiers"]
        ]
        tiers.sort(key=lambda t: t.min_value_inr, reverse=True)

        holidays = set()
        for d in raw.get("holiday_calendar") or []:
            holidays.add(date.fromisoformat(str(d)))

        return Config(
            aum_inr=float(raw["aum_inr"]),
            asset_class_tolerances=raw["asset_class_tolerances"],
            price_tolerance_pct=float(raw["price_tolerance_pct"]),
            materiality_tiers=tiers,
            escalation=raw["escalation"],
            settlement_cycle_business_days=raw["settlement_cycle_business_days"],
            validation=raw["validation"],
            holiday_calendar=holidays,
            raw=raw,
        )

    def tolerance_for(self, asset_class: str) -> dict:
        """Returns {'quantity_abs':..., 'value_abs_inr':...} for the class.
        Falls back to the widest configured tolerance if the class is
        unknown (should not happen if security master validation passed)."""
        if asset_class in self.asset_class_tolerances:
            return self.asset_class_tolerances[asset_class]
        widest = max(self.asset_class_tolerances.values(), key=lambda v: v["value_abs_inr"])
        return widest

    def tier_for_value(self, abs_value_impact: float) -> Tier:
        for tier in self.materiality_tiers:  # sorted descending
            if abs_value_impact >= tier.min_value_inr:
                return tier
        return self.materiality_tiers[-1]


def is_business_day(d: date, holidays: set) -> bool:
    return d.weekday() < 5 and d not in holidays  # Mon=0 .. Sun=6


def add_business_days(start: date, n: int, holidays: set) -> date:
    """Adds n business days to start, skipping weekends and holidays.
    n=0 returns the same day if it is a business day, else rolls forward
    is NOT applied (SLA due date of 'same day' means the run date itself)."""
    if n == 0:
        return start
    d = start
    remaining = n
    step = 1 if n > 0 else -1
    while remaining != 0:
        d = d + timedelta(days=step)
        if is_business_day(d, holidays):
            remaining -= step
    return d


def business_days_between(d1: date, d2: date, holidays: set) -> int:
    """Number of business days from d1 to d2 (positive if d2 is after d1)."""
    if d2 == d1:
        return 0
    step = 1 if d2 > d1 else -1
    count = 0
    d = d1
    while d != d2:
        d = d + timedelta(days=step)
        if is_business_day(d, holidays):
            count += step
    return count
