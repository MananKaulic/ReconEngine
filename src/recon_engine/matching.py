"""
matching.py
-----------
Stage 3 of the pipeline: match custodian and internal records on the key
(business_date, account, internal_security_id). Each record may match at
most once. Multiple rows sharing a key on one side raise a DUPLICATE break
for that side rather than being silently matched or dropped.

Rows whose internal_security_id could not be resolved (custodian side) are
never dropped either -- they carry internal_security_id = None and flow
through as custodian-only records so classify.py can raise SETUP for them.

Output is a MatchResult with four buckets:
  - matched: list of (custodian_row, internal_row) dict pairs, same key,
             exactly one row on each side.
  - duplicates: list of dicts describing (key, side, row_count) for keys
                with >1 row on a side. These keys are EXCLUDED from
                'matched' and from the unmatched buckets -- they get their
                own DUPLICATE break instead so nothing is double counted.
  - custodian_only: rows whose key has no internal counterpart (and is not
                    a duplicate key).
  - internal_only: rows whose key has no custodian counterpart (and is not
                    a duplicate key).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


def _key(row: pd.Series) -> tuple:
    return (row["business_date"], row["account"], row["internal_security_id"])


@dataclass
class MatchResult:
    matched: list = field(default_factory=list)          # list[tuple[dict, dict]]
    duplicates: list = field(default_factory=list)       # list[dict]
    custodian_only: list = field(default_factory=list)   # list[dict]
    internal_only: list = field(default_factory=list)    # list[dict]


def match_positions(custodian_df: pd.DataFrame, internal_df: pd.DataFrame, run_date) -> MatchResult:
    # Only consider rows for the run date; other dates were already flagged
    # by validation and are excluded here to avoid cross-date false matches.
    cust = custodian_df[custodian_df["business_date"] == run_date].copy()
    intl = internal_df[internal_df["business_date"] == run_date].copy()

    cust_groups: dict[tuple, list[dict]] = {}
    for _, row in cust.iterrows():
        cust_groups.setdefault(_key(row), []).append(row.to_dict())

    intl_groups: dict[tuple, list[dict]] = {}
    for _, row in intl.iterrows():
        intl_groups.setdefault(_key(row), []).append(row.to_dict())

    result = MatchResult()
    all_keys = set(cust_groups) | set(intl_groups)

    for key in all_keys:
        c_rows = cust_groups.get(key, [])
        i_rows = intl_groups.get(key, [])

        if len(c_rows) > 1:
            result.duplicates.append({"key": key, "side": "custodian", "row_count": len(c_rows), "rows": c_rows})
            continue
        if len(i_rows) > 1:
            result.duplicates.append({"key": key, "side": "internal", "row_count": len(i_rows), "rows": i_rows})
            continue

        if c_rows and i_rows:
            result.matched.append((c_rows[0], i_rows[0]))
        elif c_rows and not i_rows:
            result.custodian_only.append(c_rows[0])
        elif i_rows and not c_rows:
            result.internal_only.append(i_rows[0])

    return result
