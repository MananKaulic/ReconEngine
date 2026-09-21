from datetime import date

from recon_engine.kpis import compute_kpis
from recon_engine.models import BreakRecord


def _break(signed_impact, reason_code="UNEXPLAINED", tier="ROUTINE", due=date(2026, 9, 18), escalated=False):
    return BreakRecord(
        business_date=date(2026, 9, 18), account="ACC1", internal_security_id="SEC0001",
        custodian_security_code="CUST0001", security_name="Test", asset_class="Equity",
        custodian_qty=100, internal_qty=90, custodian_value=5000, internal_value=4500,
        custodian_ccy="INR", internal_ccy="INR",
        reason_code=reason_code, reason_detail="test", suggested_action="test",
        abs_value_impact=abs(signed_impact), signed_value_impact=signed_impact,
        materiality_tier=tier, sla_due_date=due, escalated=escalated, escalation_reason=None,
    )


def test_gross_vs_net_exposure_maths(config):
    breaks = [_break(100.0), _break(-40.0), _break(60.0)]
    kpis = compute_kpis(matched_count=10, breaks=breaks, run_date=date(2026, 9, 18), config=config)
    # gross = sum of absolute impacts = 100 + 40 + 60 = 200
    assert kpis["gross_exposure_diff_inr"] == 200.0
    # net = sum of signed impacts = 100 - 40 + 60 = 120
    assert kpis["net_exposure_diff_inr"] == 120.0
    assert kpis["break_count"] == 3
    assert kpis["total_positions_reconciled"] == 13
    assert kpis["break_rate_pct"] == round(3 / 13 * 100, 2)


def test_breaks_by_reason_and_tier(config):
    breaks = [_break(10, reason_code="PRICE", tier="SAME_DAY"), _break(20, reason_code="PRICE", tier="ROUTINE"),
              _break(30, reason_code="TIMING", tier="ROUTINE")]
    kpis = compute_kpis(0, breaks, date(2026, 9, 18), config)
    assert kpis["breaks_by_reason_code"] == {"PRICE": 2, "TIMING": 1}
    assert kpis["breaks_by_materiality_tier"] == {"SAME_DAY": 1, "ROUTINE": 2}


def test_unexplained_vs_auto_explained_share(config):
    breaks = [_break(10, reason_code="UNEXPLAINED"), _break(20, reason_code="PRICE"), _break(30, reason_code="TIMING")]
    kpis = compute_kpis(0, breaks, date(2026, 9, 18), config)
    assert kpis["unexplained_count"] == 1
    assert kpis["auto_explained_count"] == 2
    assert kpis["auto_explained_share_pct"] == round(2 / 3 * 100, 2)


def test_empty_breaks_no_crash(config):
    kpis = compute_kpis(5, [], date(2026, 9, 18), config)
    assert kpis["break_count"] == 0
    assert kpis["break_rate_pct"] == 0.0
    assert kpis["gross_exposure_diff_inr"] == 0.0
