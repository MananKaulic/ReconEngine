from datetime import date

from recon_engine.config import add_business_days, business_days_between
from recon_engine.prioritise import escalation_flags, materiality_and_sla, net_exposure_escalation


def test_materiality_tiers_by_value(config):
    same_day, due = materiality_and_sla(25_00_000, date(2026, 9, 18), config)
    assert same_day == "SAME_DAY"
    assert due == date(2026, 9, 18)  # 0 business days = same day

    next_day, due2 = materiality_and_sla(5_00_000, date(2026, 9, 18), config)
    assert next_day == "NEXT_DAY"

    routine, due3 = materiality_and_sla(50_000, date(2026, 9, 18), config)
    assert routine == "ROUTINE"


def test_sla_due_date_skips_weekends(config):
    # Friday 18 Sep 2026 + 1 business day should land on Monday 21 Sep 2026
    # (skipping Saturday 19th and Sunday 20th).
    friday = date(2026, 9, 18)
    assert friday.weekday() == 4  # sanity check: Friday
    tier, due = materiality_and_sla(5_00_000, friday, config)  # NEXT_DAY = 1 business day
    assert due == date(2026, 9, 21)


def test_sla_due_date_skips_holidays():
    from recon_engine.config import Config
    import yaml
    from pathlib import Path
    raw = yaml.safe_load(Path("config/tolerances.yaml").read_text())
    raw["holiday_calendar"] = ["2026-09-21"]  # make the Monday a holiday too
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(raw, f)
        path = f.name
    cfg = Config.load(path)
    friday = date(2026, 9, 18)
    tier, due = materiality_and_sla(5_00_000, friday, cfg)  # 1 business day
    # Sat/Sun skipped, Monday is now a holiday too -> lands on Tuesday
    assert due == date(2026, 9, 22)


def test_add_business_days_zero_returns_same_day():
    assert add_business_days(date(2026, 9, 18), 0, set()) == date(2026, 9, 18)


def test_business_days_between():
    assert business_days_between(date(2026, 9, 18), date(2026, 9, 21), set()) == 1
    assert business_days_between(date(2026, 9, 18), date(2026, 9, 18), set()) == 0


def test_single_break_escalation(config):
    threshold = config.escalation["single_break_value_inr"]
    escalated, reason = escalation_flags(threshold + 1, 0.0, config)
    assert escalated is True
    assert "senior ops" in reason

    not_escalated, reason2 = escalation_flags(threshold - 1, 0.0, config)
    assert not_escalated is False
    assert reason2 is None


def test_net_exposure_escalation(config):
    aum = config.aum_inr
    pct = config.escalation["net_exposure_pct_of_aum"]
    big_net = aum * (pct / 100.0) * 2  # well above threshold
    escalated, reason = net_exposure_escalation(big_net, config)
    assert escalated is True
    assert "portfolio manager" in reason

    small_net = aum * (pct / 100.0) * 0.01
    not_escalated, reason2 = net_exposure_escalation(small_net, config)
    assert not_escalated is False
