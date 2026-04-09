"""
Simulation Engine — the heart of Jack.

Ties together data loading, indicators, strategies, filters, risk management,
state machine, and journal logging into a deterministic day-by-day simulation.

ZERO LLM calls. Pure deterministic Python.
"""

import os
import sys
import math
from typing import Optional

import pandas as pd
import numpy as np
import yaml

from data.loader import load_all_timeframes, get_daily_iterator, get_lookback
from data.splits import DataSplits, validate_no_leakage
from indicators.registry import IndicatorRegistry
from engine.risk import RiskManager
from engine.state_machine import StateMachine
from engine.scorer import StrategyScorer
from engine.filters import run_filter_stack
from journal.logger import JournalLogger

# Import strategies
from strategies.first_hour_verdict import FirstHourVerdict
from strategies.gap_fill import GapFill
from strategies.streak_fade import StreakFade
from strategies.bb_squeeze import BBSqueezeBreakout
from strategies.gap_up_fade import GapUpFade

# Import single-day indicator functions
from indicators.orb import compute_single_day as orb_single_day
from indicators.first_hour import compute_single_day as fh_single_day


class Simulator:
    """
    Main simulation engine for Jack backtesting system.

    Runs a deterministic day-by-day simulation with 15-minute time steps.
    Handles indicator computation, strategy evaluation, risk management,
    and trade execution.
    """

    def __init__(self, config_path: str = "config/settings.yaml"):
        """
        Initialize the simulator.

        Args:
            config_path: Path to the configuration YAML file.
        """
        # Resolve config path
        if not os.path.isabs(config_path):
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            self.base_dir = os.path.dirname(self.base_dir)  # up from engine/
            config_path = os.path.join(self.base_dir, config_path)
        else:
            self.base_dir = os.path.dirname(os.path.dirname(config_path))

        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.config_path = config_path

        # Initialize components
        self.splits = DataSplits(config_path)
        self.indicator_registry = IndicatorRegistry(
            os.path.join(self.base_dir, "indicators")
        )
        self.risk_manager = RiskManager(config_path=config_path)
        self.state_machine = StateMachine()

        # Initialize strategies
        self.strategies = {
            "first_hour_verdict": FirstHourVerdict(),
            "gap_fill": GapFill(),
            "streak_fade": StreakFade(),
            "bb_squeeze": BBSqueezeBreakout(),
            "gap_up_fade": GapUpFade(),
        }

        self.scorer = StrategyScorer(self.strategies)
        self.journal = JournalLogger(
            output_dir=os.path.join(self.base_dir, "journal", "logs")
        )

        # Validate all strategy params
        for strat in self.strategies.values():
            strat.validate_params()

    def run(self, split: str = "train", verbose: bool = True) -> dict:
        """
        Run simulation on the specified data split.

        Args:
            split: "train", "test", or "holdout".
            verbose: Print progress and trade details.

        Returns:
            Dict with comprehensive simulation results.
        """
        if verbose:
            print(f"\n{'='*60}")
            print(f"  JACK SIMULATION — {split.upper()} SPLIT")
            print(f"{'='*60}")

        # Load data
        data_path = os.path.join(self.base_dir, self.config["data"]["base_path"])
        if verbose:
            print(f"\nLoading data from {data_path}...")
        data = load_all_timeframes(data_path)

        # Get date ranges
        measure_start, measure_end = self.splits.get_measurement_range(split)
        accessible_start, accessible_end = self.splits.get_accessible_range(split)

        if verbose:
            print(f"\nAccessible data: {accessible_start} → {accessible_end}")
            print(f"Measurement period: {measure_start} → {measure_end}")

        # Pre-compute daily indicators on accessible data
        daily = data.get("1d", pd.DataFrame())
        if daily.empty:
            print("ERROR: No daily data available.")
            return {"error": "no_daily_data"}

        # Filter to accessible range for indicator computation
        acc_start_ts = pd.Timestamp(accessible_start)
        acc_end_ts = pd.Timestamp(accessible_end)
        daily_accessible = daily[
            (daily["Date"] >= acc_start_ts) & (daily["Date"] <= acc_end_ts)
        ].copy()

        if verbose:
            print(f"Computing indicators on {len(daily_accessible)} daily candles...")

        # Compute daily indicators
        daily_with_indicators = self._compute_daily_indicators(daily_accessible)

        # Reset risk manager
        self.risk_manager = RiskManager(config_path=self.config_path)

        # Initialize tracking
        trade_log = []
        day_logs = []
        equity_curve = [(measure_start, self.risk_manager.current_capital)]
        total_days = 0
        no_trade_days = 0

        # Get daily iterator for measurement period
        if verbose:
            print(f"\nSimulating {measure_start} → {measure_end}...\n")

        for day_data in get_daily_iterator(data, measure_start, measure_end):
            total_days += 1
            date = day_data["date"]
            self.risk_manager.reset_daily()
            self.scorer.clear_log()

            # Get lookback
            lookback = get_lookback(data, date, n_days=60)

            # Validate no data leakage
            try:
                lookback_dates = []
                for tf, df in lookback.items():
                    if not df.empty and "Date" in df.columns:
                        lookback_dates.extend(df["Date"].tolist())
                if lookback_dates:
                    validate_no_leakage(split, lookback_dates, splits=self.splits)
            except Exception as e:
                if verbose:
                    print(f"  ⚠ Data leakage check: {e}")
                continue

            # Get today's indicator values from pre-computed data
            today_indicators = self._get_today_indicators(
                daily_with_indicators, date, lookback
            )

            # Compute intraday indicators
            orb_data = orb_single_day(day_data.get("15m", pd.DataFrame()))
            fh_data = fh_single_day(day_data.get("1h", pd.DataFrame()))

            # Build morning briefing
            briefing = self._build_briefing(
                date, today_indicators, orb_data, fh_data, lookback
            )

            # Run filter stack
            filters = run_filter_stack(
                date,
                lookback_daily={
                    "Bull_Streak": today_indicators.get("Bull_Streak", 0),
                    "Bear_Streak": today_indicators.get("Bear_Streak", 0),
                    "avg_ATR_60d": today_indicators.get("avg_ATR_60d", None),
                },
                indicators={
                    "RSI": today_indicators.get("RSI"),
                    "hourly_RSI": None,
                    "ATR": today_indicators.get("ATR"),
                    "Regime": today_indicators.get("Regime", "normal"),
                },
            )
            briefing["filters"] = filters

            # Simulate intraday
            day_trades = self._simulate_intraday(
                day_data, briefing, date, today_indicators,
                orb_data, fh_data, filters, verbose,
            )

            trade_log.extend(day_trades)

            if not day_trades:
                no_trade_days += 1

            # Log the day
            capital_state = self.risk_manager.get_state()
            equity_curve.append((
                date.strftime("%Y-%m-%d") if hasattr(date, 'strftime') else str(date),
                self.risk_manager.current_capital,
            ))

            try:
                self.journal.log_day(
                    date=date,
                    briefing=briefing,
                    trade_events=day_trades,
                    decision_log=self.scorer.get_decision_log(),
                    capital_state=capital_state,
                )
            except Exception as e:
                print(f"  [WARN] Journal write failed: {e}", file=sys.stderr)

            # Progress
            if verbose and total_days % 50 == 0:
                cap = self.risk_manager.current_capital
                dd = self.risk_manager.get_drawdown()
                print(
                    f"  Day {total_days}: {date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else date} | "
                    f"Capital: ₹{cap:,.0f} | Trades: {len(trade_log)} | "
                    f"DD: {dd['current_drawdown_pct']:.2f}%"
                )

        # Compute final results
        results = self._compute_results(
            trade_log, equity_curve, total_days, no_trade_days,
            measure_start, measure_end,
        )

        # Log summary
        try:
            self.journal.log_summary(split, results)
        except Exception as e:
            print(f"  [WARN] Summary write failed: {e}", file=sys.stderr)

        return results

    def run_single_day(self, day_data: dict, lookback: dict, verbose: bool = False, briefing_only: bool = False) -> dict:
        """
        Run simulation for a single trading day.
        Designed for live/paper trading where we only have today's data and past lookback.
        
        Args:
            day_data: Dict of DataFrames for the current day ("date", "daily", "15m", etc).
            lookback: Dict of historical data before today.
            verbose: Print details.
            
        Returns:
            Dict containing the briefing, trades, and end-of-day capital state.
        """
        date = day_data["date"]
        self.risk_manager.reset_daily()
        self.scorer.clear_log()

        # Combine lookback daily and today's daily to compute indicators correctly
        lb_daily = lookback.get("1d", pd.DataFrame())
        today_daily = day_data.get("daily", pd.DataFrame())
        
        if not lb_daily.empty and not today_daily.empty:
            combined_daily = pd.concat([lb_daily, today_daily], ignore_index=True)
            combined_idx = len(combined_daily) - 1 # Today is the last row
        elif not today_daily.empty:
            combined_daily = today_daily
            combined_idx = 0
        else:
            return {"error": "no_daily_data"}

        # Compute daily indicators
        daily_with_indicators = self._compute_daily_indicators(combined_daily)
        
        # Get today's indicator values (the last row)
        today_indicators = self._get_today_indicators(daily_with_indicators, date, lookback)

        # Compute intraday indicators
        orb_data = orb_single_day(day_data.get("15m", pd.DataFrame()))
        fh_data = fh_single_day(day_data.get("1h", pd.DataFrame()))

        # Build morning briefing
        briefing = self._build_briefing(
            date, today_indicators, orb_data, fh_data, lookback
        )

        # Run filter stack
        filters = run_filter_stack(
            date,
            lookback_daily={
                "Bull_Streak": today_indicators.get("Bull_Streak", 0),
                "Bear_Streak": today_indicators.get("Bear_Streak", 0),
                "avg_ATR_60d": today_indicators.get("avg_ATR_60d", None),
            },
            indicators={
                "RSI": today_indicators.get("RSI"),
                "hourly_RSI": None, # Will be computed locally if needed
                "ATR": today_indicators.get("ATR"),
                "Regime": today_indicators.get("Regime", "normal"),
            },
        )
        briefing["filters"] = filters
        
        if briefing_only:
            return {"date": date, "briefing": briefing}

        # Simulate intraday
        day_trades = self._simulate_intraday(
            day_data, briefing, date, today_indicators,
            orb_data, fh_data, filters, verbose,
        )

        capital_state = self.risk_manager.get_state()

        try:
            self.journal.log_day(
                date=date,
                briefing=briefing,
                trade_events=day_trades,
                decision_log=self.scorer.get_decision_log(),
                capital_state=capital_state,
            )
        except Exception as e:
            print(f"  [WARN] Journal write failed: {e}", file=sys.stderr)

        return {
            "date": date,
            "briefing": briefing,
            "trades": day_trades,
            "decision_log": self.scorer.get_decision_log(),
            "capital_state": capital_state,
            "daily_pnl": self.risk_manager.daily_pnl
        }

    def _compute_daily_indicators(self, daily: pd.DataFrame) -> pd.DataFrame:
        """Pre-compute all daily indicators."""
        df = daily.copy()

        # Core indicators
        try:
            df = self.indicator_registry.compute("ema", df, period=9)
            df = self.indicator_registry.compute("ema", df, period=21)
            df = self.indicator_registry.compute("sma", df, period=20)
            df = self.indicator_registry.compute("rsi", df)
            df = self.indicator_registry.compute("atr", df)
            df = self.indicator_registry.compute("macd", df)
            df = self.indicator_registry.compute("bbands", df)
            df = self.indicator_registry.compute("streaks", df)
            df = self.indicator_registry.compute("gap", df)
            df = self.indicator_registry.compute("pivots", df)
            df = self.indicator_registry.compute("adr", df)
            df = self.indicator_registry.compute("adx", df)
        except Exception as e:
            print(f"  [WARN] Indicator computation error: {e}")

        # Regime requires ATR_Pct, ADX, BB_Width
        try:
            if all(col in df.columns for col in ["ATR_Pct", "ADX", "BB_Width"]):
                df = self.indicator_registry.compute("regime", df)
        except Exception as e:
            print(f"  [WARN] Regime computation error: {e}")

        return df

    def _get_today_indicators(
        self, daily_indicators: pd.DataFrame, date: pd.Timestamp,
        lookback: dict,
    ) -> dict:
        """Extract today's indicator values from pre-computed daily data."""
        result = {}

        if daily_indicators.empty:
            return result

        today_row = daily_indicators[daily_indicators["Date"] == date]
        if today_row.empty:
            return result

        row = today_row.iloc[0]

        # Extract all indicator columns
        for col in daily_indicators.columns:
            if col not in ("Instrument", "Date", "Time"):
                val = row.get(col)
                if pd.notna(val):
                    result[col] = val

        # Compute average ATR over lookback for 60-day comparison
        lookback_daily = lookback.get("1d", pd.DataFrame())
        if not lookback_daily.empty and "High" in lookback_daily.columns:
            try:
                lb = self.indicator_registry.compute("atr", lookback_daily)
                if "ATR" in lb.columns:
                    result["avg_ATR_60d"] = lb["ATR"].dropna().mean()
            except Exception:
                pass

        return result

    def _build_briefing(
        self, date, indicators, orb_data, fh_data, lookback,
    ) -> dict:
        """Build the morning briefing dict."""
        return {
            "date": date,
            "day_of_week": date.day_name() if hasattr(date, 'day_name') else "",
            "gap": {
                "Gap_Pts": indicators.get("Gap_Pts"),
                "Gap_Pct": indicators.get("Gap_Pct"),
                "Gap_Type": indicators.get("Gap_Type", "flat"),
            },
            "orb": orb_data,
            "first_hour": fh_data,
            "daily_indicators": {
                "RSI": indicators.get("RSI"),
                "ATR": indicators.get("ATR"),
                "ATR_Pct": indicators.get("ATR_Pct"),
                "EMA_9": indicators.get("EMA_9"),
                "EMA_21": indicators.get("EMA_21"),
                "SMA_20": indicators.get("SMA_20"),
                "MACD": indicators.get("MACD"),
                "ADX": indicators.get("ADX"),
            },
            "regime": indicators.get("Regime", "normal"),
            "streak": {
                "bull": indicators.get("Bull_Streak", 0),
                "bear": indicators.get("Bear_Streak", 0),
            },
            "capital": self.risk_manager.current_capital,
            "drawdown": self.risk_manager.get_drawdown(),
        }

    def _simulate_intraday(
        self, day_data, briefing, date, indicators,
        orb_data, fh_data, filters, verbose,
    ) -> list[dict]:
        """
        Walk through one day in 15-minute steps.

        Returns list of trade result dicts.
        """
        trades_today = []

        # Generate 15-min time steps
        times = self._generate_time_steps()
        day_15m = day_data.get("15m", pd.DataFrame())

        # Track intraday high/low
        day_high = indicators.get("Open", 0)
        day_low = indicators.get("Open", float('inf') if indicators.get("Open", 0) > 0 else 0)

        for time_str in times:
            # Get current price from 15m data
            current_price = self._get_price_at_time(day_15m, time_str)
            if current_price <= 0:
                current_price = indicators.get("Close", 0)
                if current_price <= 0:
                    continue

            # Update intraday high/low
            candle = self._get_candle_at_time(day_15m, time_str)
            if candle is not None:
                day_high = max(day_high, candle.get("High", current_price))
                day_low = min(day_low, candle.get("Low", current_price))

            # Check if we must exit all (closing phase)
            if self.state_machine.must_exit_all(time_str):
                if self.risk_manager.open_position is not None:
                    from strategies.base import ExitSignal
                    exit_sig = ExitSignal(
                        should_exit=True,
                        exit_price=current_price,
                        reason="time_exit",
                    )
                    result = self.risk_manager.execute_exit(exit_sig, current_price)
                    result["exit_time"] = time_str
                    result["exit_date"] = str(date)
                    trades_today.append(result)
                    if verbose:
                        pnl = result["net_pnl"]
                        color = "\033[92m" if pnl >= 0 else "\033[91m"
                        print(
                            f"  {date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else date} "
                            f"{time_str} EXIT [{result['strategy']}] "
                            f"{result['direction']} "
                            f"@ {result['exit_price']:.1f} "
                            f"→ {color}₹{pnl:+,.0f}\033[0m "
                            f"({result['exit_reason']})"
                        )
                continue

            # Check exits for open position
            if self.risk_manager.open_position is not None:
                pos = self.risk_manager.open_position
                strategy = self.strategies.get(pos["strategy"])

                # Check stops via candle low/high
                if candle is not None:
                    stop_exit = self._check_stops_intraday(pos, candle)
                    if stop_exit is not None and stop_exit.should_exit:
                        result = self.risk_manager.execute_exit(stop_exit, current_price)
                        result["exit_time"] = time_str
                        result["exit_date"] = str(date)
                        trades_today.append(result)
                        if verbose:
                            pnl = result["net_pnl"]
                            color = "\033[92m" if pnl >= 0 else "\033[91m"
                            print(
                                f"  {date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else date} "
                                f"{time_str} EXIT [{result['strategy']}] "
                                f"{result['direction']} "
                                f"@ {result['exit_price']:.1f} "
                                f"→ {color}₹{pnl:+,.0f}\033[0m "
                                f"({result['exit_reason']})"
                            )
                        continue

                # Strategy-level exit check
                if strategy is not None:
                    exit_sig = strategy.check_exit(pos, day_data, time_str, current_price)
                    if exit_sig.should_exit:
                        result = self.risk_manager.execute_exit(exit_sig, current_price)
                        result["exit_time"] = time_str
                        result["exit_date"] = str(date)
                        trades_today.append(result)
                        if verbose:
                            pnl = result["net_pnl"]
                            color = "\033[92m" if pnl >= 0 else "\033[91m"
                            print(
                                f"  {date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else date} "
                                f"{time_str} EXIT [{result['strategy']}] "
                                f"{result['direction']} "
                                f"@ {result['exit_price']:.1f} "
                                f"→ {color}₹{pnl:+,.0f}\033[0m "
                                f"({result['exit_reason']})"
                            )
                        continue

            # Check entries (only if no position open)
            if self.risk_manager.open_position is None:
                eligible = self.state_machine.get_eligible_strategies(time_str)
                if not eligible:
                    continue

                # Build indicator context for strategies
                strat_indicators = {
                    "current_price": current_price,
                    "daily": {
                        "ATR": indicators.get("ATR"),
                        "RSI": indicators.get("RSI"),
                        "EMA_9": indicators.get("EMA_9"),
                        "EMA_21": indicators.get("EMA_21"),
                        "SMA_20": indicators.get("SMA_20"),
                        "ADX": indicators.get("ADX"),
                    },
                    "gap": {
                        "Gap_Pct": indicators.get("Gap_Pct", 0),
                        "Gap_Type": indicators.get("Gap_Type", "flat"),
                        "prev_close": indicators.get("prev_close",
                                                      indicators.get("Close", 0) - indicators.get("Gap_Pts", 0)
                                                      if indicators.get("Gap_Pts") else 0),
                    },
                    "orb": orb_data,
                    "first_hour": fh_data,
                    "day_high": day_high,
                    "lookback_daily": {
                        "Bull_Streak": indicators.get("Bull_Streak", 0),
                        "Bear_Streak": indicators.get("Bear_Streak", 0),
                        "streak_high": day_high,
                        "streak_low": day_low,
                    },
                    "intraday_15m": {
                        "BB_Width": None,
                        "BB_Upper": None,
                        "BB_Lower": None,
                        "BB_Width_history": [],
                    },
                }

                # Compute 15m BB data for BB squeeze strategy
                if "bb_squeeze" in eligible and not day_15m.empty:
                    try:
                        bb_15m = self.indicator_registry.compute("bbands", day_15m, period=20)
                        current_bb = bb_15m[bb_15m["Time"] <= time_str]
                        if not current_bb.empty:
                            last = current_bb.iloc[-1]
                            strat_indicators["intraday_15m"].update({
                                "BB_Width": last.get("BB_Width"),
                                "BB_Upper": last.get("BB_Upper"),
                                "BB_Lower": last.get("BB_Lower"),
                                "BB_Width_history": current_bb["BB_Width"].dropna().tolist(),
                            })
                    except Exception:
                        pass

                # Collect signals from eligible strategies
                signals = []
                for strat_name in eligible:
                    strategy = self.strategies.get(strat_name)
                    if strategy is None:
                        continue

                    try:
                        signal = strategy.check_entry(
                            day_data=day_data,
                            lookback={},
                            indicators=strat_indicators,
                            current_time=time_str,
                            filters=filters,
                        )
                        if signal is not None:
                            signals.append(signal)
                    except Exception as e:
                        if verbose:
                            print(f"  [WARN] {strat_name} entry check failed: {e}")

                if not signals:
                    continue

                # Score and select
                selected = self.scorer.select_trade(signals, filters)
                if selected is None:
                    continue

                # Risk check
                can_trade, reason = self.risk_manager.can_trade(selected)
                if not can_trade:
                    if verbose and reason != "position_already_open":
                        print(f"  {time_str} BLOCKED: {selected.strategy_name} — {reason}")
                    continue

                # Execute entry
                position = self.risk_manager.execute_entry(selected)
                position["entry_time"] = time_str
                position["entry_date"] = str(date)

                if verbose:
                    print(
                        f"  {date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else date} "
                        f"{time_str} ENTRY [{position['strategy']}] "
                        f"{position['direction']} "
                        f"@ {position['entry_price']:.1f} "
                        f"SL={position['stop_loss']:.1f} "
                        f"TGT={position['target']:.1f} "
                        f"Qty={position['quantity']}"
                    )

        return trades_today

    def _generate_time_steps(self) -> list[str]:
        """Generate 15-minute time steps from 09:15 to 15:30."""
        times = []
        hour = 9
        minute = 15
        while True:
            times.append(f"{hour:02d}:{minute:02d}")
            minute += 15
            if minute >= 60:
                hour += 1
                minute -= 60
            if hour > 15 or (hour == 15 and minute > 30):
                break
        return times

    def _get_price_at_time(self, day_15m: pd.DataFrame, time_str: str) -> float:
        """Get the close price of the 15m candle at the given time."""
        if day_15m.empty:
            return 0.0

        # Normalize time for comparison
        matching = day_15m[day_15m["Time"].str.strip() == time_str]
        if not matching.empty:
            return float(matching.iloc[0]["Close"])

        # Try with seconds (H:MM:SS format)
        time_with_sec = time_str + ":00"
        matching = day_15m[day_15m["Time"].str.strip() == time_with_sec]
        if not matching.empty:
            return float(matching.iloc[0]["Close"])

        # Try partial match
        for _, row in day_15m.iterrows():
            t = str(row["Time"]).strip()
            if t.startswith(time_str):
                return float(row["Close"])

        # Return last available price
        if not day_15m.empty:
            return float(day_15m.iloc[-1]["Close"])

        return 0.0

    def _get_candle_at_time(self, day_15m: pd.DataFrame, time_str: str) -> Optional[dict]:
        """Get a candle dict at the given time."""
        if day_15m.empty:
            return None

        matching = day_15m[day_15m["Time"].str.strip() == time_str]
        if matching.empty:
            time_with_sec = time_str + ":00"
            matching = day_15m[day_15m["Time"].str.strip() == time_with_sec]

        if matching.empty:
            for _, row in day_15m.iterrows():
                if str(row["Time"]).strip().startswith(time_str):
                    return row.to_dict()
            return None

        return matching.iloc[0].to_dict()

    def _check_stops_intraday(self, position: dict, candle: dict) -> Optional:
        """
        Check if a candle's Low/High hit the stop loss.

        More realistic than only checking at candle close.
        """
        from strategies.base import ExitSignal

        direction = position.get("direction", "LONG")
        stop_loss = position.get("stop_loss", 0)

        if direction == "LONG":
            candle_low = candle.get("Low", float('inf'))
            if candle_low <= stop_loss:
                return ExitSignal(
                    should_exit=True,
                    exit_price=stop_loss,
                    reason="stop_hit",
                )
        else:  # SHORT
            candle_high = candle.get("High", 0)
            if candle_high >= stop_loss:
                return ExitSignal(
                    should_exit=True,
                    exit_price=stop_loss,
                    reason="stop_hit",
                )

        return None

    def _compute_results(
        self, trade_log, equity_curve, total_days, no_trade_days,
        start_date, end_date,
    ) -> dict:
        """Compute summary results from the trade log."""
        total_trades = len(trade_log)

        if total_trades == 0:
            return {
                "start_date": start_date,
                "end_date": end_date,
                "total_days": total_days,
                "no_trade_days": no_trade_days,
                "total_trades": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "trade_log": trade_log,
                "equity_curve": equity_curve,
            }

        wins = [t for t in trade_log if t.get("net_pnl", 0) > 0]
        losses = [t for t in trade_log if t.get("net_pnl", 0) <= 0]
        net_pnl = sum(t.get("net_pnl", 0) for t in trade_log)
        initial = self.config["trading"]["initial_capital"]

        # Drawdown from equity curve
        max_dd = 0.0
        peak = initial
        for _, capital in equity_curve:
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Simple Sharpe approximation
        daily_pnls = [t.get("net_pnl", 0) for t in trade_log]
        if len(daily_pnls) > 1:
            mean_pnl = np.mean(daily_pnls)
            std_pnl = np.std(daily_pnls, ddof=1)
            risk_free_daily = (0.065 / 252) * initial  # 6.5% annualized
            sharpe = ((mean_pnl - risk_free_daily) / std_pnl * math.sqrt(252)
                      if std_pnl > 0 else 0)
        else:
            sharpe = 0.0

        # By strategy breakdown
        by_strategy = {}
        for t in trade_log:
            s = t.get("strategy", "unknown")
            if s not in by_strategy:
                by_strategy[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
            by_strategy[s]["trades"] += 1
            by_strategy[s]["pnl"] += t.get("net_pnl", 0)
            if t.get("net_pnl", 0) > 0:
                by_strategy[s]["wins"] += 1

        for s in by_strategy:
            bs = by_strategy[s]
            bs["win_rate"] = (bs["wins"] / bs["trades"] * 100) if bs["trades"] > 0 else 0

        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_days": total_days,
            "no_trade_days": no_trade_days,
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / total_trades * 100 if total_trades > 0 else 0,
            "net_pnl": round(net_pnl, 2),
            "return_pct": round(net_pnl / initial * 100, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 3),
            "avg_pnl": round(net_pnl / total_trades, 2) if total_trades > 0 else 0,
            "avg_win": (round(np.mean([t["net_pnl"] for t in wins]), 2)
                        if wins else 0),
            "avg_loss": (round(np.mean([t["net_pnl"] for t in losses]), 2)
                         if losses else 0),
            "profit_factor": (round(sum(t["net_pnl"] for t in wins) /
                                    abs(sum(t["net_pnl"] for t in losses)), 3)
                              if losses and sum(t["net_pnl"] for t in losses) != 0
                              else float('inf')),
            "by_strategy": by_strategy,
            "trade_log": trade_log,
            "equity_curve": equity_curve,
            "initial_capital": initial,
            "final_capital": round(self.risk_manager.current_capital, 2),
        }
