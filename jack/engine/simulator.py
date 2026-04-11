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
from data.global_data import load_global_data, get_premarket_context
from indicators.registry import IndicatorRegistry
from engine.risk import RiskManager
from engine.state_machine import StateMachine
from engine.scorer import StrategyScorer
from engine.filters import run_filter_stack
from journal.logger import JournalLogger
from analysis.post_trade import PostTradeAnalyzer

# Import strategies
from strategies.first_hour_verdict import FirstHourVerdict
from strategies.gap_fill import GapFill
from strategies.bb_squeeze import BBSqueezeBreakout
from strategies.gap_up_fade import GapUpFade
from strategies.vwap_reversion import VWAPReversion
from strategies.afternoon_breakout import AfternoonBreakout
from strategies.base import PositionManager

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

        # Load global pre-market data (gracefully — no crash if files missing)
        try:
            self._global_data = load_global_data(
                os.path.join(self.base_dir, "data", "raw", "global")
            )
        except Exception:
            self._global_data = {}

        # Initialize strategies
        self.strategies = {
            "first_hour_verdict": FirstHourVerdict(),
            "gap_fill": GapFill(),
            "bb_squeeze": BBSqueezeBreakout(),
            "gap_up_fade": GapUpFade(),
            "vwap_reversion": VWAPReversion(),
            "afternoon_breakout": AfternoonBreakout(),
        }

        # Load AI retrospective insight weights (if any saved insights exist)
        try:
            from brain.retrospective import get_scorer_adjustments
            _knowledge_dir = os.path.join(self.base_dir, "brain", "knowledge")
            insight_weights = get_scorer_adjustments(_knowledge_dir)
            if insight_weights:
                print(f"[Scorer] Loaded insight weights: {insight_weights}")
        except Exception:
            insight_weights = {}

        self.scorer = StrategyScorer(
            self.strategies,
            min_score_threshold=0.4,
            insight_weights=insight_weights,
        )
        self.journal = JournalLogger(
            output_dir=os.path.join(self.base_dir, "journal", "logs")
        )
        self._pta = PostTradeAnalyzer()
        self._missed_trades_today = []
        self.position_manager = PositionManager()

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

        self.diagnostics_summary = {
            "total_days": 0,
            "per_strategy_summary": {
                s: {
                    "days_eligible": 0,
                    "base_condition_met": 0,
                    "signal_generated": 0,
                    "passed_filters": 0,
                    "passed_scorer": 0,
                    "reason_histogram": {}
                } for s in self.strategies
            }
        }

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
            self._missed_trades_today = []
            
            self.diagnostics_summary["total_days"] += 1
            self.today_diagnostics = {
                s: {
                    "eligible_phase": False,
                    "base_condition_met": False,
                    "signal_generated": False,
                    "reason_skipped": "not_eligible_today"
                } for s in self.strategies
            }

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

            # Save diagnostics for the day
            decision_log = self.scorer.get_decision_log()
            for s_name, d_status in self.today_diagnostics.items():
                ds = self.diagnostics_summary["per_strategy_summary"][s_name]
                if d_status["eligible_phase"]:
                    ds["days_eligible"] += 1
                if d_status["base_condition_met"]:
                    ds["base_condition_met"] += 1
                if d_status["signal_generated"]:
                    ds["signal_generated"] += 1
                
                passed_filters = False
                passed_scorer = False
                for d_log in decision_log:
                    if d_log.get("reason") == "no_signals": continue
                    for sc in d_log.get("all_scores", []):
                        if sc["strategy"] == s_name:
                            passed_filters = True
                    if d_log.get("selected") and d_log["selected"]["strategy"] == s_name:
                        passed_scorer = True
                        
                if passed_filters:
                    ds["passed_filters"] += 1
                if passed_scorer:
                    ds["passed_scorer"] += 1
                    
                final_reason = "traded"
                if not d_status["eligible_phase"]:
                    final_reason = "not_eligible_today"
                elif not passed_scorer:
                    if passed_filters:
                        final_reason = "lost_to_better_signal"
                    elif d_status["signal_generated"]:
                        final_reason = "scored_below_threshold"
                    else:
                        final_reason = d_status.get("reason_skipped", "unknown")
                
                ds["reason_histogram"][final_reason] = ds["reason_histogram"].get(final_reason, 0) + 1

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
                    missed_opportunities=self._missed_trades_today,
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

        # Trigger AI retrospective after simulation completes
        try:
            from brain.retrospective import run_retrospective
            journal_logs_dir = os.path.join(self.base_dir, "journal", "logs")
            knowledge_dir = os.path.join(self.base_dir, "brain", "knowledge")
            if verbose:
                print("\n[Retrospective] Running AI retrospective on completed simulation...")
            run_retrospective(
                journal_logs_dir=journal_logs_dir,
                knowledge_dir=knowledge_dir,
                after_date=None,
                before_date=measure_end,
            )
        except Exception as e:
            if verbose:
                print(f"  [WARN] AI retrospective skipped: {e}")

        # Compute final results
        results = self._compute_results(
            trade_log, equity_curve, total_days, no_trade_days,
            measure_start, measure_end,
        )

        import json
        diag_path = os.path.join(self.base_dir, "journal", "logs", "diagnostics_summary.json")
        with open(diag_path, "w") as df:
            json.dump(self.diagnostics_summary, df, indent=2)

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
        self._missed_trades_today = []

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
                missed_opportunities=self._missed_trades_today,
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
            "global": get_premarket_context(date, self._global_data),
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

        day_5m = day_data.get("5m", pd.DataFrame())
        intraday_indicators_5m = {}
        if not day_5m.empty and len(day_5m) >= 14:
            try:
                day_5m_ind = self.indicator_registry.compute("rsi", day_5m, period=14)
                day_5m_ind = self.indicator_registry.compute("ema", day_5m_ind, period=9)
                day_5m_ind = self.indicator_registry.compute("ema", day_5m_ind, period=21)
                day_5m_ind = self.indicator_registry.compute("vwap", day_5m_ind)
                intraday_indicators_5m = day_5m_ind
            except Exception:
                pass

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

            # Classification of day type at 10:30
            if time_str == "10:30":
                day_type = self._pta.classify_day_type(day_data, briefing)
                briefing["day_type"] = day_type
                
                if self.risk_manager.open_position is not None:
                    pos = self.risk_manager.open_position
                    if day_type in ("trend_up", "trend_down"):
                        pos["target_mode"] = "trailing"
                    elif day_type == "range":
                        pos["target_mode"] = "quick_profit"

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
                
                # Update max/min price since entry for trailing stops
                meta = pos.get("metadata", {})
                candle_high = candle.get("High", current_price) if candle is not None else current_price
                candle_low = candle.get("Low", current_price) if candle is not None else current_price
                
                if pos["direction"] == "LONG":
                    meta["max_price_since_entry"] = max(meta.get("max_price_since_entry", pos["entry_price"]), candle_high)
                else:
                    meta["min_price_since_entry"] = min(meta.get("min_price_since_entry", pos["entry_price"]), candle_low)
                    
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

                # PositionManager adaptive check
                if pos:
                    day_type = briefing.get("day_type", "normal")
                    attr = pos.get("metadata", {}).get("atr", indicators.get("ATR", 100))
                    # Fallback to daily ATR if metadata missing
                    if attr is None: attr = 100
                    
                    pm_signal = self.position_manager.manage(pos, current_price, time_str, attr, day_type)
                    if pm_signal and pm_signal.should_exit:
                        # Only handle partial exits loosely for now by updating quantity and logging a trade
                        if pm_signal.reason == "partial_exit":
                            qty = pos["quantity"]
                            exit_qty = int(qty * pm_signal.partial_pct)
                            
                            if exit_qty >= self.risk_manager.lot_size:
                                # We temporarily reduce the position to let `execute_exit` handle the log
                                orig_qty = pos["quantity"]
                                pos["quantity"] = exit_qty
                                result = self.risk_manager.execute_exit(pm_signal, current_price)
                                result["exit_time"] = time_str
                                result["exit_date"] = str(date)
                                trades_today.append(result)
                                
                                # Restore open position with remaining quantity
                                pos["quantity"] = orig_qty - exit_qty
                                self.risk_manager.open_position = pos
                                
                                if verbose:
                                    pnl = result["net_pnl"]
                                    color = "\033[92m" if pnl >= 0 else "\033[91m"
                                    print(f"  {date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else date} "
                                          f"{time_str} PARTIAL EXIT [{result['strategy']}] "
                                          f"{result['direction']} "
                                          f"@ {result['exit_price']:.1f} ({exit_qty} units) "
                                          f"→ {color}₹{pnl:+,.0f}\033[0m")
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
                if "ALL" in eligible:
                    eligible = list(self.strategies.keys())

                # Get 5m indicators
                inds_5m = self._get_5m_indicators_at_time(intraday_indicators_5m, time_str)
                briefing["5m_indicators"] = inds_5m

                # Build indicator context for strategies
                strat_indicators = {
                    "current_price": current_price,
                    "rsi_5m": inds_5m.get("rsi_5m"),
                    "ema_9_5m": inds_5m.get("ema_9_5m"),
                    "ema_21_5m": inds_5m.get("ema_21_5m"),
                    "vwap": inds_5m.get("vwap"),
                    "vwap_upper": inds_5m.get("vwap_upper"),
                    "vwap_lower": inds_5m.get("vwap_lower"),
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
                        # Use period=10 so BB is valid by 12:15 (~13 candles in the day)
                        bb_15m = self.indicator_registry.compute("bbands", day_15m, period=10)
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
                        
                    if hasattr(self, 'today_diagnostics'):
                        strat_diag = self.today_diagnostics[strat_name]
                        strat_diag["eligible_phase"] = True
                        if strat_diag["reason_skipped"] == "not_eligible_today":
                            strat_diag["reason_skipped"] = "time_passed_no_signal"

                    try:
                        temp_diag = {}
                        signal = strategy.check_entry(
                            day_data=day_data,
                            lookback={},
                            indicators=strat_indicators,
                            current_time=time_str,
                            filters=filters,
                            diagnostics=temp_diag,
                        )
                        if hasattr(self, 'today_diagnostics'):
                            strat_diag = self.today_diagnostics[strat_name]
                            if temp_diag.get("base_condition_met"):
                                strat_diag["base_condition_met"] = True
                            if temp_diag.get("signal_generated"):
                                strat_diag["signal_generated"] = True
                                strat_diag["reason_skipped"] = None
                            elif not strat_diag["signal_generated"] and temp_diag.get("reason_skipped"):
                                strat_diag["reason_skipped"] = temp_diag["reason_skipped"]

                        if signal is not None:
                            signals.append(signal)
                    except Exception as e:
                        if verbose:
                            print(f"  [WARN] {strat_name} entry check failed: {e}")

                if not signals:
                    continue

                # Adaptive Context Estimation
                live_context = {
                    "regime": indicators.get("Regime", "normal"),
                    "gap_type": indicators.get("Gap_Type", "flat"),
                    "time": time_str,
                }
                
                # Score and select
                selected = self.scorer.select_trade(signals, filters)
                if selected is None:
                    continue

                # Risk check
                can_trade, reason = self.risk_manager.can_trade(selected)
                if not can_trade:
                    if reason != "position_already_open":
                        missed = self._pta.analyze_missed_trade(selected, reason, day_data)
                        self._missed_trades_today.append(missed)
                        if verbose:
                            print(f"  {time_str} BLOCKED: {selected.strategy_name} — {reason}")
                    continue

                # Try 5m pullback entry
                from strategies.base import TradeSignal
                pullback_price, pullback_time = self._find_pullback_entry_5m(
                    day_data, selected, time_str
                )
                if pullback_price != selected.entry_price:
                    selected = TradeSignal(
                        strategy_name=selected.strategy_name,
                        direction=selected.direction,
                        entry_price=pullback_price,
                        stop_loss=selected.stop_loss,
                        target=selected.target,
                        confidence=selected.confidence + 0.05,
                        reason=selected.reason + f" [5m pullback entry at {pullback_time}]",
                        metadata={**selected.metadata, "pullback_entry": True, "original_entry": selected.entry_price},
                    )

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

        for t in trades_today:
            t["post_mortem"] = self._pta.analyze_trade(t, day_data, indicators)

        return trades_today

    def _get_5m_indicators_at_time(self, day_5m_ind, time_str):
        """Get 5m indicator values at or before the given time."""
        if day_5m_ind is None or isinstance(day_5m_ind, dict) or day_5m_ind.empty:
            return {}

        available = day_5m_ind[day_5m_ind["Time"].str.strip() <= time_str]
        if available.empty:
            return {}

        last = available.iloc[-1]
        return {
            "rsi_5m": last.get("RSI"),
            "ema_9_5m": last.get("EMA_9"),
            "ema_21_5m": last.get("EMA_21"),
            "vwap": last.get("VWAP"),
            "vwap_upper": last.get("VWAP_Upper"),
            "vwap_lower": last.get("VWAP_Lower"),
        }

    def _find_pullback_entry_5m(self, day_data, signal, start_time, max_wait_candles=6):
        """
        After a strategy signal fires, scan 5m candles for a pullback entry.
        """
        day_5m = day_data.get("5m", pd.DataFrame())
        if day_5m.empty:
            return signal.entry_price, start_time

        fh_data = signal.metadata.get("fh_return", 0)
        fh_range = signal.metadata.get("fh_range", 0)

        # Get 5m candles after start_time
        after_signal = day_5m[day_5m["Time"].str.strip() >= start_time].head(max_wait_candles)

        if after_signal.empty:
            return signal.entry_price, start_time

        for _, candle in after_signal.iterrows():
            candle_time = str(candle["Time"]).strip()

            if signal.direction == "LONG":
                # Look for a dip (retracement) then bullish close
                retracement = signal.entry_price - candle["Low"]
                if fh_range > 0:
                    retrace_pct = retracement / fh_range
                else:
                    retrace_pct = 0

                # Accept if price pulled back 20-60% of FH range and candle is bullish
                if 0.2 <= retrace_pct <= 0.6 and candle["Close"] > candle["Open"]:
                    return float(candle["Close"]), candle_time[:5]

            elif signal.direction == "SHORT":
                retracement = candle["High"] - signal.entry_price
                if fh_range > 0:
                    retrace_pct = retracement / fh_range
                else:
                    retrace_pct = 0

                if 0.2 <= retrace_pct <= 0.6 and candle["Close"] < candle["Open"]:
                    return float(candle["Close"]), candle_time[:5]

        # No pullback found
        return signal.entry_price, start_time

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

    def _compute_sharpe_from_equity(self, equity_curve, risk_free_annual=0.065):
        """Compute Sharpe from daily equity returns including flat days."""
        if len(equity_curve) < 2:
            return 0.0

        # Extract daily equity values
        daily_values = [eq[1] for eq in equity_curve]

        # Compute daily returns (including zero-return flat days)
        daily_returns = []
        for i in range(1, len(daily_values)):
            if daily_values[i-1] > 0:
                ret = (daily_values[i] - daily_values[i-1]) / daily_values[i-1]
                daily_returns.append(ret)

        if len(daily_returns) < 2:
            return 0.0

        daily_returns = np.array(daily_returns)
        risk_free_daily = risk_free_annual / 252

        excess_returns = daily_returns - risk_free_daily
        mean_excess = np.mean(excess_returns)
        std_returns = np.std(daily_returns, ddof=1)

        if std_returns <= 0:
            return 0.0

        return float(mean_excess / std_returns * math.sqrt(252))

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

        # Sharpe from daily equity returns (including flat/no-trade days)
        sharpe = self._compute_sharpe_from_equity(equity_curve)

        # Keep old per-trade calculation for reference
        daily_pnls = [t.get("net_pnl", 0) for t in trade_log]
        if len(daily_pnls) > 1:
            mean_pnl = np.mean(daily_pnls)
            std_pnl = np.std(daily_pnls, ddof=1)
            risk_free_daily = (0.065 / 252) * initial
            sharpe_inflated = ((mean_pnl - risk_free_daily) / std_pnl * math.sqrt(252)
                               if std_pnl > 0 else 0)
        else:
            sharpe_inflated = 0.0

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
