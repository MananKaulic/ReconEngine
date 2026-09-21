"""
app.py
------
Thin Streamlit UI for the position reconciliation engine prototype.

ARCHITECTURE RULE: this file contains NO reconciliation logic. Every
threshold, comparison, classification and prioritisation decision happens
inside recon_engine/*.py (pure, testable, Streamlit-free). This file only
collects inputs, calls recon_engine.run_reconciliation, and renders the
result.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from recon_engine import Config, build_excel_report, breaks_to_dataframe, run_reconciliation, validation_issues_to_dataframe
from recon_engine.security_master import clean_master_df

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "tolerances.yaml"
SAMPLE_DATA_DIR = ROOT / "data"

st.set_page_config(page_title="Position Reconciliation Engine (Prototype)", layout="wide")


# ---------------------------------------------------------------------------
# Sidebar: data source, tolerances editor, run button
# ---------------------------------------------------------------------------
def load_default_config() -> dict:
    with open(DEFAULT_CONFIG_PATH) as f:
        return yaml.safe_load(f)


if "raw_config" not in st.session_state:
    st.session_state.raw_config = load_default_config()

st.sidebar.title("⚙️ Setup")
st.sidebar.caption("PROTOTYPE on synthetic data — not for production use.")

data_source = st.sidebar.radio("Data source", ["Use sample data", "Upload my own files"])

uploaded = {}
if data_source == "Upload my own files":
    st.sidebar.markdown("**Required**")
    uploaded["custodian"] = st.sidebar.file_uploader("custodian_positions.csv", type="csv")
    uploaded["internal"] = st.sidebar.file_uploader("internal_positions.csv", type="csv")
    uploaded["master"] = st.sidebar.file_uploader("security_master.csv", type="csv")
    st.sidebar.markdown("**Optional evidence** (improves auto-explained rate)")
    uploaded["pending"] = st.sidebar.file_uploader("pending_trades.csv (optional)", type="csv")
    uploaded["corp"] = st.sidebar.file_uploader("corporate_actions.csv (optional)", type="csv")

with st.sidebar.expander("Edit tolerances / thresholds", expanded=False):
    st.caption("All values are illustrative assumptions for this prototype, not industry standards.")
    rc = st.session_state.raw_config
    rc["aum_inr"] = st.number_input("AUM (INR)", value=float(rc["aum_inr"]), step=1_00_00_000.0, format="%.0f")
    for ac, tol in rc["asset_class_tolerances"].items():
        st.markdown(f"**{ac}**")
        tol["quantity_abs"] = st.number_input(f"{ac} qty tolerance", value=float(tol["quantity_abs"]), key=f"qty_{ac}")
        tol["value_abs_inr"] = st.number_input(f"{ac} value tolerance (INR)", value=float(tol["value_abs_inr"]), key=f"val_{ac}")
    rc["price_tolerance_pct"] = st.number_input("Price tolerance (%)", value=float(rc["price_tolerance_pct"]))
    rc["escalation"]["single_break_value_inr"] = st.number_input("Single-break escalation threshold (INR)", value=float(rc["escalation"]["single_break_value_inr"]))
    rc["escalation"]["net_exposure_pct_of_aum"] = st.number_input("Net exposure escalation (% of AUM)", value=float(rc["escalation"]["net_exposure_pct_of_aum"]))
    if st.button("Reset to defaults"):
        st.session_state.raw_config = load_default_config()
        st.rerun()

run_date_input = st.sidebar.date_input("Business date", value=date(2026, 9, 18))
run_clicked = st.sidebar.button("▶ Run reconciliation", type="primary")


def _write_temp_config(raw: dict) -> Path:
    tmp = ROOT / ".tmp_tolerances.yaml"
    with open(tmp, "w") as f:
        yaml.safe_dump(raw, f)
    return tmp


def load_csv(file_or_path) -> pd.DataFrame:
    return pd.read_csv(file_or_path)


def load_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    return df


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------
st.title("📊 Position Reconciliation Engine — Prototype")
st.caption(
    "Custodian vs internal books, positions only. Rule-based classification (no ML). "
    "All data here is synthetic. Built as a BA interview project, modelled loosely on "
    "IVP's Reconciliation Solution and Security & Reference Master."
)

if "result" not in st.session_state:
    st.session_state.result = None
    st.session_state.master_df = None

if run_clicked:
    try:
        if data_source == "Use sample data":
            cust = load_csv(SAMPLE_DATA_DIR / "custodian_positions.csv")
            intl = load_csv(SAMPLE_DATA_DIR / "internal_positions.csv")
            master = load_csv(SAMPLE_DATA_DIR / "security_master.csv")
            pending = load_dates(load_csv(SAMPLE_DATA_DIR / "pending_trades.csv"), ["trade_date", "expected_settlement_date"])
            corp = load_dates(load_csv(SAMPLE_DATA_DIR / "corporate_actions.csv"), ["ex_date"])
        else:
            if not (uploaded.get("custodian") and uploaded.get("internal") and uploaded.get("master")):
                st.error("Please upload custodian_positions.csv, internal_positions.csv and security_master.csv (all three are required).")
                st.stop()
            cust = load_csv(uploaded["custodian"])
            intl = load_csv(uploaded["internal"])
            master = load_csv(uploaded["master"])
            pending = load_dates(load_csv(uploaded["pending"]), ["trade_date", "expected_settlement_date"]) if uploaded.get("pending") else None
            corp = load_dates(load_csv(uploaded["corp"]), ["ex_date"]) if uploaded.get("corp") else None

        tmp_cfg_path = _write_temp_config(st.session_state.raw_config)
        config = Config.load(tmp_cfg_path)

        result = run_reconciliation(
            cust, intl, master, run_date_input, config,
            pending_trades_df=pending, corporate_actions_df=corp,
        )
        st.session_state.result = result
        st.session_state.master_df = clean_master_df(master)
        st.success(f"Run complete: {result.kpis.get('total_positions_reconciled', 0)} positions reconciled.")
    except Exception as e:
        st.error(f"Could not complete the run: {e}")
        st.stop()

result = st.session_state.result

tabs = st.tabs(["Summary", "Break blotter", "Break detail", "File validation", "Security master", "How it works"])

# --- Summary tab ------------------------------------------------------------
with tabs[0]:
    if result is None:
        st.info("Choose a data source and click **Run reconciliation** in the sidebar to begin.")
    else:
        k = result.kpis
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total positions", k.get("total_positions_reconciled", 0))
        c2.metric("Matched", k.get("matched_count", 0))
        c3.metric("Breaks", k.get("break_count", 0))
        c4.metric("Break rate", f"{k.get('break_rate_pct', 0)}%")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Gross exposure diff (₹)", f"{k.get('gross_exposure_diff_inr', 0):,.0f}")
        c6.metric("Net exposure diff (₹)", f"{k.get('net_exposure_diff_inr', 0):,.0f}")
        c7.metric("Net exposure (% AUM)", f"{k.get('net_exposure_pct_of_aum', 0)}%")
        c8.metric("Auto-explained", f"{k.get('auto_explained_share_pct', 0)}%")

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Breaks by reason code")
            by_reason = k.get("breaks_by_reason_code", {})
            if by_reason:
                st.bar_chart(pd.Series(by_reason, name="count"))
            else:
                st.caption("No breaks.")
        with col_b:
            st.subheader("Breaks by materiality tier")
            by_tier = k.get("breaks_by_materiality_tier", {})
            if by_tier:
                st.bar_chart(pd.Series(by_tier, name="count"))
            else:
                st.caption("No breaks.")

        st.subheader("Aging")
        st.bar_chart(pd.Series(k.get("aging", {}), name="count"))

        st.metric("Escalated breaks", k.get("escalated_count", 0))
        st.metric("Items due same day", k.get("items_due_same_day", 0))

# --- Break blotter tab -------------------------------------------------------
with tabs[1]:
    if result is None or len(result.breaks) == 0:
        st.info("No breaks to show yet. Run a reconciliation first.")
    else:
        df = breaks_to_dataframe(result.breaks)
        colf1, colf2, colf3, colf4 = st.columns(4)
        reason_filter = colf1.multiselect("Reason code", sorted(df["reason_code"].unique()))
        tier_filter = colf2.multiselect("Materiality tier", sorted(df["materiality_tier"].unique()))
        account_filter = colf3.multiselect("Account", sorted(df["account"].unique()))
        escalated_only = colf4.checkbox("Escalated only")

        filtered = df.copy()
        if reason_filter:
            filtered = filtered[filtered["reason_code"].isin(reason_filter)]
        if tier_filter:
            filtered = filtered[filtered["materiality_tier"].isin(tier_filter)]
        if account_filter:
            filtered = filtered[filtered["account"].isin(account_filter)]
        if escalated_only:
            filtered = filtered[filtered["escalated"]]

        filtered = filtered.sort_values("abs_value_impact", ascending=False)
        st.dataframe(filtered, use_container_width=True, height=500)

        st.download_button(
            "⬇ Download break blotter (CSV)",
            data=filtered.to_csv(index=False).encode(),
            file_name="break_blotter.csv", mime="text/csv",
        )
        excel_bytes = build_excel_report(result)
        st.download_button(
            "⬇ Download full Excel report",
            data=excel_bytes,
            file_name="reconciliation_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# --- Break detail tab ---------------------------------------------------
with tabs[2]:
    if result is None or len(result.breaks) == 0:
        st.info("No breaks to show yet.")
    else:
        labels = [f"{b.account} | {b.internal_security_id or b.custodian_security_code} | {b.reason_code}" for b in result.breaks]
        idx = st.selectbox("Select a break", range(len(labels)), format_func=lambda i: labels[i])
        b = result.breaks[idx]

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Custodian")
            st.write({"quantity": b.custodian_qty, "market_value": b.custodian_value, "currency": b.custodian_ccy,
                      "custodian_security_code": b.custodian_security_code})
        with col2:
            st.subheader("Internal")
            st.write({"quantity": b.internal_qty, "market_value": b.internal_value, "currency": b.internal_ccy,
                      "internal_security_id": b.internal_security_id})

        st.subheader("Security master row used")
        if st.session_state.master_df is not None and b.internal_security_id:
            row = st.session_state.master_df[st.session_state.master_df["internal_security_id"] == b.internal_security_id]
            if len(row) > 0:
                st.dataframe(row, use_container_width=True)
            else:
                st.caption("No matching security master row (unmapped).")
        else:
            st.caption("No internal_security_id resolved for this break.")

        st.subheader("Reason & suggested action")
        st.write(f"**Reason code:** {b.reason_code}")
        st.write(f"**Detail:** {b.reason_detail}")
        st.write(f"**Suggested action:** {b.suggested_action}")
        st.write(f"**Materiality:** {b.materiality_tier} | **SLA due:** {b.sla_due_date} | **Escalated:** {b.escalated}")
        if b.escalation_reason:
            st.write(f"**Escalation reason:** {b.escalation_reason}")

        st.subheader("Evidence used")
        if b.evidence_used:
            for e in b.evidence_used:
                st.write(f"- {e}")
        else:
            st.caption("No evidence file explained this break.")

        st.subheader("Audit trail")
        for entry in b.audit_trail:
            st.code(f"[{entry.rule}] evidence: {entry.evidence}\n  values: {entry.values_compared}\n  outcome: {entry.outcome}")

# --- File validation tab -----------------------------------------------------
with tabs[3]:
    if result is None:
        st.info("Run a reconciliation to see the validation report.")
    else:
        vdf = validation_issues_to_dataframe(result.validation_issues)
        if len(vdf) == 0:
            st.success("No validation issues.")
        else:
            st.dataframe(vdf, use_container_width=True)
        st.subheader("Unmapped codes discovered during this run")
        st.write("Unmapped custodian codes:", result.unmapped_custodian_codes or "None")
        st.write("Unmapped internal IDs:", result.unmapped_internal_ids or "None")

# --- Security master tab -----------------------------------------------------
with tabs[4]:
    if st.session_state.master_df is None:
        st.info("Run a reconciliation to load the security master.")
    else:
        search = st.text_input("Search (ticker, ISIN, internal ID, custodian code, name)")
        mdf = st.session_state.master_df
        if search:
            mask = mdf.apply(lambda row: search.upper() in " ".join(str(v) for v in row.values).upper(), axis=1)
            mdf = mdf[mask]
        st.dataframe(mdf, use_container_width=True, height=500)

# --- How it works tab ---------------------------------------------------
with tabs[5]:
    st.markdown("""
### Process flow
1. **Validate** — required columns, business date, numeric fields, position-count deviation, control totals, and security-master quality checks (duplicate IDs, ambiguous mappings, missing asset class/multiplier).
2. **Standardise** — uppercase/trim identifiers, parse dates, recompute missing market values, map custodian codes to internal IDs via the security master, apply unit multipliers.
3. **Match** — pair custodian and internal rows on (business date, account, internal security ID). A key with more than one row on either side becomes a DUPLICATE break instead of a false match.
4. **Compare** — check quantity, value and price differences against the asset class's tolerance; a currency disagreement is always a CCY_MISMATCH.
5. **Classify** (rule-based, fixed order): **SETUP** → **CCY_MISMATCH** → **TIMING** (unsettled pending trade) → **CORP** (corporate action processed on one side) → **PRICE** (quantities agree, prices don't) → **TRADE** (a recent booking explains the gap) → **UNEXPLAINED** (no rule fired — an honest fallback, never forced).
6. **Prioritise** — value impact, materiality tier, SLA due date (business days, skipping weekends/holidays), and escalation.
7. **Suggest** a plain-English next action per reason code.
8. **KPIs** — break rate, gross/net exposure, auto-explained share, aging.

### Why rules, not ML
This prototype is entirely rule-based and deterministic — the same input always produces the same output, and every decision is traceable to a named rule and the evidence it used. IVP's own product additionally uses AI/ML to suggest resolutions; that is explicitly out of scope here, both to keep the logic auditable for this project and because a defensible ML classifier needs far more labelled break history than a prototype has.

### Honest limitations
- Positions only — no cash, trade, NAV or P&L reconciliation.
- Two-way (custodian vs internal) only — no N-way matching across multiple custodians/administrators.
- Identifier matching is exact (via the security master), not fuzzy.
- The security master here is a simplified stand-in with no lifecycle governance or real vendor feed.
- All thresholds are illustrative assumptions, not industry benchmarks.
""")

st.caption("PROTOTYPE — synthetic data only. Rule-based engine, no machine learning. Not affiliated with or endorsed by IVP.")
