"""
models.py
---------
Shared dataclasses and enums used across every stage of the reconciliation
engine. Kept dependency-free (no pandas here) so it can be imported anywhere
without circularity.

This module has NO Streamlit, NO network calls, NO I/O. It is pure data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    EQUITY = "Equity"
    FIXED_INCOME = "FixedIncome"
    MONEY_MARKET = "MoneyMarket"
    DERIVATIVE = "Derivative"


class ReasonCode(str, Enum):
    """Root-cause classification for a break. Order here mirrors the
    documented evaluation order used by classify.py (SETUP checked first,
    UNEXPLAINED is the fallback of last resort)."""
    SETUP = "SETUP"
    TIMING = "TIMING"
    CORP = "CORP"
    PRICE = "PRICE"
    TRADE = "TRADE"
    DUPLICATE = "DUPLICATE"
    CCY_MISMATCH = "CCY_MISMATCH"
    MISSING_INTERNAL = "MISSING_INTERNAL"   # exists at custodian only
    MISSING_CUSTODIAN = "MISSING_CUSTODIAN"  # exists internally only
    UNEXPLAINED = "UNEXPLAINED"


class MaterialityTier(str, Enum):
    SAME_DAY = "SAME_DAY"
    NEXT_DAY = "NEXT_DAY"
    ROUTINE = "ROUTINE"


class ValidationSeverity(str, Enum):
    ERROR = "ERROR"      # stops the run (per config)
    WARNING = "WARNING"  # run continues, flagged in the validation report


@dataclass
class ValidationIssue:
    stage: str
    severity: ValidationSeverity
    code: str
    message: str
    context: dict = field(default_factory=dict)


@dataclass
class AuditEntry:
    """One line of the audit trail: which rule fired, on what evidence,
    comparing which values. Every classification decision produces at
    least one of these -- nothing is decided silently."""
    key: str                 # (business_date, account, internal_security_id)
    rule: str                # e.g. "SETUP.unmapped_custodian_code"
    evidence: str            # human-readable description of evidence used
    values_compared: dict = field(default_factory=dict)
    outcome: str = ""        # e.g. "SETUP" or "no match -> next rule"


@dataclass
class SecurityMasterRow:
    internal_security_id: str
    custodian_security_code: str
    isin: str
    ticker: str
    security_name: str
    asset_class: AssetClass
    currency: str
    unit_multiplier: float
    status: str              # ACTIVE / INACTIVE
    effective_from: date


@dataclass
class BreakRecord:
    """One row of the break blotter -- the central output of the engine."""
    business_date: date
    account: str
    internal_security_id: str
    custodian_security_code: Optional[str]
    security_name: Optional[str]
    asset_class: Optional[str]

    custodian_qty: Optional[float]
    internal_qty: Optional[float]
    custodian_value: Optional[float]
    internal_value: Optional[float]
    custodian_ccy: Optional[str]
    internal_ccy: Optional[str]

    reason_code: str
    reason_detail: str
    suggested_action: str

    abs_value_impact: float
    signed_value_impact: float
    materiality_tier: str
    sla_due_date: date
    escalated: bool
    escalation_reason: Optional[str]

    audit_trail: list = field(default_factory=list)   # list[AuditEntry]
    evidence_used: list = field(default_factory=list)  # human-readable strings


@dataclass
class RunResult:
    """Everything a UI or test needs from one reconciliation run."""
    business_date: date
    validation_issues: list                 # list[ValidationIssue]
    matched_count: int
    breaks: list                            # list[BreakRecord]
    kpis: dict
    unmapped_custodian_codes: list
    unmapped_internal_ids: list
