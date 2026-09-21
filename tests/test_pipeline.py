from datetime import date, timedelta

import pandas as pd

from recon_engine import Config, run_reconciliation
from tests.conftest import RUN_DATE, cust_row, intl_row, make_master, master_row


def _run(cust_rows, intl_rows, master_rows, config, **kwargs):
    return run_reconciliation(
        pd.DataFrame(cust_rows), pd.DataFrame(intl_rows), pd.DataFrame(master_rows),
        RUN_DATE, config, **kwargs,
    )


def test_exact_match(config):
    result = _run([cust_row()], [intl_row()], [master_row()], config)
    assert result.matched_count == 1
    assert len(result.breaks) == 0


def test_rounding_inside_tolerance_matches(config):
    # Equity tolerance: 1 share / Rs 500. A 0.5-share, Rs 40 rounding gap
    # should still match.
    result = _run(
        [cust_row(qty=100.4, price=50.0, mv=100.4 * 50.0)],
        [intl_row(qty=100.0, price=50.0, mv=100.0 * 50.0)],
        [master_row()], config,
    )
    assert result.matched_count == 1
    assert len(result.breaks) == 0


def test_quantity_difference_is_a_break(config):
    result = _run(
        [cust_row(qty=150.0, price=50.0, mv=150.0 * 50.0)],
        [intl_row(qty=100.0, price=50.0, mv=100.0 * 50.0)],
        [master_row()], config,
    )
    assert result.matched_count == 0
    assert len(result.breaks) == 1


def test_record_cannot_match_twice_and_duplicate_detected(config):
    # Two custodian rows for the same key: should raise exactly ONE
    # DUPLICATE break, not two breaks and not a false single match.
    result = _run(
        [cust_row(), cust_row()],
        [intl_row()],
        [master_row()], config,
    )
    assert result.matched_count == 0
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "DUPLICATE"


def _empty_internal_df():
    return pd.DataFrame(columns=["business_date", "account", "internal_security_id", "quantity", "price", "market_value", "currency"])


def test_unmapped_custodian_code_is_setup_and_not_dropped(config):
    result = _run(
        [cust_row(code="CUST_GHOST")],
        _empty_internal_df(),
        [master_row()], config,
    )
    assert len(result.breaks) == 1
    b = result.breaks[0]
    assert b.reason_code == "SETUP"
    assert "not found in security master" in b.reason_detail
    assert "CUST_GHOST" in result.unmapped_custodian_codes


def test_inactive_security_raises_setup(config):
    result = _run(
        [cust_row()],
        [intl_row()],
        [master_row(status="INACTIVE")], config,
    )
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "SETUP"
    assert "INACTIVE" in result.breaks[0].reason_detail


def test_not_yet_effective_security_raises_setup(config):
    future_date = (RUN_DATE + timedelta(days=30)).isoformat()
    result = _run(
        [cust_row()],
        [intl_row()],
        [master_row(effective_from=future_date)], config,
    )
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "SETUP"
    assert "not yet effective" in result.breaks[0].reason_detail


def test_ambiguous_mapping_caught_by_validation_and_raises_setup(config):
    master = make_master(
        master_row(internal_id="SEC0001", custodian_code="CUST_AMBIG"),
        master_row(internal_id="SEC0002", custodian_code="CUST_AMBIG"),
    )
    result = _run([cust_row(code="CUST_AMBIG")], _empty_internal_df(), master, config)
    # Validation should flag it as an ERROR-severity ambiguous mapping...
    codes = [i.code for i in result.validation_issues]
    assert "AMBIGUOUS_MAPPING" in codes
    # ...and the record still surfaces as its own SETUP break, not dropped.
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "SETUP"
    assert "ambiguously" in result.breaks[0].reason_detail


def test_unit_multiplier_prevents_false_break_on_bond(config):
    # Custodian reports face value (units * multiplier); internal reports
    # units. Without the multiplier this would show as a huge quantity break.
    units = 500.0
    multiplier = 1000.0
    result = _run(
        [cust_row(qty=units * multiplier, price=98.0, mv=units * 98.0)],
        [intl_row(qty=units, price=98.0, mv=units * 98.0)],
        [master_row(asset_class="FixedIncome", unit_multiplier=multiplier)], config,
    )
    assert result.matched_count == 1
    assert len(result.breaks) == 0


def test_asset_class_selects_correct_tolerance(config):
    # A 50-unit gap is within Derivative tolerance context (0.1 contracts is
    # tight) -- use a FixedIncome gap of 500 face value, which IS within the
    # FixedIncome tolerance (1000) but would NOT be within Equity tolerance (1).
    result = _run(
        [cust_row(qty=100_500.0, price=99.0, mv=100_500.0 * 99.0 / 1000)],
        [intl_row(qty=100.0, price=99.0, mv=100.0 * 99.0)],
        [master_row(asset_class="FixedIncome", unit_multiplier=1000)], config,
    )
    # custodian quantity normalised: 100_500/1000 = 100.5 vs internal 100 -> gap 0.5, within 1000 tolerance
    assert result.matched_count == 1


def test_corp_action_processed_one_side_yields_corp(config):
    ratio = 2.0
    internal_qty = 1000.0
    custodian_qty = internal_qty * ratio
    price = 50.0
    corp_df = pd.DataFrame([{
        "internal_security_id": "SEC0001", "action_type": "SPLIT", "ex_date": RUN_DATE - timedelta(days=1),
        "ratio": ratio, "processed_internally": "N", "processed_at_custodian": "Y",
    }])
    result = _run(
        [cust_row(qty=custodian_qty, price=price / ratio, mv=custodian_qty * price / ratio)],
        [intl_row(qty=internal_qty, price=price, mv=internal_qty * price)],
        [master_row()], config, corporate_actions_df=corp_df,
    )
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "CORP"


def test_pending_trade_explains_timing(config):
    internal_qty = 800.0
    trade_qty = 200.0
    custodian_qty = internal_qty - trade_qty
    price = 50.0
    pending_df = pd.DataFrame([{
        "trade_id": "T0001", "account": "ACC1", "internal_security_id": "SEC0001",
        "side": "BUY", "quantity": trade_qty, "trade_date": RUN_DATE - timedelta(days=1),
        "expected_settlement_date": RUN_DATE + timedelta(days=1), "status": "unsettled",
    }])
    result = _run(
        [cust_row(qty=custodian_qty, price=price, mv=custodian_qty * price)],
        [intl_row(qty=internal_qty, price=price, mv=internal_qty * price)],
        [master_row()], config, pending_trades_df=pending_df,
    )
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "TIMING"


def test_price_only_difference_yields_price(config):
    qty = 100.0
    result = _run(
        [cust_row(qty=qty, price=57.0, mv=qty * 57.0)],
        [intl_row(qty=qty, price=50.0, mv=qty * 50.0)],
        [master_row()], config,
    )
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "PRICE"


def test_missing_internal_and_missing_custodian(config):
    result = _run(
        [cust_row(account="ACC1"), cust_row(account="ACC2", code="CUST0001")],
        [intl_row(account="ACC1")],
        [master_row()], config,
    )
    # ACC1 matches exactly; ACC2 custodian-only -> MISSING_INTERNAL
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "MISSING_INTERNAL"

    result2 = _run(
        [cust_row(account="ACC1")],
        [intl_row(account="ACC1"), intl_row(account="ACC2")],
        [master_row()], config,
    )
    assert len(result2.breaks) == 1
    assert result2.breaks[0].reason_code == "MISSING_CUSTODIAN"


def test_running_without_evidence_files_produces_unexplained_with_note(config):
    internal_qty = 800.0
    custodian_qty = 600.0
    price = 50.0
    # No pending_trades_df / corporate_actions_df passed at all.
    result = _run(
        [cust_row(qty=custodian_qty, price=price, mv=custodian_qty * price)],
        [intl_row(qty=internal_qty, price=price, mv=internal_qty * price)],
        [master_row()], config,
    )
    assert len(result.breaks) == 1
    b = result.breaks[0]
    assert b.reason_code == "UNEXPLAINED"
    assert "not supplied" in b.reason_detail
    # Validation should also have warned that evidence files were missing.
    codes = [i.code for i in result.validation_issues]
    assert codes.count("EVIDENCE_FILE_NOT_SUPPLIED") == 2
    # And it must not crash -- covered simply by reaching this assertion.


def test_unknown_case_goes_to_unexplained(config):
    result = _run(
        [cust_row(qty=137.0, price=50.0, mv=137.0 * 50.0)],
        [intl_row(qty=100.0, price=50.0, mv=100.0 * 50.0)],
        [master_row()], config,
    )
    assert len(result.breaks) == 1
    assert result.breaks[0].reason_code == "UNEXPLAINED"


def test_tolerance_change_flips_a_result(config, tmp_path):
    # A 5-share / Rs 250 gap is a break under the default Equity tolerance
    # (1 share / Rs 500)...
    cust = [cust_row(qty=105.0, price=50.0, mv=105.0 * 50.0)]
    intl = [intl_row(qty=100.0, price=50.0, mv=100.0 * 50.0)]
    master = [master_row()]
    result = _run(cust, intl, master, config)
    assert len(result.breaks) == 1

    # ...but matches once we widen the tolerance.
    import copy
    widened = copy.deepcopy(config)
    widened.asset_class_tolerances = dict(config.asset_class_tolerances)
    widened.asset_class_tolerances["Equity"] = {"quantity_abs": 10, "value_abs_inr": 1000}
    result2 = _run(cust, intl, master, widened)
    assert len(result2.breaks) == 0


def test_determinism(config):
    cust = [cust_row(qty=105.0, price=50.0, mv=105.0 * 50.0)]
    intl = [intl_row(qty=100.0, price=50.0, mv=100.0 * 50.0)]
    master = [master_row()]
    r1 = _run(cust, intl, master, config)
    r2 = _run(cust, intl, master, config)
    assert r1.kpis == r2.kpis
    assert len(r1.breaks) == len(r2.breaks) == 1
    assert r1.breaks[0].reason_code == r2.breaks[0].reason_code
