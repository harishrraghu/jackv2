"""OHLC data validator for Bank Nifty backtesting engine."""

import pandas as pd

INTRADAY_TIMEFRAMES = ["2h", "1h", "15m", "5m", "1m"]
PRICE_MIN = 1_000
PRICE_MAX = 60_000
RANGE_OUTLIER_THRESHOLD = 0.10  # 10% of Close


def validate_data(data: dict) -> dict:
    """
    Validate OHLC data across all timeframes.

    Parameters
    ----------
    data : dict
        Mapping of timeframe string -> pd.DataFrame, as returned by load_all_timeframes.

    Returns
    -------
    dict with keys: passed, ohlc_violations, date_gaps, missing_intraday,
                    value_outliers, range_outliers, summary
    """
    ohlc_violations = 0
    date_gaps = []
    missing_intraday = []
    value_outliers = 0
    range_outliers = []

    # 1. OHLC integrity & value range sanity — all timeframes
    for tf, df in data.items():
        if df.empty:
            continue

        for _, row in df.iterrows():
            o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
            date_str = str(row["Date"])[:10]

            # OHLC integrity
            if not (h >= max(o, c)):
                ohlc_violations += 1
            elif not (l <= min(o, c)):
                ohlc_violations += 1
            elif not (h >= l):
                ohlc_violations += 1
            elif not all(v > 0 for v in [o, h, l, c]):
                ohlc_violations += 1

            # Value range sanity
            for v in [o, h, l, c]:
                if v < PRICE_MIN or v > PRICE_MAX:
                    value_outliers += 1
                    break

            # Range outlier (only flag once per row)
            if c > 0:
                range_pct = (h - l) / c
                if range_pct > RANGE_OUTLIER_THRESHOLD:
                    range_outliers.append((date_str, round(range_pct * 100, 2)))

    # 2. Date continuity — 1d data only
    daily_df = data.get("1d", pd.DataFrame())
    if not daily_df.empty:
        dates = sorted(daily_df["Date"].unique())
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i - 1]).days
            if gap > 3:  # more than 3 calendar days means 4+ day gap
                date_gaps.append((
                    str(dates[i - 1])[:10],
                    str(dates[i])[:10],
                    gap,
                ))

    # 3. Timeframe alignment — flag 1d days missing ALL intraday data
    if not daily_df.empty:
        daily_dates = set(daily_df["Date"].unique())
        for date in daily_dates:
            all_empty = True
            for tf in INTRADAY_TIMEFRAMES:
                tf_df = data.get(tf, pd.DataFrame())
                if not tf_df.empty and (tf_df["Date"] == date).any():
                    all_empty = False
                    break
            if all_empty:
                missing_intraday.append(str(date)[:10])
        missing_intraday.sort()

    passed = ohlc_violations == 0 and value_outliers == 0

    lines = [
        "=== Data Validation Summary ===",
        f"OHLC violations  : {ohlc_violations}",
        f"Date gaps (4d+)  : {len(date_gaps)}",
        f"Missing intraday : {len(missing_intraday)}",
        f"Value outliers   : {value_outliers}",
        f"Range outliers   : {len(range_outliers)}",
        f"Overall          : {'PASSED' if passed else 'FAILED'}",
    ]
    summary = "\n".join(lines)
    print(summary)

    if ohlc_violations > 0 or value_outliers > 0:
        print("WARNING: Critical issues found")

    return {
        "passed": passed,
        "ohlc_violations": ohlc_violations,
        "date_gaps": date_gaps,
        "missing_intraday": missing_intraday,
        "value_outliers": value_outliers,
        "range_outliers": range_outliers,
        "summary": summary,
    }
