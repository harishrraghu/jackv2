"""
Jack v3 - 5-day paper trading simulation.
Runs Apr 7, 8, 9, 10, 13 2026 with Mar 30-Apr 6 as indicator lookback.
"""
import json
import os
import sys
import time
import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TRADE_DATES = ["2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10", "2026-04-13"]
LOOKBACK_DATES = ["2026-03-30", "2026-04-01", "2026-04-02", "2026-04-06"]
CSV_PATH = "data/banknifty_1month.csv"
OUTPUT_FILE = "sim_results/simulation_results_5d.json"


def load_candles(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    return df


def get_day_candles(df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    d = pd.Timestamp(date_str).date()
    mask = df["Datetime"].dt.date == d
    return df[mask].copy().reset_index(drop=True)


def main():
    print("\n" + "=" * 60)
    print("  JACK v3 -- 5-Day Simulation (Apr 7-13 2026)")
    print("=" * 60)

    with open("config/settings.yaml") as f:
        config = yaml.safe_load(f)

    all_candles = load_candles(CSV_PATH)
    print(f"[Sim] Loaded {len(all_candles):,} candles from {CSV_PATH}")

    # Lookback candles for indicator warmup (prior 4 days)
    lookback_df = pd.concat(
        [get_day_candles(all_candles, d) for d in LOOKBACK_DATES],
        ignore_index=True
    )
    print(f"[Sim] Lookback candles: {len(lookback_df)} rows ({LOOKBACK_DATES[0]} to {LOOKBACK_DATES[-1]})")

    # Init loop
    from engine.loop import JackMainLoop
    loop = JackMainLoop.__new__(JackMainLoop)
    loop.config_path = "config/settings.yaml"
    loop.config = config
    loop.live = False
    loop.paper_mode = True
    loop._sim_mode = False
    loop._sim_candles = None
    loop._sim_trade_date = None
    loop._trade_date = None
    loop._init_components()

    results = []
    cumulative_pnl = 0.0

    for date_str in TRADE_DATES:
        day_candles = get_day_candles(all_candles, date_str)
        if len(day_candles) < 10:
            print(f"[Sim] {date_str}: skipping (only {len(day_candles)} candles)")
            continue

        print(f"\n[Sim] ---- {date_str} ----")
        trade_date = pd.Timestamp(date_str).date()

        # Build pre-market context with AI thesis
        from brain.thesis import ThesisGenerator
        from brain.ai_client import create_ai_client

        # Compute momentum dependents from lookback
        closes = lookback_df.groupby(lookback_df["Datetime"].dt.date)["Close"].last().sort_index()
        if len(closes) >= 2:
            momentum_pct = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100
            weighted_bias = max(-1.0, min(1.0, momentum_pct / 2.0))
            bias_dir = "BULLISH" if weighted_bias > 0.15 else ("BEARISH" if weighted_bias < -0.15 else "NEUTRAL")
        else:
            weighted_bias, bias_dir, momentum_pct = 0.0, "NEUTRAL", 0.0

        dependents = {
            "weighted_bias": round(weighted_bias, 4),
            "bias_direction": bias_dir,
            "momentum_pct": round(momentum_pct, 4),
            "prior_close": round(float(closes.iloc[-1]), 2) if len(closes) else 0.0,
            "fetch_errors": [],
        }

        # AI thesis
        try:
            ai = create_ai_client(config, mode="intraday")
            thesis_gen = ThesisGenerator(ai)
            thesis = thesis_gen.generate(
                dependents=dependents,
                research={},
                recent_journal=[],
                strategy_rankings=[],
            )
            print(f"[Sim] Thesis: {thesis.get('direction')} @ {thesis.get('confidence', 0):.0%}")
        except Exception as e:
            print(f"[Sim] AI thesis failed ({e}), using momentum fallback")
            conf = min(abs(weighted_bias) * 1.5, 0.55)
            thesis = {
                "direction": bias_dir,
                "confidence": round(conf, 2),
                "reasoning": f"Momentum fallback: {momentum_pct:+.2f}%",
                "key_factors": ["price_momentum"],
                "suggested_strategy": None,
                "risk_note": "Fallback thesis",
                "expected_range_pts": 300,
                "bias_entry_after": "09:30",
            }

        pre_market_context = {"thesis": thesis, "dependents": dependents, "research": {}}

        # Run the day
        try:
            result = loop.run_simulation_day(
                trade_date=trade_date,
                day_candles_df=day_candles,
                pre_market_context=pre_market_context,
                lookback_candles_df=lookback_df,
                skip_ai_review=False,
            )
        except Exception as e:
            print(f"[Sim] ERROR on {date_str}: {e}")
            import traceback
            traceback.print_exc()
            result = {
                "date": date_str,
                "daily_pnl": 0, "cumulative_pnl": cumulative_pnl,
                "num_trades": 0, "wins": 0, "trades": [],
                "thesis_direction": thesis.get("direction", "NEUTRAL"),
                "thesis_confidence": thesis.get("confidence", 0.5),
                "open_price": 0, "close_price": 0, "day_move_pts": 0,
            }

        cumulative_pnl += result.get("daily_pnl", 0)
        result["cumulative_pnl"] = cumulative_pnl
        results.append(result)

        pnl = result.get("daily_pnl", 0)
        sign = "+" if pnl >= 0 else ""
        print(f"[Sim] {date_str} | P&L: Rs.{sign}{pnl:,.0f} | "
              f"Trades: {result.get('num_trades', 0)} (W:{result.get('wins', 0)}) | "
              f"Cumulative: Rs.{cumulative_pnl:,.0f}")

        # Brief pause to avoid rate limiting
        if date_str != TRADE_DATES[-1]:
            print("[Sim] Pausing 5s before next day...")
            time.sleep(5)

        # Update lookback with this day's candles
        lookback_df = pd.concat([lookback_df, day_candles], ignore_index=True)
        # Keep only last 4 days worth
        all_lookback_dates = sorted(lookback_df["Datetime"].dt.date.unique())
        keep_dates = all_lookback_dates[-4:]
        lookback_df = lookback_df[lookback_df["Datetime"].dt.date.isin(keep_dates)].reset_index(drop=True)

    # Save results
    os.makedirs("sim_results", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[Sim] Results saved to {OUTPUT_FILE}")

    # Summary
    total_pnl = sum(r.get("daily_pnl", 0) for r in results)
    total_trades = sum(r.get("num_trades", 0) for r in results)
    wins = sum(r.get("wins", 0) for r in results)
    print("\n" + "=" * 60)
    print(f"  5-Day Total P&L : Rs.{total_pnl:,.0f}")
    print(f"  Total Trades    : {total_trades}")
    print(f"  Win Rate        : {wins/total_trades*100:.1f}%" if total_trades else "  Win Rate        : N/A")
    print("=" * 60)


if __name__ == "__main__":
    main()
