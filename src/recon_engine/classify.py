"""
classify.py
-----------
Stages 4 ("COMPARE") and 6 ("ROOT-CAUSE CLASSIFIER") of the pipeline.

COMPARE: for every matched (custodian, internal) pair, checks the quantity,
value and price differences against the asset class's tolerance, and
checks for a currency mismatch. Within tolerance on qty+value and no
currency mismatch => MATCHED. Otherwise the pair becomes a break candidate.

CLASSIFY: assigns a root-cause reason code to every break candidate
(including unmatched / duplicate records) using a FIXED, DOCUMENTED rule
order. Every decision -- including "no rule matched" -- writes an
AuditEntry naming the rule, the evidence considered, and the values
compared. The engine never forces a label: if no rule's condition is
actually met, the break goes to UNEXPLAINED with an honest note about
which evidence file (if any) was missing.

Rule order (checked top to bottom, first match wins):
  1. SETUP        -- unmapped / inactive / not-yet-effective / ambiguous
  2. CCY_MISMATCH -- currency disagreement (checked at COMPARE time)
  3. TIMING       -- explained by an unsettled pending trade
  4. CORP         -- explained by a corporate action processed on one side
  5. PRICE        -- quantity agrees, value differs because of price
  6. TRADE        -- explained by a recent booking (trade) on one side
  7. UNEXPLAINED  -- no rule matched; honest fallback
(DUPLICATE is assigned directly from matching.py's duplicate bucket and
MISSING_INTERNAL / MISSING_CUSTODIAN from the unmatched buckets, both
ahead of this chain conceptually since they never reach COMPARE.)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd

from .config import Config
from .models import AuditEntry
from .security_master import SecurityMaster

TOL_EPS = 1e-9


def compare_pair(cust: dict, intl: dict, sm_row, config: Config) -> dict:
    """Returns a dict describing the comparison outcome for one matched
    pair. Always includes 'is_match' (bool) and the raw diffs, so callers
    (and tests) can inspect exactly why something did or didn't match."""
    asset_class = sm_row.asset_class.value if sm_row and sm_row.asset_class else None
    tol = config.tolerance_for(asset_class) if asset_class else config.tolerance_for("__unknown__")

    qty_diff = (cust.get("quantity") or 0) - (intl.get("quantity") or 0)
    value_diff = (cust.get("market_value") or 0) - (intl.get("market_value") or 0)

    intl_price = intl.get("price") or 0
    cust_price = cust.get("price") or 0
    price_diff_pct = (abs(cust_price - intl_price) / abs(intl_price) * 100.0) if intl_price else 0.0

    master_ccy = sm_row.currency if sm_row else None
    cust_ccy = (cust.get("currency") or "").upper()
    intl_ccy = (intl.get("currency") or "").upper()
    ccy_mismatch = (cust_ccy != intl_ccy) or (master_ccy is not None and (cust_ccy != master_ccy or intl_ccy != master_ccy))

    qty_within = abs(qty_diff) <= tol["quantity_abs"] + TOL_EPS
    value_within = abs(value_diff) <= tol["value_abs_inr"] + TOL_EPS

    is_match = qty_within and value_within and not ccy_mismatch

    return {
        "is_match": is_match,
        "qty_diff": qty_diff,
        "value_diff": value_diff,
        "price_diff_pct": price_diff_pct,
        "ccy_mismatch": ccy_mismatch,
        "qty_within_tolerance": qty_within,
        "value_within_tolerance": value_within,
        "tolerance_used": tol,
        "asset_class": asset_class,
    }


def _net_signed_pending_qty(pending_trades_df: Optional[pd.DataFrame], account: str, internal_id: str, run_date: date) -> tuple[float, list]:
    if pending_trades_df is None or len(pending_trades_df) == 0:
        return 0.0, []
    df = pending_trades_df
    mask = (
        (df["account"] == account)
        & (df["internal_security_id"] == internal_id)
        & (df["status"].str.lower() == "unsettled")
        & (df["expected_settlement_date"] > run_date)
    )
    rows = df[mask]
    if len(rows) == 0:
        return 0.0, []
    signed = rows.apply(lambda r: r["quantity"] if r["side"].upper() == "BUY" else -r["quantity"], axis=1)
    used = rows["trade_id"].tolist()
    return float(signed.sum()), used


def _corp_action_for(corp_actions_df: Optional[pd.DataFrame], internal_id: str, run_date: date):
    if corp_actions_df is None or len(corp_actions_df) == 0:
        return None
    df = corp_actions_df
    mask = (df["internal_security_id"] == internal_id) & (df["ex_date"] <= run_date)
    rows = df[mask]
    if len(rows) == 0:
        return None
    # Most recent ex_date first
    rows = rows.sort_values("ex_date", ascending=False)
    return rows.iloc[0].to_dict()


def _recent_trades(pending_trades_df: Optional[pd.DataFrame], account: str, internal_id: str, run_date: date, lookback_days: int) -> pd.DataFrame:
    if pending_trades_df is None or len(pending_trades_df) == 0:
        return pd.DataFrame()
    df = pending_trades_df
    window_start = run_date - timedelta(days=lookback_days)
    mask = (
        (df["account"] == account)
        & (df["internal_security_id"] == internal_id)
        & (df["trade_date"] >= window_start)
        & (df["trade_date"] <= run_date)
    )
    return df[mask]


def classify_matched_break(
    cust: dict, intl: dict, comparison: dict, sm: SecurityMaster, config: Config,
    run_date: date, pending_trades_df: Optional[pd.DataFrame], corp_actions_df: Optional[pd.DataFrame],
) -> tuple[str, str, list, list]:
    """Classifies a break that came from a matched pair failing COMPARE
    (SETUP is handled by the caller before this is invoked, since setup
    issues are known at standardise time). Returns
    (reason_code, reason_detail, audit_entries, evidence_used)."""
    account = intl.get("account") or cust.get("account")
    internal_id = intl.get("internal_security_id") or cust.get("internal_security_id")
    key = f"{run_date}/{account}/{internal_id}"
    audit: list[AuditEntry] = []
    evidence: list[str] = []
    qty_tol = comparison["tolerance_used"]["quantity_abs"]

    # --- CCY_MISMATCH -------------------------------------------------
    if comparison["ccy_mismatch"]:
        audit.append(AuditEntry(
            key=key, rule="CCY_MISMATCH.currency_disagreement",
            evidence="custodian currency vs internal currency vs security master currency",
            values_compared={"custodian_ccy": cust.get("currency"), "internal_ccy": intl.get("currency")},
            outcome="CCY_MISMATCH",
        ))
        return "CCY_MISMATCH", "Currency reported differs between books and/or the security master.", audit, evidence

    # --- TIMING ---------------------------------------------------------
    net_pending, trade_ids = _net_signed_pending_qty(pending_trades_df, account, internal_id, run_date)
    if trade_ids:
        # Internal books are assumed to book trades on trade date; custodian
        # reflects them only once settled, so custodian_qty - internal_qty
        # should equal the negative of the net signed pending quantity.
        explained = abs(comparison["qty_diff"] + net_pending) <= qty_tol + TOL_EPS
        audit.append(AuditEntry(
            key=key, rule="TIMING.unsettled_pending_trade",
            evidence=f"pending_trades.csv: unsettled trades {trade_ids} with settlement after {run_date}",
            values_compared={"qty_diff": comparison["qty_diff"], "net_pending_qty": net_pending},
            outcome="TIMING" if explained else "no match -> next rule",
        ))
        if explained:
            evidence.append(f"Unsettled pending trade(s) {trade_ids} explain the quantity gap.")
            return "TIMING", f"Quantity gap matches unsettled pending trade(s) {trade_ids}.", audit, evidence
    elif pending_trades_df is None:
        audit.append(AuditEntry(
            key=key, rule="TIMING.unsettled_pending_trade", evidence="pending_trades.csv not supplied",
            values_compared={}, outcome="skipped - evidence file not supplied",
        ))

    # --- CORP -------------------------------------------------------------
    corp = _corp_action_for(corp_actions_df, internal_id, run_date)
    if corp is not None:
        ratio = float(corp["ratio"])
        intl_qty = intl.get("quantity") or 0
        forward = abs(intl_qty * ratio - (cust.get("quantity") or 0)) <= qty_tol + TOL_EPS
        reverse = (ratio != 0) and abs(intl_qty / ratio - (cust.get("quantity") or 0)) <= qty_tol + TOL_EPS
        processed_diff = str(corp.get("processed_internally")).upper() != str(corp.get("processed_at_custodian")).upper()
        matched_ratio = forward or reverse
        audit.append(AuditEntry(
            key=key, rule="CORP.corporate_action_ratio",
            evidence=f"corporate_actions.csv: {corp.get('action_type')} ex_date={corp.get('ex_date')} ratio={ratio}",
            values_compared={"internal_qty": intl_qty, "custodian_qty": cust.get("quantity"), "ratio": ratio,
                              "processed_internally": corp.get("processed_internally"), "processed_at_custodian": corp.get("processed_at_custodian")},
            outcome="CORP" if (matched_ratio and processed_diff) else "no match -> next rule",
        ))
        if matched_ratio and processed_diff:
            evidence.append(f"{corp.get('action_type')} (ratio {ratio}) processed on only one side as of {run_date}.")
            return "CORP", (f"{corp.get('action_type')} with ratio {ratio} was processed on one side only "
                             f"(internal={corp.get('processed_internally')}, custodian={corp.get('processed_at_custodian')})."), audit, evidence
    elif corp_actions_df is None:
        audit.append(AuditEntry(
            key=key, rule="CORP.corporate_action_ratio", evidence="corporate_actions.csv not supplied",
            values_compared={}, outcome="skipped - evidence file not supplied",
        ))

    # --- PRICE --------------------------------------------------------
    if comparison["qty_within_tolerance"] and not comparison["value_within_tolerance"]:
        audit.append(AuditEntry(
            key=key, rule="PRICE.quantity_agrees_value_differs",
            evidence="quantity within tolerance; market_value differs beyond tolerance",
            values_compared={"price_diff_pct": comparison["price_diff_pct"], "custodian_price": cust.get("price"), "internal_price": intl.get("price")},
            outcome="PRICE",
        ))
        evidence.append(f"Prices differ by {comparison['price_diff_pct']:.2f}% between books.")
        return "PRICE", f"Quantities agree but prices differ by {comparison['price_diff_pct']:.2f}%; flagged for valuation review.", audit, evidence

    # --- TRADE (booking-error suggestion) ---------------------------------
    recent_days = config.validation.get("recent_days_for_booking_error", 3)
    recent = _recent_trades(pending_trades_df, account, internal_id, run_date, recent_days)
    if len(recent) > 0:
        signed = recent.apply(lambda r: r["quantity"] if r["side"].upper() == "BUY" else -r["quantity"], axis=1)
        candidates = list(signed) + [signed.sum()]
        gap = comparison["qty_diff"]
        found = None
        for c in candidates:
            if abs(gap - c) <= qty_tol + TOL_EPS or abs(gap + c) <= qty_tol + TOL_EPS:
                found = c
                break
        audit.append(AuditEntry(
            key=key, rule="TRADE.recent_booking_window",
            evidence=f"pending_trades.csv: {len(recent)} trade(s) in last {recent_days} day(s)",
            values_compared={"qty_diff": gap, "candidate_matches": candidates},
            outcome="TRADE" if found is not None else "no match -> next rule",
        ))
        if found is not None:
            trade_ids = recent["trade_id"].tolist()
            evidence.append(f"Quantity gap matches a recent trade booking ({trade_ids}) within the last {recent_days} day(s).")
            return "TRADE", f"Quantity gap equals a recent trade (or sum of trades) booked in the last {recent_days} day(s); likely a one-sided booking error.", audit, evidence
    elif pending_trades_df is None:
        audit.append(AuditEntry(
            key=key, rule="TRADE.recent_booking_window", evidence="pending_trades.csv not supplied",
            values_compared={}, outcome="skipped - evidence file not supplied",
        ))

    # --- UNEXPLAINED --------------------------------------------------
    missing_files = []
    if pending_trades_df is None:
        missing_files.append("pending_trades.csv")
    if corp_actions_df is None:
        missing_files.append("corporate_actions.csv")
    note = f" (note: {', '.join(missing_files)} not supplied)" if missing_files else ""
    audit.append(AuditEntry(
        key=key, rule="UNEXPLAINED.no_rule_matched",
        evidence="no SETUP/CCY/TIMING/CORP/PRICE/TRADE rule condition was met",
        values_compared={"qty_diff": comparison["qty_diff"], "value_diff": comparison["value_diff"]},
        outcome="UNEXPLAINED",
    ))
    return "UNEXPLAINED", f"No rule matched this break{note}.", audit, evidence


def suggest_action(reason_code: str, context: dict) -> str:
    """Stage 8: plain-English next action per reason code."""
    if reason_code == "SETUP":
        return "Add or correct the mapping in the security master, then re-run."
    if reason_code == "CCY_MISMATCH":
        return "Confirm the correct trading/settlement currency with the custodian and correct the book that is wrong."
    if reason_code == "TIMING":
        trades = context.get("trade_ids", [])
        due = context.get("expected_settlement_date", "the expected settlement date")
        return f"Confirm with custodian that trade(s) {trades} settle by {due}; no correction needed if they do."
    if reason_code == "CORP":
        return "Process the corporate action on the side that is missing it, then re-run."
    if reason_code == "PRICE":
        return "Send both prices to the valuation/pricing team for review; check for a stale or incorrect price source."
    if reason_code == "TRADE":
        return "Investigate the recent trade booking on both sides for a duplicate, missed, or incorrectly sided entry."
    if reason_code == "DUPLICATE":
        return "Identify and remove/correct the duplicate row for this account/security before re-running."
    if reason_code == "MISSING_INTERNAL":
        return "Confirm whether this position should exist internally; book it if valid, or ask the custodian to correct their file if not."
    if reason_code == "MISSING_CUSTODIAN":
        return "Confirm with the custodian why this position is not on their statement; check for an unsettled trade or a booking error."
    return "Escalate to a reconciliation analyst for manual review; no rule-based suggestion is available."
