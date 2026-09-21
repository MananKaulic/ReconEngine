from datetime import date, timedelta

import pandas as pd

from recon_engine.validation import has_blocking_errors, validate_inputs
from tests.conftest import RUN_DATE, cust_row, intl_row, master_row


def test_missing_required_column_is_error():
    cust = pd.DataFrame([{"business_date": RUN_DATE, "account": "A", "quantity": 1, "price": 1, "market_value": 1, "currency": "INR"}])
    # missing custodian_security_code
    intl = pd.DataFrame([intl_row()])
    master = pd.DataFrame([master_row()])
    issues = validate_inputs(cust, intl, master, RUN_DATE)
    codes = [i.code for i in issues]
    assert "MISSING_COLUMNS" in codes
    assert has_blocking_errors(issues)


def test_non_numeric_quantity_is_error():
    row = cust_row()
    row["quantity"] = "not_a_number"
    cust = pd.DataFrame([row])
    intl = pd.DataFrame([intl_row()])
    master = pd.DataFrame([master_row()])
    issues = validate_inputs(cust, intl, master, RUN_DATE)
    codes = [i.code for i in issues]
    assert "NON_NUMERIC_VALUE" in codes
    assert has_blocking_errors(issues)


def test_business_date_mismatch_is_warning():
    wrong_date = RUN_DATE - timedelta(days=1)
    cust = pd.DataFrame([cust_row(business_date=wrong_date)])
    intl = pd.DataFrame([intl_row()])
    master = pd.DataFrame([master_row()])
    issues = validate_inputs(cust, intl, master, RUN_DATE)
    codes = [i.code for i in issues]
    assert "BUSINESS_DATE_MISMATCH" in codes
    # A date mismatch alone should not be a blocking error.
    assert not has_blocking_errors(issues)


def test_position_count_deviation_flagged():
    cust = pd.DataFrame([cust_row(account=f"ACC{i}") for i in range(3)])
    intl = pd.DataFrame([intl_row(account=f"ACC{i}") for i in range(3)])
    master = pd.DataFrame([master_row()])
    issues = validate_inputs(cust, intl, master, RUN_DATE, expected_position_count=100, expected_count_deviation_pct=5)
    codes = [i.code for i in issues]
    assert "POSITION_COUNT_DEVIATION" in codes


def test_control_total_mismatch_flagged():
    cust = pd.DataFrame([cust_row(mv=5000.0)])
    intl = pd.DataFrame([intl_row()])
    master = pd.DataFrame([master_row()])
    issues = validate_inputs(cust, intl, master, RUN_DATE, custodian_control_total=999_999)
    codes = [i.code for i in issues]
    assert "CONTROL_TOTAL_MISMATCH" in codes


def test_no_issues_on_clean_inputs():
    cust = pd.DataFrame([cust_row()])
    intl = pd.DataFrame([intl_row()])
    master = pd.DataFrame([master_row()])
    pending = pd.DataFrame(columns=["trade_id", "account", "internal_security_id", "side", "quantity", "trade_date", "expected_settlement_date", "status"])
    corp = pd.DataFrame(columns=["internal_security_id", "action_type", "ex_date", "ratio", "processed_internally", "processed_at_custodian"])
    issues = validate_inputs(cust, intl, master, RUN_DATE, pending_trades_df=pending, corporate_actions_df=corp)
    assert not has_blocking_errors(issues)
