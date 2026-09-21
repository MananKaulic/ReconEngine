"""
report.py
---------
Stage 10 (implicit): ties every prior stage together into one pure
`run_reconciliation(...)` entry point that returns a RunResult, and
provides the break-blotter DataFrame + Excel export used by the app and
scripts/evaluate.py.

This is the ONLY module that calls every other engine module in sequence;
everything here remains pure (DataFrames/dataclasses in, DataFrames/
dataclasses out) so it can be unit-tested without Streamlit.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Optional

import pandas as pd

from .classify import classify_matched_break, compare_pair, suggest_action


def _issue(value) -> Optional[str]:
    """Normalises a 'setup_issue' cell to a real string or None. Needed
    because pandas represents a missing string as float('nan'), which is
    truthy in plain Python -- `nan or x` would wrongly evaluate to nan."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
from .config import Config
from .kpis import compute_kpis
from .matching import match_positions
from .models import AuditEntry, BreakRecord, RunResult, ValidationIssue, ValidationSeverity
from .prioritise import compute_value_impact, escalation_flags, materiality_and_sla, net_exposure_escalation
from .security_master import SecurityMaster, clean_master_df, load_security_master
from .standardise import standardise_custodian, standardise_internal
from .validation import has_blocking_errors, validate_inputs


def _clean_internal_id(internal_id: Optional[str]) -> Optional[str]:
    """Unresolvable custodian codes are carried through matching as a
    '__UNMAPPED__<code>' placeholder so they stay distinct (see
    standardise.py). For display in the break blotter we blank that back
    out to None -- the custodian_security_code on the break already shows
    which code could not be mapped."""
    if internal_id and str(internal_id).startswith("__UNMAPPED__"):
        return None
    return internal_id


def _sm_row_for(sm: SecurityMaster, internal_id: Optional[str]):
    if internal_id is None:
        return None
    return sm.get_row(internal_id)


def _build_break(
    business_date: date, account: str, internal_id: Optional[str],
    cust: Optional[dict], intl: Optional[dict], sm_row,
    reason_code: str, reason_detail: str, config: Config,
    audit_trail: list, evidence_used: list,
) -> BreakRecord:
    custodian_value = (cust or {}).get("market_value")
    internal_value = (intl or {}).get("market_value")
    abs_impact, signed_impact = compute_value_impact(custodian_value, internal_value)
    tier_name, sla_due = materiality_and_sla(abs_impact, business_date, config)
    escalated, esc_reason = escalation_flags(abs_impact, 0.0, config)

    action = suggest_action(reason_code, {
        "trade_ids": [], "expected_settlement_date": None,
    })

    return BreakRecord(
        business_date=business_date,
        account=account,
        internal_security_id=internal_id or "",
        custodian_security_code=(cust or {}).get("custodian_security_code") or (sm_row.custodian_security_code if sm_row else None),
        security_name=sm_row.security_name if sm_row else None,
        asset_class=sm_row.asset_class.value if (sm_row and sm_row.asset_class) else None,
        custodian_qty=(cust or {}).get("quantity"),
        internal_qty=(intl or {}).get("quantity"),
        custodian_value=custodian_value,
        internal_value=internal_value,
        custodian_ccy=(cust or {}).get("currency"),
        internal_ccy=(intl or {}).get("currency"),
        reason_code=reason_code,
        reason_detail=reason_detail,
        suggested_action=action,
        abs_value_impact=abs_impact,
        signed_value_impact=signed_impact,
        materiality_tier=tier_name,
        sla_due_date=sla_due,
        escalated=escalated,
        escalation_reason=esc_reason,
        audit_trail=audit_trail,
        evidence_used=evidence_used,
    )


def run_reconciliation(
    custodian_df: pd.DataFrame,
    internal_df: pd.DataFrame,
    master_df: pd.DataFrame,
    run_date: date,
    config: Config,
    expected_position_count: Optional[int] = None,
    custodian_control_total: Optional[float] = None,
    internal_control_total: Optional[float] = None,
    pending_trades_df: Optional[pd.DataFrame] = None,
    corporate_actions_df: Optional[pd.DataFrame] = None,
    stop_on_error: bool = False,
) -> RunResult:
    """The single entry point that runs the whole pipeline end to end.
    Pure function: takes DataFrames + config in, returns a RunResult.
    Never touches Streamlit, the filesystem, or the network."""

    master_df = clean_master_df(master_df)

    validation_issues: list[ValidationIssue] = validate_inputs(
        custodian_df, internal_df, master_df, run_date,
        expected_position_count=expected_position_count,
        expected_count_deviation_pct=config.validation.get("expected_position_count_deviation_pct", 5),
        custodian_control_total=custodian_control_total,
        internal_control_total=internal_control_total,
        pending_trades_df=pending_trades_df,
        corporate_actions_df=corporate_actions_df,
    )

    if stop_on_error and has_blocking_errors(validation_issues):
        return RunResult(
            business_date=run_date, validation_issues=validation_issues,
            matched_count=0, breaks=[], kpis={}, unmapped_custodian_codes=[], unmapped_internal_ids=[],
        )

    sm = SecurityMaster(master_df)
    cust_std = standardise_custodian(custodian_df, sm, run_date)
    intl_std = standardise_internal(internal_df, sm, run_date)

    match_result = match_positions(cust_std, intl_std, run_date)

    breaks: list[BreakRecord] = []
    unmapped_custodian_codes: list[str] = []
    unmapped_internal_ids: list[str] = []

    # --- Matched pairs: COMPARE, then classify anything that fails ------
    for cust, intl in match_result.matched:
        internal_id = intl.get("internal_security_id")
        account = intl.get("account")
        key = f"{run_date}/{account}/{internal_id}"

        setup_issue = _issue(cust.get("setup_issue")) or _issue(intl.get("setup_issue"))
        if setup_issue:
            sm_row = _sm_row_for(sm, internal_id)
            if cust.get("custodian_security_code") and sm.map_custodian_code(cust["custodian_security_code"]) is None and not sm.is_ambiguous_code(cust["custodian_security_code"]):
                unmapped_custodian_codes.append(cust["custodian_security_code"])
            audit = [AuditEntry(
                key=key, rule="SETUP.mapping_or_lifecycle_issue", evidence="security_master.csv lookup",
                values_compared={"issue": setup_issue}, outcome="SETUP",
            )]
            breaks.append(_build_break(run_date, account, _clean_internal_id(internal_id), cust, intl, sm_row, "SETUP", setup_issue, config, audit, []))
            continue

        sm_row = _sm_row_for(sm, internal_id)
        comparison = compare_pair(cust, intl, sm_row, config)
        if comparison["is_match"]:
            continue

        reason_code, reason_detail, audit, evidence = classify_matched_break(
            cust, intl, comparison, sm, config, run_date, pending_trades_df, corporate_actions_df,
        )
        breaks.append(_build_break(run_date, account, internal_id, cust, intl, sm_row, reason_code, reason_detail, config, audit, evidence))

    # --- Duplicates -------------------------------------------------------
    for dup in match_result.duplicates:
        run_dt, account, internal_id = dup["key"]
        key = f"{run_dt}/{account}/{internal_id}"
        rows = dup["rows"]
        sm_row = _sm_row_for(sm, internal_id)
        representative = rows[0]
        audit = [AuditEntry(
            key=key, rule="DUPLICATE.multiple_rows_same_key",
            evidence=f"{dup['side']} file has {dup['row_count']} rows for this (date, account, security) key",
            values_compared={"side": dup["side"], "row_count": dup["row_count"]}, outcome="DUPLICATE",
        )]
        cust = representative if dup["side"] == "custodian" else None
        intl = representative if dup["side"] == "internal" else None
        detail = f"{dup['row_count']} rows found on the {dup['side']} side for the same (date, account, security) key; cannot safely match."
        breaks.append(_build_break(run_dt, account, _clean_internal_id(internal_id), cust, intl, sm_row, "DUPLICATE", detail, config, audit, []))

    # --- Custodian-only (MISSING_INTERNAL, unless SETUP takes precedence) -
    for cust in match_result.custodian_only:
        internal_id = cust.get("internal_security_id")
        account = cust.get("account")
        key = f"{run_date}/{account}/{internal_id}"
        setup_issue = _issue(cust.get("setup_issue"))
        sm_row = _sm_row_for(sm, internal_id)
        if setup_issue:
            if cust.get("custodian_security_code") and sm.map_custodian_code(cust["custodian_security_code"]) is None and not sm.is_ambiguous_code(cust["custodian_security_code"]):
                unmapped_custodian_codes.append(cust["custodian_security_code"])
            audit = [AuditEntry(
                key=key, rule="SETUP.mapping_or_lifecycle_issue", evidence="security_master.csv lookup",
                values_compared={"issue": setup_issue}, outcome="SETUP",
            )]
            breaks.append(_build_break(run_date, account, _clean_internal_id(internal_id), cust, None, sm_row, "SETUP", setup_issue, config, audit, []))
            continue
        audit = [AuditEntry(
            key=key, rule="MISSING_INTERNAL.no_internal_record",
            evidence="internal_positions.csv has no row for this (date, account, security) key",
            values_compared={}, outcome="MISSING_INTERNAL",
        )]
        breaks.append(_build_break(run_date, account, internal_id, cust, None, sm_row, "MISSING_INTERNAL",
                                    "Position exists at the custodian but not in the internal book.", config, audit, []))

    # --- Internal-only (MISSING_CUSTODIAN) -------------------------------
    for intl in match_result.internal_only:
        internal_id = intl.get("internal_security_id")
        account = intl.get("account")
        key = f"{run_date}/{account}/{internal_id}"
        setup_issue = _issue(intl.get("setup_issue"))
        sm_row = _sm_row_for(sm, internal_id)
        if setup_issue:
            if internal_id not in sm._by_internal_id.index:
                unmapped_internal_ids.append(internal_id)
            audit = [AuditEntry(
                key=key, rule="SETUP.mapping_or_lifecycle_issue", evidence="security_master.csv lookup",
                values_compared={"issue": setup_issue}, outcome="SETUP",
            )]
            breaks.append(_build_break(run_date, account, internal_id, None, intl, sm_row, "SETUP", setup_issue, config, audit, []))
            continue
        audit = [AuditEntry(
            key=key, rule="MISSING_CUSTODIAN.no_custodian_record",
            evidence="custodian_positions.csv has no row for this (date, account, security) key",
            values_compared={}, outcome="MISSING_CUSTODIAN",
        )]
        breaks.append(_build_break(run_date, account, internal_id, None, intl, sm_row, "MISSING_CUSTODIAN",
                                    "Position exists internally but not at the custodian.", config, audit, []))

    # matched_count = matched pairs that did NOT become a break. Breaks that
    # originated from a matched pair (SETUP or a classified COMPARE failure)
    # always carry BOTH a custodian_qty and an internal_qty; breaks from
    # duplicates or one-sided (missing) records carry only one side.
    breaks_from_matched_pairs = sum(
        1 for b in breaks if b.custodian_qty is not None and b.internal_qty is not None
    )
    matched_count = len(match_result.matched) - breaks_from_matched_pairs

    net_total = sum(b.signed_value_impact for b in breaks)
    portfolio_escalated, portfolio_reason = net_exposure_escalation(net_total, config)
    if portfolio_escalated:
        for b in breaks:
            if not b.escalated:
                b.escalated = True
                b.escalation_reason = (b.escalation_reason + " | " if b.escalation_reason else "") + f"Portfolio-level: {portfolio_reason}"

    kpis = compute_kpis(matched_count, breaks, run_date, config)

    return RunResult(
        business_date=run_date,
        validation_issues=validation_issues,
        matched_count=matched_count,
        breaks=breaks,
        kpis=kpis,
        unmapped_custodian_codes=sorted(set(unmapped_custodian_codes)),
        unmapped_internal_ids=sorted(set(unmapped_internal_ids)),
    )


def breaks_to_dataframe(breaks: list) -> pd.DataFrame:
    rows = []
    for b in breaks:
        rows.append({
            "business_date": b.business_date,
            "account": b.account,
            "internal_security_id": b.internal_security_id,
            "custodian_security_code": b.custodian_security_code,
            "security_name": b.security_name,
            "asset_class": b.asset_class,
            "custodian_qty": b.custodian_qty,
            "internal_qty": b.internal_qty,
            "custodian_value": b.custodian_value,
            "internal_value": b.internal_value,
            "custodian_ccy": b.custodian_ccy,
            "internal_ccy": b.internal_ccy,
            "reason_code": b.reason_code,
            "reason_detail": b.reason_detail,
            "suggested_action": b.suggested_action,
            "abs_value_impact": b.abs_value_impact,
            "signed_value_impact": b.signed_value_impact,
            "materiality_tier": b.materiality_tier,
            "sla_due_date": b.sla_due_date,
            "escalated": b.escalated,
            "escalation_reason": b.escalation_reason,
        })
    return pd.DataFrame(rows)


def validation_issues_to_dataframe(issues: list) -> pd.DataFrame:
    rows = [{
        "stage": i.stage, "severity": i.severity, "code": i.code,
        "message": i.message, "context": str(i.context),
    } for i in issues]
    return pd.DataFrame(rows)


def build_excel_report(run_result: RunResult) -> bytes:
    """Builds an in-memory .xlsx with a break blotter, KPI summary and
    validation report sheet. Returns raw bytes (caller writes to disk or
    offers as a Streamlit download)."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        breaks_to_dataframe(run_result.breaks).to_excel(writer, sheet_name="Break Blotter", index=False)
        kpi_rows = []
        for k, v in run_result.kpis.items():
            if isinstance(v, dict):
                for kk, vv in v.items():
                    kpi_rows.append({"metric": f"{k}.{kk}", "value": vv})
            else:
                kpi_rows.append({"metric": k, "value": v})
        pd.DataFrame(kpi_rows).to_excel(writer, sheet_name="KPIs", index=False)
        validation_issues_to_dataframe(run_result.validation_issues).to_excel(writer, sheet_name="Validation", index=False)
    buf.seek(0)
    return buf.read()
