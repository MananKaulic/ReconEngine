import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from recon_engine import Config

RUN_DATE = date(2026, 9, 18)  # a Friday


@pytest.fixture(scope="session")
def config() -> Config:
    return Config.load(ROOT / "config" / "tolerances.yaml")


def master_row(internal_id="SEC0001", custodian_code="CUST0001", asset_class="Equity",
                currency="INR", unit_multiplier=1, status="ACTIVE", effective_from="2015-01-01",
                isin="INTESTAAAAAA1", ticker="TEST"):
    return {
        "internal_security_id": internal_id, "custodian_security_code": custodian_code,
        "isin": isin, "ticker": ticker, "security_name": f"{ticker} Ltd",
        "asset_class": asset_class, "currency": currency, "unit_multiplier": unit_multiplier,
        "status": status, "effective_from": effective_from,
    }


def make_master(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows) if rows else [master_row()])


def cust_row(account="ACC1", code="CUST0001", qty=100.0, price=50.0, mv=None, ccy="INR", business_date=RUN_DATE):
    return {
        "business_date": business_date, "account": account, "custodian_security_code": code,
        "quantity": qty, "price": price, "market_value": mv if mv is not None else qty * price,
        "currency": ccy,
    }


def intl_row(account="ACC1", sec_id="SEC0001", qty=100.0, price=50.0, mv=None, ccy="INR", business_date=RUN_DATE):
    return {
        "business_date": business_date, "account": account, "internal_security_id": sec_id,
        "quantity": qty, "price": price, "market_value": mv if mv is not None else qty * price,
        "currency": ccy,
    }
