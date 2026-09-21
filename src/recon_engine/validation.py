"""
validation.py
-------------
Stage 1 of the pipeline: validate inputs BEFORE any matching happens.

Checks implemented:
  - required columns present on each file
  - business_date in the position files equals the run date
  - quantity / price are numeric
  - position count within tolerance of an optional expected count
  - optional control total of market value supplied by the user
  - security master quality checks (delegated to security_master.py)

Returns a list[ValidationIssue]. Callers decide (per config / caller choice)
whether an ERROR should stop the run; this module never raises on business
data problems, only on structurally missing columns (a programming error,
not a data-quality break) it cannot proceed without.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from .models import ValidationIssue, ValidationSeverity
from .security_master import quality_check_master

CUSTODIAN_REQUIRED_COLUMNS = [
    "business_date", "account", "custodian_security_code",
    "quantity", "price", "market_value", "currency",
]
INTERNAL_REQUIRED_COLUMNS = [
    "business_date", "account", "internal_security_id",
    "quantity", "price", "market_value", "currency",
]
PENDING_TRADES_COLUMNS = [
    "trade_id", "account", "internal_security_id", "side",
    "quantity", "trade_date", "expected_settlement_date", "status",
]
CORP_ACTIONS_COLUMNS = [
    "internal_security_id", "action_type", "ex_date", "ratio",
    "processed_internally", "processed_at_custodian",
]


def _check_required_columns(df: pd.DataFrame, required: list[str], file_label: str) -> list[ValidationIssue]:
    issues = []
    missing = [c for c in required if c not in df.columns]
    if missing:
        issues.append(ValidationIssue(
            stage="validation", severity=ValidationSeverity.ERROR,
            code="MISSING_COLUMNS",
            message=f"{file_label} is missing required column(s): {missing}",
            context={"file": file_label, "missing_columns": missing},
        ))
    return issues


def _check_business_date(df: pd.DataFrame, run_date: date, file_label: str) -> list[ValidationIssue]:
    issues = []
    if "business_date" not in df.columns:
        return issues
    parsed = pd.to_datetime(df["business_date"], errors="coerce").dt.date
    bad = df[parsed != run_date]
    if len(bad) > 0:
        distinct = sorted({str(x) for x in parsed[parsed != run_date].unique()})
        issues.append(ValidationIssue(
            stage="validation", severity=ValidationSeverity.WARNING,
            code="BUSINESS_DATE_MISMATCH",
            message=(f"{file_label}: {len(bad)} row(s) have business_date != run date "
                      f"{run_date} (found: {distinct}). These rows are excluded from the run."),
            context={"file": file_label, "row_count": len(bad), "found_dates": distinct},
        ))
    return issues


def _check_numeric(df: pd.DataFrame, columns: list[str], file_label: str) -> list[ValidationIssue]:
    issues = []
    for col in columns:
        if col not in df.columns:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        bad_rows = df[numeric.isna() & df[col].notna()]
        if len(bad_rows) > 0:
            issues.append(ValidationIssue(
                stage="validation", severity=ValidationSeverity.ERROR,
                code="NON_NUMERIC_VALUE",
                message=f"{file_label}: column '{col}' has {len(bad_rows)} non-numeric value(s)",
                context={"file": file_label, "column": col, "row_count": len(bad_rows)},
            ))
    return issues


def _check_position_count(df: pd.DataFrame, expected_count: Optional[int], deviation_pct: float, file_label: str) -> list[ValidationIssue]:
    issues = []
    if expected_count is None or expected_count <= 0:
        return issues
    actual = len(df)
    allowed = expected_count * deviation_pct / 100.0
    if abs(actual - expected_count) > allowed:
        issues.append(ValidationIssue(
            stage="validation", severity=ValidationSeverity.WARNING,
            code="POSITION_COUNT_DEVIATION",
            message=(f"{file_label}: row count {actual} deviates from expected {expected_count} "
                      f"by more than {deviation_pct}% (allowed +/-{allowed:.1f})"),
            context={"file": file_label, "actual": actual, "expected": expected_count},
        ))
    return issues


def _check_control_total(df: pd.DataFrame, expected_total: Optional[float], file_label: str, rel_tol: float = 0.001) -> list[ValidationIssue]:
    issues = []
    if expected_total is None:
        return issues
    actual_total = pd.to_numeric(df.get("market_value"), errors="coerce").sum()
    if expected_total != 0 and abs(actual_total - expected_total) / abs(expected_total) > rel_tol:
        issues.append(ValidationIssue(
            stage="validation", severity=ValidationSeverity.WARNING,
            code="CONTROL_TOTAL_MISMATCH",
            message=(f"{file_label}: sum(market_value)={actual_total:,.2f} does not match "
                      f"supplied control total {expected_total:,.2f}"),
            context={"file": file_label, "actual_total": actual_total, "expected_total": expected_total},
        ))
    return issues


def validate_inputs(
    custodian_df: pd.DataFrame,
    internal_df: pd.DataFrame,
    master_df: pd.DataFrame,
    run_date: date,
    expected_position_count: Optional[int] = None,
    expected_count_deviation_pct: float = 5.0,
    custodian_control_total: Optional[float] = None,
    internal_control_total: Optional[float] = None,
    pending_trades_df: Optional[pd.DataFrame] = None,
    corporate_actions_df: Optional[pd.DataFrame] = None,
) -> list[ValidationIssue]:
    """Runs every validation check and returns the combined issue list.
    Does not mutate any of the input frames."""
    issues: list[ValidationIssue] = []

    issues += _check_required_columns(custodian_df, CUSTODIAN_REQUIRED_COLUMNS, "custodian_positions.csv")
    issues += _check_required_columns(internal_df, INTERNAL_REQUIRED_COLUMNS, "internal_positions.csv")

    # If required columns are missing we still attempt best-effort checks on
    # what IS present, but numeric/date checks below guard with `in df.columns`.
    issues += _check_business_date(custodian_df, run_date, "custodian_positions.csv")
    issues += _check_business_date(internal_df, run_date, "internal_positions.csv")

    issues += _check_numeric(custodian_df, ["quantity", "price", "market_value"], "custodian_positions.csv")
    issues += _check_numeric(internal_df, ["quantity", "price", "market_value"], "internal_positions.csv")

    issues += _check_position_count(custodian_df, expected_position_count, expected_count_deviation_pct, "custodian_positions.csv")
    issues += _check_position_count(internal_df, expected_position_count, expected_count_deviation_pct, "internal_positions.csv")

    issues += _check_control_total(custodian_df, custodian_control_total, "custodian_positions.csv")
    issues += _check_control_total(internal_df, internal_control_total, "internal_positions.csv")

    issues += quality_check_master(master_df)

    if pending_trades_df is None:
        issues.append(ValidationIssue(
            stage="validation", severity=ValidationSeverity.WARNING,
            code="EVIDENCE_FILE_NOT_SUPPLIED",
            message="pending_trades.csv not supplied: TIMING breaks cannot be auto-explained and will show as UNEXPLAINED.",
            context={"file": "pending_trades.csv"},
        ))
    else:
        issues += _check_required_columns(pending_trades_df, PENDING_TRADES_COLUMNS, "pending_trades.csv")

    if corporate_actions_df is None:
        issues.append(ValidationIssue(
            stage="validation", severity=ValidationSeverity.WARNING,
            code="EVIDENCE_FILE_NOT_SUPPLIED",
            message="corporate_actions.csv not supplied: CORP breaks cannot be auto-explained and will show as UNEXPLAINED.",
            context={"file": "corporate_actions.csv"},
        ))
    else:
        issues += _check_required_columns(corporate_actions_df, CORP_ACTIONS_COLUMNS, "corporate_actions.csv")

    return issues


def has_blocking_errors(issues: list[ValidationIssue]) -> bool:
    return any(i.severity == ValidationSeverity.ERROR for i in issues)
