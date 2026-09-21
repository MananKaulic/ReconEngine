"""
scripts/generate_data.py
-------------------------
Seeded synthetic data generator for the reconciliation engine prototype.

Produces:
  data/security_master.csv        (~40-60 NSE-style securities, synthetic ISINs)
  data/custodian_positions.csv    (~300 positions across 5 accounts)
  data/internal_positions.csv
  data/pending_trades.csv         (optional evidence file)
  data/corporate_actions.csv      (optional evidence file)
  data/answer_key.csv             (planted breaks and their expected reason code)

ALL data is synthetic. ISINs follow the correct FORMAT (2 letters + 9
alphanumeric + 1 check digit) but are randomly generated and do NOT
correspond to real securities. NSE tickers used are real company tickers
used purely as realistic-looking labels for a finance-education prototype;
no real market data (prices, quantities) is used or implied.

Usage: python scripts/generate_data.py [--seed 42] [--out-dir data]
"""
from __future__ import annotations

import argparse
import random
import string
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# A pool of real NSE tickers used only as realistic-looking labels.
NSE_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
    "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ITC", "BAJFINANCE", "ASIANPAINT",
    "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO", "NESTLEIND", "ONGC",
    "NTPC", "POWERGRID", "M&M", "TATASTEEL", "TATAMOTORS", "ADANIPORTS", "HCLTECH",
    "TECHM", "GRASIM", "JSWSTEEL", "CIPLA", "DRREDDY", "BAJAJFINSV", "EICHERMOT",
    "BRITANNIA", "DIVISLAB", "HEROMOTOCO", "COALINDIA", "BPCL", "SHREECEM", "UPL",
    "APOLLOHOSP", "HDFCLIFE", "SBILIFE", "INDUSINDBK", "TATACONSUM", "BAJAJ-AUTO",
]

ACCOUNTS = ["ACC-EQ-01", "ACC-EQ-02", "ACC-FI-01", "ACC-MM-01", "ACC-DER-01"]

ASSET_CLASS_BY_ACCOUNT = {
    "ACC-EQ-01": "Equity", "ACC-EQ-02": "Equity",
    "ACC-FI-01": "FixedIncome", "ACC-MM-01": "MoneyMarket", "ACC-DER-01": "Derivative",
}


def synthetic_isin(rng: random.Random) -> str:
    """Format-valid but FAKE ISIN: 'IN' + 9 alphanumeric + 1 check digit.
    The check digit here is just a random digit, not a real Luhn check --
    clearly a synthetic placeholder, not a real security identifier."""
    body = "".join(rng.choices(string.ascii_uppercase + string.digits, k=9))
    check = rng.choice(string.digits)
    return f"IN{body}{check}"


def build_security_master(rng: random.Random, n_securities: int = 50) -> pd.DataFrame:
    rows = []
    tickers = rng.sample(NSE_TICKERS, k=min(n_securities, len(NSE_TICKERS)))
    # pad with synthetic tickers if we need more than the real pool
    i = 0
    while len(tickers) < n_securities:
        tickers.append(f"SYN{i:03d}")
        i += 1

    for idx, ticker in enumerate(tickers):
        internal_id = f"SEC{idx+1:04d}"
        custodian_code = f"CUST{idx+1:04d}"
        # Distribute asset classes: mostly equity, some FI/MM/derivative
        if idx % 10 == 0:
            asset_class, multiplier, ccy = "FixedIncome", 1000, "INR"
        elif idx % 10 == 1:
            asset_class, multiplier, ccy = "MoneyMarket", 100, "INR"
        elif idx % 10 == 2:
            asset_class, multiplier, ccy = "Derivative", 10, "INR"
        else:
            asset_class, multiplier, ccy = "Equity", 1, "INR"

        rows.append({
            "internal_security_id": internal_id,
            "custodian_security_code": custodian_code,
            "isin": synthetic_isin(rng),
            "ticker": ticker,
            "security_name": f"{ticker} Ltd",
            "asset_class": asset_class,
            "currency": ccy,
            "unit_multiplier": multiplier,
            "status": "ACTIVE",
            "effective_from": "2015-01-01",
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=str, default="data")
    parser.add_argument("--run-date", type=str, default=None,
                         help="Business date for the run (default: most recent NSE-style weekday)")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.run_date:
        run_date = date.fromisoformat(args.run_date)
    else:
        run_date = date(2026, 9, 18)  # a Friday, fixed so the sample data is reproducible

    master = build_security_master(rng, n_securities=62)
    master_active = master[(master["status"] == "ACTIVE")].reset_index(drop=True)

    answer_key_rows = []
    cust_rows = []
    intl_rows = []
    pending_trade_rows = []
    corp_action_rows = []
    trade_counter = 1

    def base_price_for(asset_class: str) -> float:
        if asset_class == "Equity":
            return round(rng.uniform(150, 4500), 2)
        if asset_class == "FixedIncome":
            return round(rng.uniform(95, 105), 2)  # price per 100 face
        if asset_class == "MoneyMarket":
            return round(rng.uniform(99, 100.5), 2)
        return round(rng.uniform(50, 500), 2)  # Derivative

    def base_qty_for(asset_class: str) -> float:
        if asset_class == "Equity":
            return float(rng.randint(100, 5000))
        if asset_class == "FixedIncome":
            return float(rng.choice([50_000, 100_000, 250_000, 500_000]))  # face value
        if asset_class == "MoneyMarket":
            return float(rng.choice([10_000, 25_000, 50_000]))
        return float(rng.randint(5, 200))  # derivative contracts

    # ---- Assign one (account, security) combo per position slot ----------
    # Each account is nominally "typed" to an asset class for the sake of a
    # clean story in the pitch (e.g. ACC-FI-01 = the bond book), but holds a
    # majority of that class plus a minority of other classes, which is more
    # realistic for a hedge fund account and also gives us enough distinct
    # (account, security) combinations to reach ~300 positions from a
    # security master of ~60 names.
    n_target_positions = 300
    combos = []
    n_per_account = n_target_positions // len(ACCOUNTS)
    for account in ACCOUNTS:
        primary_class = ASSET_CLASS_BY_ACCOUNT[account]
        primary_pool = master_active[master_active["asset_class"] == primary_class]
        other_pool = master_active[master_active["asset_class"] != primary_class]
        n_primary = min(len(primary_pool), max(1, int(n_per_account * 0.6)))
        n_other = min(len(other_pool), n_per_account - n_primary)
        chosen = pd.concat([
            primary_pool.sample(n=n_primary, random_state=rng.randint(0, 10_000)),
            other_pool.sample(n=n_other, random_state=rng.randint(0, 10_000)) if n_other > 0 else other_pool.iloc[0:0],
        ])
        for _, sec in chosen.iterrows():
            combos.append((account, sec))

    # Deduplicate (account, internal_security_id) to keep one position per combo,
    # topping back up to ~300 by resampling extra securities per account if short.
    seen = set()
    unique_combos = []
    for account, sec in combos:
        key = (account, sec["internal_security_id"])
        if key not in seen:
            seen.add(key)
            unique_combos.append((account, sec))
    combos = unique_combos

    # Reserve the first N combos for specific planted scenarios (edge cases),
    # the remainder are "clean" positions that should match exactly or within
    # a small random rounding tolerance.
    planted_needed = 16
    if len(combos) < planted_needed + 10:
        raise RuntimeError("Not enough distinct (account, security) combinations generated; increase n_securities.")

    def emit_clean(account, sec, exact=True):
        asset_class = sec["asset_class"]
        qty = base_qty_for(asset_class)
        price = base_price_for(asset_class)
        mult = float(sec["unit_multiplier"])
        internal_qty = qty
        internal_price = price
        internal_value = round(internal_qty * internal_price, 2)

        if exact:
            cust_reported_qty = qty * mult if mult != 1 else qty
            cust_price = price
        else:
            # rounding difference inside tolerance
            tol = {"Equity": 0.4, "FixedIncome": 400, "MoneyMarket": 40, "Derivative": 0.03}[asset_class]
            cust_reported_qty = (qty + rng.uniform(-tol, tol)) * mult if mult != 1 else qty + rng.uniform(-tol, tol)
            cust_price = price

        cust_value = round((cust_reported_qty / mult if mult != 1 else cust_reported_qty) * cust_price, 2)

        cust_rows.append({
            "business_date": run_date, "account": account,
            "custodian_security_code": sec["custodian_security_code"],
            "quantity": round(cust_reported_qty, 4), "price": cust_price,
            "market_value": cust_value, "currency": sec["currency"],
        })
        intl_rows.append({
            "business_date": run_date, "account": account,
            "internal_security_id": sec["internal_security_id"],
            "quantity": round(internal_qty, 4), "price": internal_price,
            "market_value": internal_value, "currency": sec["currency"],
        })

    idx = 0

    # 1) Rounding difference inside tolerance -> must MATCH
    account, sec = combos[idx]; idx += 1
    emit_clean(account, sec, exact=False)
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "MATCHED", "scenario": "rounding_inside_tolerance"})

    # 2) Duplicate: two custodian rows for the same key
    account, sec = combos[idx]; idx += 1
    qty = base_qty_for(sec["asset_class"]); price = base_price_for(sec["asset_class"])
    for _ in range(2):
        cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                           "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": sec["currency"]})
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": sec["currency"]})
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "DUPLICATE", "scenario": "duplicate_custodian_rows"})

    # 3) Currency mismatch
    account, sec = combos[idx]; idx += 1
    qty = base_qty_for(sec["asset_class"]); price = base_price_for(sec["asset_class"])
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                       "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": "USD"})
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": sec["currency"]})
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "CCY_MISMATCH", "scenario": "currency_mismatch"})

    # 4) Custodian code missing from the security master (unmapped) -> SETUP
    account, sec = combos[idx]; idx += 1
    fake_code = "CUSTGHOST01"
    qty = base_qty_for(sec["asset_class"]); price = base_price_for(sec["asset_class"])
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": fake_code,
                       "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": sec["currency"]})
    answer_key_rows.append({"account": account, "internal_security_id": "(unmapped)", "expected_reason_code": "SETUP", "scenario": "unmapped_custodian_code"})

    # 5) Custodian code mapped to an INACTIVE security -> SETUP
    account, sec = combos[idx]; idx += 1
    inactive_id = "SEC9001"
    inactive_code = "CUST9001"
    master = pd.concat([master, pd.DataFrame([{
        "internal_security_id": inactive_id, "custodian_security_code": inactive_code,
        "isin": synthetic_isin(rng), "ticker": "DELISTED", "security_name": "Delisted Co Ltd",
        "asset_class": "Equity", "currency": "INR", "unit_multiplier": 1,
        "status": "INACTIVE", "effective_from": "2015-01-01",
    }])], ignore_index=True)
    qty = base_qty_for("Equity"); price = base_price_for("Equity")
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": inactive_code,
                       "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": "INR"})
    answer_key_rows.append({"account": account, "internal_security_id": inactive_id, "expected_reason_code": "SETUP", "scenario": "inactive_security"})

    # 6) One custodian code mapped to TWO internal IDs -> ambiguous SETUP
    account, sec = combos[idx]; idx += 1
    account2, sec2 = combos[idx]; idx += 1
    ambiguous_code = "CUSTAMBIG1"
    dupe_master_rows = pd.DataFrame([
        {"internal_security_id": "SEC9002", "custodian_security_code": ambiguous_code, "isin": synthetic_isin(rng),
         "ticker": "AMBIG-A", "security_name": "Ambiguous Co A", "asset_class": "Equity", "currency": "INR",
         "unit_multiplier": 1, "status": "ACTIVE", "effective_from": "2015-01-01"},
        {"internal_security_id": "SEC9003", "custodian_security_code": ambiguous_code, "isin": synthetic_isin(rng),
         "ticker": "AMBIG-B", "security_name": "Ambiguous Co B", "asset_class": "Equity", "currency": "INR",
         "unit_multiplier": 1, "status": "ACTIVE", "effective_from": "2015-01-01"},
    ])
    master = pd.concat([master, dupe_master_rows], ignore_index=True)
    qty = base_qty_for("Equity"); price = base_price_for("Equity")
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": ambiguous_code,
                       "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": "INR"})
    answer_key_rows.append({"account": account, "internal_security_id": "SEC9002/SEC9003", "expected_reason_code": "SETUP", "scenario": "ambiguous_custodian_mapping"})

    # 7) Bond: custodian reports face value, internal reports units -> must NOT break
    fi_rows = master_active[master_active["asset_class"] == "FixedIncome"]
    sec = fi_rows.iloc[0]
    account = "ACC-FI-01"
    # Remove this (account, security) combo from the "clean" pool below so it
    # is not accidentally emitted a second time (which would create a false
    # duplicate on top of the planted scenario).
    combos = [(a, s) for (a, s) in combos if not (a == account and s["internal_security_id"] == sec["internal_security_id"])]
    units = 500.0  # internal reports 500 units
    mult = float(sec["unit_multiplier"])  # e.g. 1000 face per unit
    face_value_reported_by_custodian = units * mult
    price = base_price_for("FixedIncome")
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": units, "price": price, "market_value": round(units * price, 2), "currency": sec["currency"]})
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                       "quantity": face_value_reported_by_custodian, "price": price,
                       "market_value": round(units * price, 2), "currency": sec["currency"]})
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "MATCHED", "scenario": "unit_multiplier_face_value_vs_units"})

    # 8) Split processed on one side only -> CORP
    account, sec = combos[idx]; idx += 1
    ex_date = run_date - timedelta(days=2)
    ratio = 2.0
    internal_qty = 1000.0
    custodian_qty = internal_qty * ratio  # custodian has processed the 2-for-1 split, internal hasn't
    price = base_price_for("Equity") / ratio
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": internal_qty, "price": price * ratio, "market_value": round(internal_qty * price * ratio, 2), "currency": sec["currency"]})
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                       "quantity": custodian_qty, "price": price, "market_value": round(custodian_qty * price, 2), "currency": sec["currency"]})
    corp_action_rows.append({"internal_security_id": sec["internal_security_id"], "action_type": "SPLIT", "ex_date": ex_date,
                              "ratio": ratio, "processed_internally": "N", "processed_at_custodian": "Y"})
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "CORP", "scenario": "split_processed_one_side"})

    # 9) Pending settlement explains a quantity gap -> TIMING
    account, sec = combos[idx]; idx += 1
    internal_qty = 800.0
    trade_qty = 200.0
    custodian_qty = internal_qty - trade_qty  # custodian hasn't reflected the unsettled BUY yet
    price = base_price_for(sec["asset_class"])
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": internal_qty, "price": price, "market_value": round(internal_qty * price, 2), "currency": sec["currency"]})
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                       "quantity": custodian_qty, "price": price, "market_value": round(custodian_qty * price, 2), "currency": sec["currency"]})
    pending_trade_rows.append({"trade_id": f"T{trade_counter:04d}", "account": account, "internal_security_id": sec["internal_security_id"],
                                "side": "BUY", "quantity": trade_qty, "trade_date": run_date - timedelta(days=1),
                                "expected_settlement_date": run_date + timedelta(days=1), "status": "unsettled"})
    trade_counter += 1
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "TIMING", "scenario": "pending_settlement_explains_gap"})

    # 10) Price-only difference -> PRICE
    account, sec = combos[idx]; idx += 1
    qty = base_qty_for(sec["asset_class"])
    internal_price = base_price_for(sec["asset_class"])
    custodian_price = internal_price * 1.03  # 3% off, above the 0.5% tolerance
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": qty, "price": internal_price, "market_value": round(qty * internal_price, 2), "currency": sec["currency"]})
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                       "quantity": qty, "price": custodian_price, "market_value": round(qty * custodian_price, 2), "currency": sec["currency"]})
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "PRICE", "scenario": "price_only_difference"})

    # 11) Missing position on custodian side only -> MISSING_CUSTODIAN
    account, sec = combos[idx]; idx += 1
    qty = base_qty_for(sec["asset_class"]); price = base_price_for(sec["asset_class"])
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": sec["currency"]})
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "MISSING_CUSTODIAN", "scenario": "missing_on_custodian_side"})

    # 12) Missing position on internal side only -> MISSING_INTERNAL
    account, sec = combos[idx]; idx += 1
    qty = base_qty_for(sec["asset_class"]); price = base_price_for(sec["asset_class"])
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                       "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": sec["currency"]})
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "MISSING_INTERNAL", "scenario": "missing_on_internal_side"})

    # 13) Would be TIMING if pending_trades were supplied (we still add the
    #     trade row to pending_trades.csv globally, but this scenario is used
    #     by evaluate.py's WITHOUT-evidence run to show it degrades to UNEXPLAINED)
    account, sec = combos[idx]; idx += 1
    internal_qty = 500.0
    trade_qty = 150.0
    custodian_qty = internal_qty - trade_qty
    price = base_price_for(sec["asset_class"])
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": internal_qty, "price": price, "market_value": round(internal_qty * price, 2), "currency": sec["currency"]})
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                       "quantity": custodian_qty, "price": price, "market_value": round(custodian_qty * price, 2), "currency": sec["currency"]})
    pending_trade_rows.append({"trade_id": f"T{trade_counter:04d}", "account": account, "internal_security_id": sec["internal_security_id"],
                                "side": "BUY", "quantity": trade_qty, "trade_date": run_date - timedelta(days=1),
                                "expected_settlement_date": run_date + timedelta(days=2), "status": "unsettled"})
    trade_counter += 1
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "TIMING", "scenario": "timing_only_with_evidence"})

    # 14) Recent booking error (TRADE) -- a trade booked internally but not reflected at custodian yet, outside the "unsettled" pending set (status=settled at custodian's own pace)
    account, sec = combos[idx]; idx += 1
    internal_qty = 600.0
    trade_qty = 100.0
    custodian_qty = internal_qty - trade_qty
    price = base_price_for(sec["asset_class"])
    intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                       "quantity": internal_qty, "price": price, "market_value": round(internal_qty * price, 2), "currency": sec["currency"]})
    cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                       "quantity": custodian_qty, "price": price, "market_value": round(custodian_qty * price, 2), "currency": sec["currency"]})
    # Booked as SETTLED already (so TIMING rule, which only looks at unsettled
    # trades, won't claim it) but recent enough for the TRADE rule to find it.
    pending_trade_rows.append({"trade_id": f"T{trade_counter:04d}", "account": account, "internal_security_id": sec["internal_security_id"],
                                "side": "BUY", "quantity": trade_qty, "trade_date": run_date, "expected_settlement_date": run_date, "status": "settled"})
    trade_counter += 1
    answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "TRADE", "scenario": "recent_booking_error"})

    # 15) & 16) Genuinely unexplained breaks (random quantity gap, no evidence explains it)
    for _ in range(2):
        account, sec = combos[idx]; idx += 1
        qty = base_qty_for(sec["asset_class"])
        gap = qty * 0.15 + 37  # arbitrary gap that matches no rule
        price = base_price_for(sec["asset_class"])
        intl_rows.append({"business_date": run_date, "account": account, "internal_security_id": sec["internal_security_id"],
                           "quantity": qty, "price": price, "market_value": round(qty * price, 2), "currency": sec["currency"]})
        cust_rows.append({"business_date": run_date, "account": account, "custodian_security_code": sec["custodian_security_code"],
                           "quantity": qty - gap, "price": price, "market_value": round((qty - gap) * price, 2), "currency": sec["currency"]})
        answer_key_rows.append({"account": account, "internal_security_id": sec["internal_security_id"], "expected_reason_code": "UNEXPLAINED", "scenario": "genuinely_unexplained"})

    # ---- Remaining combos: clean, exactly-matching positions -------------
    for account, sec in combos[idx:]:
        emit_clean(account, sec, exact=True)

    custodian_df = pd.DataFrame(cust_rows)
    internal_df = pd.DataFrame(intl_rows)
    pending_trades_df = pd.DataFrame(pending_trade_rows)
    corp_actions_df = pd.DataFrame(corp_action_rows)
    answer_key_df = pd.DataFrame(answer_key_rows)

    custodian_df.to_csv(out_dir / "custodian_positions.csv", index=False)
    internal_df.to_csv(out_dir / "internal_positions.csv", index=False)
    master.to_csv(out_dir / "security_master.csv", index=False)
    pending_trades_df.to_csv(out_dir / "pending_trades.csv", index=False)
    corp_actions_df.to_csv(out_dir / "corporate_actions.csv", index=False)
    answer_key_df.to_csv(out_dir / "answer_key.csv", index=False)

    print(f"Generated {len(custodian_df)} custodian rows, {len(internal_df)} internal rows, "
          f"{len(master)} master rows, {len(answer_key_df)} planted scenarios.")
    print(f"Run date: {run_date}")


if __name__ == "__main__":
    main()
