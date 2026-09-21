"""
standardise.py
--------------
Stage 2 of the pipeline: turn raw custodian/internal CSVs into clean,
comparable records keyed on internal_security_id.

Steps, in order:
  1. Uppercase and trim identifiers (account, security codes/ids, currency).
  2. Parse business_date.
  3. Recompute market_value = quantity * price where it is missing.
  4. Map custodian_security_code -> internal_security_id via the security
     master. Unmapped / inactive / not-yet-effective / ambiguous codes are
     tagged with a setup_issue but NEVER dropped -- they flow through to
     matching.py as unmatched records so they surface as SETUP breaks.
  5. Apply the security master's unit_multiplier to the CUSTODIAN side's
     quantity and market_value.

     ASSUMPTION (documented here and in the BRD): the custodian is assumed
     to report fixed income / derivative quantities in "market convention"
     units (e.g. bond face value, or lots) while our internal books already
     store the multiplier-adjusted economic quantity. We therefore
     normalise the CUSTODIAN side by dividing its reported quantity by the
     unit_multiplier where multiplier != 1, so both sides end up expressed
     in the same internal unit before comparison. This choice is arbitrary
     but must be picked and documented -- real onboarding would confirm
     each custodian's convention file by file.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .security_master import SecurityMaster


def _clean_common(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["account"] = df["account"].astype(str).str.strip().str.upper()
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    df["business_date"] = pd.to_datetime(df["business_date"], errors="coerce").dt.date
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["market_value"] = pd.to_numeric(df["market_value"], errors="coerce")
    missing_mv = df["market_value"].isna() & df["quantity"].notna() & df["price"].notna()
    df.loc[missing_mv, "market_value"] = df.loc[missing_mv, "quantity"] * df.loc[missing_mv, "price"]
    return df


def standardise_custodian(df: pd.DataFrame, sm: SecurityMaster, run_date: date) -> pd.DataFrame:
    df = _clean_common(df)
    df["custodian_security_code"] = df["custodian_security_code"].astype(str).str.strip().str.upper()

    def resolve(code: str) -> tuple[Optional[str], Optional[str], bool]:
        # NOTE: when a code cannot be resolved to a real internal_security_id
        # (unmapped or ambiguous), we still need a matching KEY that is
        # unique per distinct custodian_security_code -- using a bare `None`
        # for every unresolved row would make unrelated unmapped/ambiguous
        # codes on the same account collide into a false DUPLICATE instead
        # of each surfacing as its own SETUP break. A stable per-code
        # placeholder id keeps unresolved rows both distinct from each
        # other AND correctly grouped if the SAME bad code genuinely
        # repeats (which should still be flagged as DUPLICATE).
        if sm.is_ambiguous_code(code):
            return f"__UNMAPPED__{code}", f"custodian_security_code '{code}' maps ambiguously to multiple internal IDs", True
        internal_id = sm.map_custodian_code(code)
        if internal_id is None:
            return f"__UNMAPPED__{code}", f"custodian_security_code '{code}' not found in security master", True
        issue = sm.setup_issue(internal_id, run_date)
        return internal_id, issue, False

    resolved = df["custodian_security_code"].apply(resolve)
    df["internal_security_id"] = resolved.apply(lambda t: t[0])
    df["setup_issue"] = resolved.apply(lambda t: t[1])
    df["is_unmapped_placeholder"] = resolved.apply(lambda t: t[2])

    def multiplier_for(internal_id):
        if internal_id is None:
            return 1.0
        row = sm.get_row(internal_id)
        if row is None or row.unit_multiplier in (None, 0):
            return 1.0
        return row.unit_multiplier

    df["unit_multiplier"] = df["internal_security_id"].apply(multiplier_for)
    # Normalise custodian quantity/value into the same unit convention as
    # the internal book (see module docstring for the documented assumption).
    df["raw_quantity"] = df["quantity"]
    df["raw_market_value"] = df["market_value"]
    needs_norm = df["unit_multiplier"] != 1.0
    df.loc[needs_norm, "quantity"] = df.loc[needs_norm, "quantity"] / df.loc[needs_norm, "unit_multiplier"]
    # market_value is economic value already comparable 1:1; we do not rescale it,
    # only quantity, since price already reflects "per reported unit".
    return df


def standardise_internal(df: pd.DataFrame, sm: SecurityMaster, run_date: date) -> pd.DataFrame:
    df = _clean_common(df)
    df["internal_security_id"] = df["internal_security_id"].astype(str).str.strip().str.upper()

    def issue_for(internal_id: str) -> Optional[str]:
        return sm.setup_issue(internal_id, run_date)

    df["setup_issue"] = df["internal_security_id"].apply(issue_for)
    return df
