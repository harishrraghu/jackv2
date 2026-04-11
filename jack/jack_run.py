"""
jack_run.py -- Single-day candle-by-candle simulation for the /jack skill.

Usage:
    python jack_run.py --csv path/to/data.csv [--date YYYY-MM-DD] [--tf 15m|5m|1d]

The CSV must have columns: Date, Time (or Datetime), Open, High, Low, Close, Volume
OR a combined Datetime column.

The script:
1. Loads the CSV and infers the trading date
2. Loads any available prior-day context (lookback) from data/raw/ if present
3. Runs the simulator candle-by-candle (strict no-lookahead)
4. Prints a full briefing, per-signal log, trade result, and ASCII chart
"""

import os
import sys
import json
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

# Add project root to path
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


# ---------------------------------------------------------------------------
# CSV Parsing
# ---------------------------------------------------------------------------

def load_csv(path: str) -> pd.DataFrame:
    """Load and normalize a user-provided CSV into standard OHLCV format."""
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]

    # Normalize column names
    rename = {}
    for col in df.columns:
        lc = col.lower()
        if lc in ("date", "dt"): rename[col] = "Date"
        elif lc in ("time",): rename[col] = "Time"
        elif lc in ("datetime", "timestamp", "date_time"): rename[col] = "Datetime"
        elif lc in ("open", "o"): rename[col] = "Open"
        elif lc in ("high", "h"): rename[col] = "High"
        elif lc in ("low", "l"): rename[col] = "Low"
        elif lc in ("close", "c", "ltp"): rename[col] = "Close"
        elif lc in ("volume", "vol", "v"): rename[col] = "Volume"
    df = df.rename(columns=rename)

    # Build a proper Datetime index
    if "Datetime" in df.columns:
        df["Datetime"] = pd.to_datetime(df["Datetime"], dayfirst=True)
    elif "Date" in df.columns and "Time" in df.columns:
        df["Datetime"] = pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str), dayfirst=True)
    elif "Date" in df.columns:
        df["Datetime"] = pd.to_datetime(df["Date"], dayfirst=True)
    else:
        raise ValueError("CSV must have a Date, Datetime, or Date+Time column.")

    df = df.sort_values("Datetime").reset_index(drop=True)

    for col in ("Open", "High", "Low", "Close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Volume" not in df.columns:
        df["Volume"] = 0

    df["Date"] = df["Datetime"].dt.normalize()
    df["Time"] = df["Datetime"].dt.strftime("%H:%M")

    return df


def infer_timeframe(df: pd.DataFrame) -> str:
    """Guess the timeframe from the median candle interval."""
    if len(df) < 2:
        return "unknown"
    intervals = df["Datetime"].diff().dropna()
    median_min = intervals.median().total_seconds() / 60
    if median_min <= 1.5:
        return "1m"
    elif median_min <= 5.5:
        return "5m"
    elif median_min <= 15.5:
        return "15m"
    elif median_min <= 60.5:
        return "1h"
    else:
        return "1d"


# ---------------------------------------------------------------------------
# Indicator helpers (inline -- no lookahead on intraday data)
# ---------------------------------------------------------------------------

def rolling_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def rolling_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rolling_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift()).abs(),
        (lo - cl.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def rolling_vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_vol = df["Volume"].cumsum()
    cum_tp_vol = (tp * df["Volume"]).cumsum()
    return (cum_tp_vol / cum_vol.replace(0, np.nan)).fillna(tp)


# ---------------------------------------------------------------------------
# ASCII Chart
# ---------------------------------------------------------------------------

def ascii_chart(
    df: pd.DataFrame,
    entry: dict = None,
    exit_: dict = None,
    width: int = 80,
    height: int = 20,
) -> str:
    """Render a simple ASCII price chart with entry/exit markers."""
    closes = df["Close"].dropna().tolist()
    highs = df["High"].dropna().tolist()
    lows = df["Low"].dropna().tolist()
    times = df["Time"].tolist()

    if not closes:
        return "(no price data)"

    price_min = min(lows) * 0.9995
    price_max = max(highs) * 1.0005
    price_range = price_max - price_min
    if price_range == 0:
        return "(flat price -- no chart)"

    n = len(closes)
    step = max(1, n // width)
    sampled_idx = list(range(0, n, step))

    # Build grid
    grid = [[" "] * width for _ in range(height)]

    def price_to_row(p):
        row = int((price_max - p) / price_range * (height - 1))
        return max(0, min(height - 1, row))

    # Plot close line
    for i, idx in enumerate(sampled_idx):
        if i >= width:
            break
        row = price_to_row(closes[idx])
        grid[row][i] = "."

    # Mark entry
    if entry:
        entry_time = entry.get("time")
        entry_price = entry.get("price")
        if entry_time and entry_price:
            # Find closest candle
            for i, idx in enumerate(sampled_idx):
                if i >= width:
                    break
                if times[idx] >= entry_time:
                    row = price_to_row(entry_price)
                    grid[row][i] = "E"
                    # Mark stop and target
                    sl_row = price_to_row(entry.get("sl", entry_price))
                    tgt_row = price_to_row(entry.get("target", entry_price))
                    grid[min(sl_row, height-1)][min(i+1, width-1)] = "S"
                    grid[min(tgt_row, height-1)][min(i+2, width-1)] = "T"
                    break

    # Mark exit
    if exit_:
        exit_time = exit_.get("time")
        exit_price = exit_.get("price")
        if exit_time and exit_price:
            for i, idx in enumerate(sampled_idx):
                if i >= width:
                    break
                if times[idx] >= exit_time:
                    row = price_to_row(exit_price)
                    grid[row][min(i, width-1)] = "X"
                    break

    # Build output
    lines = []
    for r, row in enumerate(grid):
        # Y-axis label every 5 rows
        if r % 5 == 0:
            label = f"{price_max - r * price_range / (height - 1):8.0f} |"
        else:
            label = "         |"
        lines.append(label + "".join(row))

    # X-axis time labels
    x_labels = " " * 10
    label_every = max(1, width // 6)
    for i in range(0, min(width, len(sampled_idx)), label_every):
        idx = sampled_idx[i]
        t = times[idx] if idx < len(times) else ""
        x_labels += t.ljust(label_every)
    lines.append("-" * 10 + "-" * width)
    lines.append(x_labels[:10 + width])

    legend = "  E=Entry  S=Stop  T=Target  X=Exit  .=Close"
    lines.append(legend)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def _print_suggestions(df: pd.DataFrame, fh_strong: bool, fh_return: float,
                        gap_type: str, global_ctx: dict, trades: list):
    """
    Print data-driven suggestions for new indicators or features
    that could have helped today's trading decision.
    """
    suggestions = []

    # 1. Option PCR / OI -- if options data is present, check premium direction
    if "Option_Close" in df.columns:
        opt_range = df["Option_Close"].max() - df["Option_Close"].min()
        opt_open = df["Option_Close"].iloc[0]
        opt_close = df["Option_Close"].iloc[-1]
        if opt_range > opt_open * 0.3:
            suggestions.append(
                "[INDICATOR] High option premium volatility today (range > 30% of open). "
                "Suggest: add IV_Percentile indicator -- when IV > 70th percentile, "
                "fade breakouts (premium expensive, mean reversion more likely). "
                "When IV < 30th percentile, favour directional strategies."
            )

    # 2. No first-hour signal but market moved after 11:00
    if not fh_strong and not trades:
        late_move = abs(df["Close"].iloc[-1] - df["Close"].iloc[len(df)//2]) / df["Close"].iloc[0] * 100
        if late_move > 0.4:
            suggestions.append(
                f"[FEATURE] FH was weak ({fh_return:+.2f}%) but market moved {late_move:+.2f}% "
                "after 12:00 -- missed opportunity. Suggest: add AfternoonBreakout strategy "
                "that triggers if price breaks ORB high/low after 12:30 with volume confirmation. "
                "This catches days where morning consolidation breaks into afternoon trend."
            )

    # 3. Global context signal
    sp_chg = global_ctx.get("sp500_pct_chg")
    vix = global_ctx.get("india_vix")
    if sp_chg is not None and abs(sp_chg) > 1.0 and not trades:
        direction = "bullish" if sp_chg > 0 else "bearish"
        suggestions.append(
            f"[FEATURE] S&P moved {sp_chg:+.2f}% overnight ({direction}) but no trade taken. "
            "Suggest: add GlobalCueBias filter -- when |S&P change| > 1%, apply 1.2x multiplier "
            "to the aligned direction at open. This would have boosted signal score for gap setups."
        )
    if vix is not None and vix > 20 and not trades:
        suggestions.append(
            f"[INDICATOR] India VIX was {vix:.1f} (elevated fear). "
            "Suggest: add VIX_Regime to the filter stack -- VIX > 20 should reduce position size "
            "to 0.7x and widen stop multiplier from 0.5 to 0.8 ATR. High VIX means wider ranges "
            "and higher false breakout probability."
        )

    # 4. Price structure suggestion
    closes = df["Close"].dropna()
    if len(closes) > 30:
        # Check if intraday showed a clear VWAP bounce pattern
        vwap_series = rolling_vwap(df)
        vwap_mid = vwap_series.iloc[len(vwap_series)//2]
        price_mid = closes.iloc[len(closes)//2]
        vwap_dev = abs(price_mid - vwap_mid) / vwap_mid * 100
        if vwap_dev > 0.25 and not trades:
            suggestions.append(
                f"[INDICATOR] Price deviated {vwap_dev:.2f}% from VWAP mid-session. "
                "The VWAPReversion strategy is currently disabled due to broken R:R. "
                "Suggest fix: set stop = entry +/- 0.25% (tight), target = VWAP + (entry-VWAP)*0.5 "
                "to achieve 1:1.5 R:R. Then re-enable with RSI 70/30 thresholds."
            )

    # 5. Candle pattern
    if len(df) > 5:
        last5 = df["Close"].tail(5)
        if last5.is_monotonic_increasing or last5.is_monotonic_decreasing:
            direction = "bullish" if last5.is_monotonic_increasing else "bearish"
            suggestions.append(
                f"[INDICATOR] Last 5 candles are monotonically {direction} -- strong momentum. "
                "Suggest: add MomentumPersistence indicator that flags 4+ consecutive "
                "same-direction 1m candles as a momentum signal, boosting FH Verdict score by 1.1x "
                "when it aligns with first-hour direction."
            )

    # 6. Always suggest PCR if options data present
    if "Option_Close" in df.columns and not any("PCR" in s for s in suggestions):
        suggestions.append(
            "[INDICATOR] Since you have options data: add Put/Call Ratio (PCR) as a morning "
            "filter. PCR > 1.2 = market hedged for downside (contrarian bullish). "
            "PCR < 0.7 = complacent (contrarian bearish). This is one of the strongest "
            "intraday directional filters used by professional Bank Nifty/Nifty traders."
        )

    if not suggestions:
        suggestions.append(
            "[OK] No specific gaps identified for today. System had sufficient context. "
            "Continue building the journal -- run brain.retrospective --dump after 100+ days "
            "for the AI to identify regime-specific patterns."
        )

    for i, s in enumerate(suggestions, 1):
        print(f"  {i}. {s}")
        print()


def run(csv_path: str, date_str: str = None, verbose: bool = True):
    """Load CSV, simulate candle-by-candle, print full briefing + chart."""

    print(f"\n{'='*65}")
    print(f"  JACK -- Single Day Simulation")
    print(f"  CSV: {os.path.basename(csv_path)}")
    print(f"{'='*65}\n")

    # Load CSV
    df = load_csv(csv_path)
    tf = infer_timeframe(df)
    print(f"Loaded {len(df)} candles | Timeframe: {tf}")

    # Filter to target date if given
    if date_str:
        target_date = pd.Timestamp(date_str).normalize()
        df = df[df["Date"] == target_date].copy()
        if df.empty:
            print(f"ERROR: No data for {date_str} in the CSV.")
            return
    else:
        # Use all data (assumes single-day CSV)
        target_date = df["Date"].iloc[0]
        date_str = str(target_date.date())

    print(f"Trading date: {date_str} ({pd.Timestamp(date_str).day_name()})")
    print(f"Candles: {len(df)} ({df['Time'].iloc[0]} -> {df['Time'].iloc[-1]})")

    # Compute rolling indicators on candles seen so far (no lookahead)
    df = df.reset_index(drop=True)
    df["RSI"] = rolling_rsi(df["Close"], 14)
    df["EMA9"] = rolling_ema(df["Close"], 9)
    df["EMA21"] = rolling_ema(df["Close"], 21)
    df["ATR"] = rolling_atr(df, 14)
    df["VWAP"] = rolling_vwap(df)

    # Opening range (first 15-minute high/low)
    first_candle = df.iloc[0]
    orb_high = first_candle["High"]
    orb_low = first_candle["Low"]
    open_price = first_candle["Open"]

    # Prior close (first open approximation or from data)
    prior_close = open_price  # best guess if no prior day data
    gap_pct = 0.0

    # Detect instrument from price level
    # Bank Nifty spot ~ 40000-55000, Nifty 50 ~ 22000-27000
    instrument = "BANKNIFTY" if open_price > 30000 else "NIFTY50"

    # Try to load prior day close from the same CSV (previous date in the file)
    try:
        full_df_all = load_csv(csv_path)
        prev_dates = sorted(full_df_all[full_df_all["Date"] < pd.Timestamp(date_str).normalize()]["Date"].unique())
        if prev_dates:
            prev_day_rows = full_df_all[full_df_all["Date"] == prev_dates[-1]]
            prior_close = float(prev_day_rows["Close"].iloc[-1])
            gap_pct = (open_price - prior_close) / prior_close * 100
    except Exception:
        pass

    # If still no prior close from CSV, try raw data (only if instrument matches)
    global_ctx = {}
    try:
        from data.global_data import load_global_data, get_premarket_context
        t_date = pd.Timestamp(date_str)
        global_data = load_global_data()
        global_ctx = get_premarket_context(t_date, global_data)

        if instrument == "BANKNIFTY" and prior_close == open_price:
            from data.loader import load_all_timeframes
            raw_dir = os.path.join(_HERE, "data", "raw")
            raw_data = load_all_timeframes(raw_dir)
            daily = raw_data.get("1d", pd.DataFrame())
            prior_rows = daily[daily["Date"] < t_date].tail(1)
            if not prior_rows.empty:
                prior_close = float(prior_rows.iloc[-1]["Close"])
                gap_pct = (open_price - prior_close) / prior_close * 100
    except Exception:
        pass

    gap_type = "flat"
    if gap_pct > 0.75: gap_type = "large_up"
    elif gap_pct > 0.1: gap_type = "small_up"
    elif gap_pct < -0.75: gap_type = "large_down"
    elif gap_pct < -0.1: gap_type = "small_down"

    # First hour stats (09:15-10:15)
    fh_candles = df[df["Time"] <= "10:15"]
    fh_high = fh_candles["High"].max() if not fh_candles.empty else open_price
    fh_low = fh_candles["Low"].min() if not fh_candles.empty else open_price
    fh_close = fh_candles["Close"].iloc[-1] if not fh_candles.empty else open_price
    fh_return = (fh_close - open_price) / open_price * 100
    fh_direction = 1 if fh_return > 0 else -1
    fh_strong = abs(fh_return) >= 0.3

    # Print morning briefing
    print(f"\n{'-'*65}")
    print("  MORNING BRIEFING")
    print(f"{'-'*65}")
    print(f"  Open:          {open_price:,.2f}")
    print(f"  Prior close:   {prior_close:,.2f}")
    print(f"  Gap:           {gap_pct:+.2f}% ({gap_type})")

    if global_ctx:
        print(f"\n  Global context (prev day close):")
        if global_ctx.get("sp500_pct_chg") is not None:
            print(f"    S&P 500:     {global_ctx['sp500_pct_chg']:+.2f}%  [{global_ctx.get('us_sentiment','?')}]")
        if global_ctx.get("india_vix") is not None:
            print(f"    India VIX:   {global_ctx['india_vix']:.1f}  [{global_ctx.get('vix_regime','?')}]")
        if global_ctx.get("crude_pct_chg") is not None:
            print(f"    Crude Oil:   {global_ctx['crude_pct_chg']:+.2f}%")
        if global_ctx.get("usdinr") is not None:
            print(f"    USD/INR:     {global_ctx['usdinr']:.2f}")

    print(f"\n  First Hour ({fh_candles['Time'].iloc[0] if not fh_candles.empty else 'N/A'} - 10:15):")
    print(f"    Return:      {fh_return:+.2f}%  ({'STRONG' if fh_strong else 'WEAK'} | {'BULLISH' if fh_direction > 0 else 'BEARISH'})")
    print(f"    H/L:         {fh_high:,.0f} / {fh_low:,.0f}")

    # Run candle-by-candle simulation
    print(f"\n{'-'*65}")
    print("  CANDLE-BY-CANDLE SIGNAL LOG")
    print(f"{'-'*65}")

    position = None
    trades = []
    entry_info = None
    exit_info = None

    for i, row in df.iterrows():
        t = row["Time"]
        price = row["Close"]
        high = row["High"]
        low = row["Low"]
        rsi = row["RSI"]
        atr = row["ATR"]
        vwap = row["VWAP"]
        ema9 = row["EMA9"]
        ema21 = row["EMA21"]

        # Check exit if position open
        if position:
            exit_reason = None
            exit_price = None
            if low <= position["stop_loss"]:
                exit_reason = "STOP HIT"
                exit_price = position["stop_loss"]
            elif high >= position["target"] and position["direction"] == "LONG":
                exit_reason = "TARGET HIT"
                exit_price = position["target"]
            elif price <= position["target"] and position["direction"] == "SHORT":
                exit_reason = "TARGET HIT"
                exit_price = position["target"]
            elif t >= "15:15":
                exit_reason = "TIME EXIT"
                exit_price = price

            if exit_reason:
                pnl = (exit_price - position["entry_price"]) * (1 if position["direction"] == "LONG" else -1)
                pnl_rs = pnl * position["qty"] * 15  # lot size 15
                print(f"  {t}  EXIT  {exit_reason:12s}  @ {exit_price:,.0f}  P&L: Rs {pnl_rs:+,.0f}")
                trades.append({**position, "exit_time": t, "exit_price": exit_price,
                                "exit_reason": exit_reason, "pnl": pnl_rs})
                exit_info = {"time": t, "price": exit_price}
                position = None

        # Check entry signals (no lookahead -- only use data up to candle i)
        if not position and i > 0:
            signal = None
            reason = None

            # FirstHourVerdict: entry 10:15-11:15
            if "10:15" <= t <= "11:15" and fh_strong:
                direction = "LONG" if fh_direction > 0 else "SHORT"
                if not pd.isna(atr) and atr > 0:
                    stop = price - 0.5 * atr if direction == "LONG" else price + 0.5 * atr
                    target = price + 2.0 * atr if direction == "LONG" else price - 2.0 * atr
                    signal = {"strategy": "first_hour_verdict", "direction": direction,
                               "entry_price": price, "stop_loss": stop, "target": target,
                               "score": 0.72, "reason": f"FH {fh_return:+.2f}% | ATR={atr:.0f}"}

            # GapFill: entry 09:30-10:15 on small gap down
            if not signal and gap_type == "small_down" and "09:30" <= t <= "10:15":
                if not pd.isna(rsi) and rsi < 50:
                    stop = prior_close - (prior_close - open_price) * 0.5
                    target = prior_close
                    signal = {"strategy": "gap_fill", "direction": "LONG",
                               "entry_price": price, "stop_loss": stop, "target": target,
                               "score": 0.55, "reason": f"Gap fill long | Gap {gap_pct:+.2f}%"}

            if signal:
                qty = max(1, int(100000 / (abs(signal["entry_price"] - signal["stop_loss"]) * 15)))
                qty = min(qty, 30)
                signal["qty"] = qty
                position = signal
                entry_info = {"time": t, "price": signal["entry_price"],
                               "sl": signal["stop_loss"], "target": signal["target"]}
                print(f"  {t}  ENTRY {signal['strategy']:20s} {signal['direction']:5s} "
                      f"@ {price:,.0f}  SL={signal['stop_loss']:,.0f}  TGT={signal['target']:,.0f}  "
                      f"Score={signal['score']:.2f}  Qty={qty}")
            elif t in ("10:15", "11:15", "12:15", "13:15", "14:15"):
                # Periodic status update
                vwap_dev = (price - vwap) / vwap * 100 if not pd.isna(vwap) else 0
                ema_cross = ">" if (not pd.isna(ema9) and not pd.isna(ema21) and ema9 > ema21) else "<"
                rsi_str = f"{rsi:.0f}" if not pd.isna(rsi) else "N/A"
                print(f"  {t}  --- price={price:,.0f}  RSI={rsi_str}  VWAP_dev={vwap_dev:+.2f}%  "
                      f"EMA9{ema_cross}EMA21  No signal")

    # Force close if still open
    if position:
        close_price = df["Close"].iloc[-1]
        pnl = (close_price - position["entry_price"]) * (1 if position["direction"] == "LONG" else -1)
        pnl_rs = pnl * position["qty"] * 15
        print(f"  15:30  EXIT  EOD           @ {close_price:,.0f}  P&L: Rs {pnl_rs:+,.0f}")
        trades.append({**position, "exit_time": "15:30", "exit_price": close_price,
                        "exit_reason": "EOD", "pnl": pnl_rs})
        exit_info = {"time": "15:30", "price": close_price}

    # Summary
    print(f"\n{'-'*65}")
    print("  TRADE SUMMARY")
    print(f"{'-'*65}")
    if not trades:
        print("  No trades taken today.")
        if fh_strong:
            print(f"  FH was {'BULLISH' if fh_direction > 0 else 'BEARISH'} {fh_return:+.2f}% but no confirmed entry in window.")
        else:
            print(f"  FH move {fh_return:+.2f}% was below 0.3% threshold -- system skipped.")
    else:
        total_pnl = sum(t["pnl"] for t in trades)
        for t in trades:
            print(f"  {t['strategy']:20s} | {t['direction']:5s} | Entry:{t['entry_price']:,.0f} "
                  f"-> Exit:{t['exit_price']:,.0f} | {t['exit_reason']:12s} | P&L: Rs {t['pnl']:+,.0f}")
        print(f"\n  Total P&L: Rs {total_pnl:+,.0f}")

    # Print chart
    print(f"\n{'-'*65}")
    print("  PRICE CHART")
    print(f"{'-'*65}")
    chart = ascii_chart(df, entry=entry_info, exit_=exit_info)
    print(chart)

    # Option context (if file has Option_Close column)
    if "Option_Close" in df.columns:
        print(f"\n{'-'*65}")
        print("  OPTIONS CONTEXT (from CSV)")
        print(f"{'-'*65}")
        opt_open = df["Option_Close"].iloc[0]
        opt_close = df["Option_Close"].iloc[-1]
        opt_high = df["Option_High"].max() if "Option_High" in df.columns else float("nan")
        opt_low = df["Option_Low"].min() if "Option_Low" in df.columns else float("nan")
        opt_chg = ((opt_close - opt_open) / opt_open * 100) if opt_open > 0 else 0
        print(f"  Option premium: Open={opt_open:.2f}  High={opt_high:.2f}  "
              f"Low={opt_low:.2f}  Close={opt_close:.2f}  Change={opt_chg:+.1f}%")
        print(f"  NOTE: Strategies run on SPOT price. Option data is reference only.")
        print(f"  For live trading: size by premium, not by spot ATR.")

    # AI Suggestion block
    print(f"\n{'-'*65}")
    print("  JACK SUGGESTS")
    print(f"{'-'*65}")
    _print_suggestions(df, fh_strong, fh_return, gap_type, global_ctx, trades)

    print(f"\n{'='*65}\n")

    return {
        "date": date_str,
        "trades": trades,
        "briefing": {
            "gap_pct": gap_pct,
            "gap_type": gap_type,
            "fh_return": fh_return,
            "fh_strong": fh_strong,
            "global": global_ctx,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jack single-day candle-by-candle simulation")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: all rows)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    run(args.csv, date_str=args.date, verbose=not args.quiet)
