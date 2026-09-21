"""
security_master.py
-------------------
The security master is the Rosetta Stone of the engine: it is what lets us
translate a custodian's security code into our internal_security_id so that
both books can be keyed on the same identifier before matching.

Responsibilities implemented here (first-class, not an afterthought):
  1. Load + lightly standardise the master file.
  2. Quality-check the master itself (duplicates, ambiguous mappings,
     missing asset class / multiplier) -- these are reported at validation
     time, not discovered halfway through matching.
  3. Provide lookup helpers used by standardise.py:
       - custodian_security_code -> internal_security_id
       - internal_security_id -> SecurityMasterRow (asset class, multiplier,
         currency, status, effective_from)
  4. Flag SETUP conditions: unmapped code, inactive security, security not
     yet effective as of the business date, ambiguous mapping.

Pure functions + one loader; no Streamlit, no network.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd

from .models import AssetClass, SecurityMasterRow, ValidationIssue, ValidationSeverity

REQUIRED_COLUMNS = [
    "internal_security_id", "custodian_security_code", "isin", "ticker",
    "security_name", "asset_class", "currency", "unit_multiplier",
    "status", "effective_from",
]


def clean_master_df(df: pd.DataFrame) -> pd.DataFrame:
    """Standardises a raw security_master DataFrame (whatever its dtypes),
    idempotent: safe to call on an already-cleaned frame. This is what
    both load_security_master (reading from disk) and run_reconciliation
    (given an already-loaded DataFrame, e.g. from a Streamlit upload) use,
    so a caller never has to remember to pre-clean the master themselves."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"security_master.csv missing required column: {col}")

    df["internal_security_id"] = df["internal_security_id"].astype(str).str.strip().str.upper()
    df["custodian_security_code"] = df["custodian_security_code"].astype(str).str.strip().str.upper()
    df["isin"] = df["isin"].astype(str).str.strip().str.upper()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    df["status"] = df["status"].astype(str).str.strip().str.upper()
    df["unit_multiplier"] = pd.to_numeric(df["unit_multiplier"], errors="coerce")
    df["effective_from"] = pd.to_datetime(df["effective_from"], errors="coerce").dt.date
    return df


def load_security_master(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    return clean_master_df(df)


def quality_check_master(df: pd.DataFrame) -> list[ValidationIssue]:
    """Runs the "master quality checks" required by the spec:
    duplicate internal_security_id, one custodian code mapped to two
    internal IDs (ambiguous mapping), missing asset class, missing
    multiplier. Returns a list of ValidationIssue; ambiguous mappings and
    duplicate internal IDs are ERRORs (they make matching unsafe for the
    affected securities), the rest are WARNINGs."""
    issues: list[ValidationIssue] = []

    dup_internal = df[df["internal_security_id"].duplicated(keep=False)]
    for sec_id, grp in dup_internal.groupby("internal_security_id"):
        issues.append(ValidationIssue(
            stage="security_master", severity=ValidationSeverity.ERROR,
            code="DUPLICATE_INTERNAL_ID",
            message=f"internal_security_id '{sec_id}' appears {len(grp)} times in security_master.csv",
            context={"internal_security_id": sec_id, "row_count": len(grp)},
        ))

    ambiguous = df.groupby("custodian_security_code")["internal_security_id"].nunique()
    for code, n in ambiguous.items():
        if n > 1:
            mapped_ids = sorted(df.loc[df["custodian_security_code"] == code, "internal_security_id"].unique())
            issues.append(ValidationIssue(
                stage="security_master", severity=ValidationSeverity.ERROR,
                code="AMBIGUOUS_MAPPING",
                message=f"custodian_security_code '{code}' maps to {n} different internal IDs: {mapped_ids}",
                context={"custodian_security_code": code, "internal_ids": mapped_ids},
            ))

    valid_classes = {e.value for e in AssetClass}
    bad_class = df[~df["asset_class"].isin(valid_classes)]
    for _, row in bad_class.iterrows():
        issues.append(ValidationIssue(
            stage="security_master", severity=ValidationSeverity.WARNING,
            code="MISSING_OR_INVALID_ASSET_CLASS",
            message=f"'{row['internal_security_id']}' has asset_class '{row['asset_class']}' (expected one of {sorted(valid_classes)})",
            context={"internal_security_id": row["internal_security_id"]},
        ))

    bad_mult = df[df["unit_multiplier"].isna() | (df["unit_multiplier"] <= 0)]
    for _, row in bad_mult.iterrows():
        issues.append(ValidationIssue(
            stage="security_master", severity=ValidationSeverity.WARNING,
            code="MISSING_OR_INVALID_MULTIPLIER",
            message=f"'{row['internal_security_id']}' has invalid unit_multiplier '{row.get('unit_multiplier')}'",
            context={"internal_security_id": row["internal_security_id"]},
        ))

    return issues


class SecurityMaster:
    """Convenience wrapper providing the lookups standardise.py needs."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        # Ambiguous custodian codes map to a sentinel so lookups fail loudly.
        counts = df.groupby("custodian_security_code")["internal_security_id"].nunique()
        self._ambiguous_codes = set(counts[counts > 1].index)
        self._by_custodian_code = (
            df[~df["custodian_security_code"].isin(self._ambiguous_codes)]
            .set_index("custodian_security_code")["internal_security_id"]
            .to_dict()
        )
        # Keep first row per internal_security_id for lookups (duplicates are
        # already flagged as an ERROR by quality_check_master).
        self._by_internal_id = (
            df.drop_duplicates(subset=["internal_security_id"], keep="first")
            .set_index("internal_security_id")
        )

    def is_ambiguous_code(self, custodian_code: str) -> bool:
        return custodian_code in self._ambiguous_codes

    def map_custodian_code(self, custodian_code: str) -> Optional[str]:
        return self._by_custodian_code.get(custodian_code)

    def get_row(self, internal_security_id: str) -> Optional[SecurityMasterRow]:
        if internal_security_id not in self._by_internal_id.index:
            return None
        r = self._by_internal_id.loc[internal_security_id]
        try:
            asset_class = AssetClass(r["asset_class"])
        except ValueError:
            asset_class = None
        return SecurityMasterRow(
            internal_security_id=internal_security_id,
            custodian_security_code=r["custodian_security_code"],
            isin=r["isin"],
            ticker=r["ticker"],
            security_name=r["security_name"],
            asset_class=asset_class,
            currency=r["currency"],
            unit_multiplier=float(r["unit_multiplier"]) if pd.notna(r["unit_multiplier"]) else None,
            status=r["status"],
            effective_from=r["effective_from"],
        )

    def setup_issue(self, internal_security_id: str, business_date: date) -> Optional[str]:
        """Returns a human-readable SETUP reason if this security cannot be
        safely used for matching on business_date, else None."""
        row = self.get_row(internal_security_id)
        if row is None:
            return "internal_security_id not found in security master"
        if row.status != "ACTIVE":
            return f"security master status is '{row.status}' (not ACTIVE)"
        if row.effective_from is not None and business_date < row.effective_from:
            return f"security not yet effective (effective_from={row.effective_from}, business_date={business_date})"
        if row.asset_class is None:
            return "security master has missing/invalid asset_class"
        if row.unit_multiplier is None or row.unit_multiplier <= 0:
            return "security master has missing/invalid unit_multiplier"
        return None
