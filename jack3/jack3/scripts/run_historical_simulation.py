"""
Jack v3 — Historical Simulation with Learning.

Replays any date range of BankNifty data day-by-day, letting the system
learn progressively: each day's journal feeds the next day's thesis.

Usage:
  python scripts/run_historical_simulation.py --csv data.csv
  python scripts/run_historical_simulation.py --csv data.csv --from 2022-01-01 --to 2022-12-31
  python scripts/run_historical_simulation.py --csv data.csv --from 2022-01-01 --no-ai
  python scripts/run_historical_simulation.py --csv data.csv --strategy first_hour_verdict

CSV format expected (5-minute BankNifty candles):
  datetime,open,high,low,close,volume
  2022-01-03 09:15:00,36500.0,36550.0,36480.0,36530.0,12345
  ...

Column names are flexible — the normalizer handles variants like
Date/date/Datetime, Open/open/OPEN, etc.

How learning works:
  Day 1: Thesis generated with no journal history (neutral/fallback).
  Day 2: Thesis reads Day 1 journal (what worked, what failed, lessons).
  Day N: Thesis reads last 10 days of journal + strategy rankings.
  After every 20 days: Strategy ranker re-runs, updates rankings.json.

Flags:
  --no-ai        Skip AI evaluator — uses strategy signals directly (fast, no tokens)
  --batch-ai     Send ALL days to AI in one call, cache decisions to disk.
                 Avoids per-candle rate limits. Recommended for backtesting.
                 Example: 5 days = 1 API call instead of 375.
  --batch-size N Days per batch when using --batch-ai (default: 5).
                 Increase if your AI provider supports large context windows.
  --strategy X   Only test one strategy (forces no-ai mode)
  --ai-every N   Run AI evaluator only every N days (e.g., --ai-every 5 = 20% of days)
  --review-ai    Run AI post-trade review each day (slower but richer journal)
  --from DATE    Start date (YYYY-MM-DD), default: first date in CSV
  --to DATE      End date (YYYY-MM-DD), default: last date in CSV
"""

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Jack v3 Historical Simulation with Learning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--csv", required=True, help="Path to 5-min candle CSV file")
    parser.add_argument("--from", dest="from_date", help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="End date YYYY-MM-DD")
    parser.add_argument("--config", default="config/settings.yaml", help="Config path")
    parser.add_argument("--no-ai", action="store_true",
                        help="Skip AI evaluator — use strategy signals only (fast)")
    parser.add_argument("--ai-every", type=int, default=1, metavar="N",
                        help="Run AI evaluator every N days only (default: every day)")
    parser.add_argument("--review-ai", action="store_true",
                        help="Run AI post-trade review each day (richer journal, slower)")
    parser.add_argument("--strategy", help="Test a single strategy (implies --no-ai)")
    parser.add_argument("--rank-every", type=int, default=20, metavar="N",
                        help="Re-rank strategies every N days (default: 20)")
    parser.add_argument("--output", default="sim_results", help="Output directory for results")
    parser.add_argument("--batch-ai", action="store_true",
                        help="Send ALL days to AI in one call, cache decisions — avoids per-candle rate limits")
    parser.add_argument("--batch-size", type=int, default=5, metavar="N",
                        help="Days per batch when using --batch-ai (default: 5)")
    args = parser.parse_args()

    # --strategy implies --no-ai (strategy signals drive decisions)
    if args.strategy:
        args.no_ai = True

    # Load config
    with open(args.config) as f:
        config = yaml.safe_load(f)

    # Load and parse CSV
    print(f"\n[Sim] Loading candle data from: {args.csv}")
    all_candles = load_candle_csv(args.csv)
    if all_candles is None or len(all_candles) == 0:
        print("[Sim] ERROR: Could not load candle data. Check CSV format.")
        sys.exit(1)

    # Date filtering
    trading_dates = get_trading_dates(all_candles, args.from_date, args.to_date)
    if not trading_dates:
        print("[Sim] ERROR: No trading dates found in the specified range.")
        sys.exit(1)

    print(f"[Sim] Dates: {trading_dates[0]} -> {trading_dates[-1]} ({len(trading_dates)} days)")
    if args.no_ai:
        print(f"[Sim] Mode: Technical-only (no AI)")
    elif getattr(args, "batch_ai", False):
        print(f"[Sim] Mode: Batch AI (1 API call per {args.batch_size} days)")
    else:
        print(f"[Sim] Mode: AI-assisted (live per-candle)")
    if args.strategy:
        print(f"[Sim] Single strategy: {args.strategy}")

    # Prepare output directory
    os.makedirs(args.output, exist_ok=True)
    os.makedirs(f"{args.output}/journal", exist_ok=True)

    # Initialize the main loop (with simulation config)
    sim_config = _build_sim_config(config, args.output)
    from engine.loop import JackMainLoop
    loop = JackMainLoop.__new__(JackMainLoop)
    loop.config_path = args.config
    loop.config = sim_config
    loop.live = False
    loop.paper_mode = True
    loop._sim_mode = False
    loop._sim_candles = None
    loop._trade_date = None
    loop._init_components()

    # Override journal output dir to sim results
    loop.journal.output_dir = f"{args.output}/journal"
    loop.journal.json_dir = f"{args.output}/journal/json"
    os.makedirs(loop.journal.json_dir, exist_ok=True)

    # ── Batch AI pre-warming ──────────────────────────────────────────
    batch_cache: dict = {}
    if getattr(args, "batch_ai", False) and not args.no_ai:
        batch_cache = _run_batch_prewarming(
            all_candles=all_candles,
            trading_dates=trading_dates,
            config=sim_config,
            batch_size=args.batch_size,
            output_dir=args.output,
        )
        if batch_cache:
            # Store cache on the loop — _run_one_tick reads it each candle
            loop._batch_decision_cache = batch_cache
            print(f"[BatchAI] Cache attached to loop: {len(batch_cache)} days ready.")

    # Run simulation
    simulator = HistoricalSimulator(
        loop=loop,
        config=sim_config,
        all_candles=all_candles,
        trading_dates=trading_dates,
        no_ai=args.no_ai,
        ai_every=args.ai_every,
        review_ai=args.review_ai,
        strategy_filter=args.strategy,
        rank_every=args.rank_every,
        output_dir=args.output,
        batch_cache=batch_cache,
    )

    results = simulator.run()
    _print_final_report(results, trading_dates)
    _save_final_report(results, args.output)


# ─────────────────────────────────────────────────
#  Main simulator class
# ─────────────────────────────────────────────────

class HistoricalSimulator:
    """Runs the Jack v3 loop over historical data day by day."""

    def __init__(
        self,
        loop,
        config: dict,
        all_candles: pd.DataFrame,
        trading_dates: list,
        no_ai: bool,
        ai_every: int,
        review_ai: bool,
        strategy_filter: Optional[str],
        rank_every: int,
        output_dir: str,
        batch_cache: dict = None,
    ):
        self.loop = loop
        self.config = config
        self.all_candles = all_candles
        self.trading_dates = trading_dates
        self.no_ai = no_ai
        self.ai_every = ai_every
        self.review_ai = review_ai
        self.strategy_filter = strategy_filter
        self.rank_every = rank_every
        self.output_dir = output_dir
        self.batch_cache = batch_cache or {}

        self.day_results: list = []
        self.cumulative_pnl: float = 0.0
        self.day_number: int = 0

    def run(self) -> dict:
        """Run the full simulation. Returns aggregate results."""
        print(f"\n{'='*60}")
        print(f"  JACK v3 HISTORICAL SIMULATION")
        print(f"{'='*60}")

        for trade_date in self.trading_dates:
            self.day_number += 1
            day_candles = self._get_day_candles(trade_date)

            if day_candles is None or len(day_candles) < 10:
                print(f"[Sim] {trade_date}: skipping (< 10 candles)")
                continue

            # Tell the loop which date we're simulating (for batch cache lookups)
            if self.batch_cache:
                self.loop._batch_decision_date = str(trade_date)

            # Decide whether to use AI for this day
            # In batch mode, the cache drives decisions — evaluator won't call live API
            use_ai = not self.no_ai and (self.day_number % self.ai_every == 0)

            # Build pre-market context (thesis + dependents)
            pre_market_context = self._build_pre_market_context(trade_date, use_ai)

            # Patch the loop's evaluator if no_ai
            if not use_ai:
                self._patch_loop_for_no_ai()
            else:
                self._unpatch_loop()

            # Patch strategy filter if set
            if self.strategy_filter:
                self._patch_strategy_filter()

            # Run the simulation day
            skip_review = not self.review_ai
            result = self.loop.run_simulation_day(
                trade_date=trade_date,
                day_candles_df=day_candles,
                pre_market_context=pre_market_context,
                skip_ai_review=skip_review,
            )

            self.day_results.append(result)
            self.cumulative_pnl += result.get("daily_pnl", 0)

            # Progress print
            cap = result.get("capital", {}).get("current_capital", 0)
            trades = len(result.get("trades", []))
            wins = result.get("wins", 0)
            pnl = result.get("daily_pnl", 0)
            pnl_str = f"+{pnl:.0f}" if pnl >= 0 else f"{pnl:.0f}"
            print(f"[Sim] {trade_date} | P&L: Rs.{pnl_str} | Trades: {trades} (W:{wins}) "
                  f"| Capital: Rs.{cap:,.0f} | Cumulative: Rs.{self.cumulative_pnl:,.0f}")

            # Re-rank strategies periodically (this updates rankings.json, which the thesis reads)
            if self.day_number % self.rank_every == 0 and self.day_number >= self.rank_every:
                self._run_incremental_ranking(trade_date)

        return self._aggregate_results()

    # ─────────────────────────────────────────────────
    #  Pre-market context builder
    # ─────────────────────────────────────────────────

    def _build_pre_market_context(self, trade_date, use_ai: bool) -> dict:
        """Build pre-market context (thesis + dependents) for a simulated day."""
        # Get prior day's close for momentum bias
        prior_candles = self._get_candles_before(trade_date, days=5)
        dependents = self._compute_momentum_bias(prior_candles, trade_date)

        # Load recent journal and rankings for thesis context
        recent_journal = self.loop.journal.get_recent_entries(n=10)
        strategy_rankings = self._load_rankings()

        if use_ai:
            # Use AI thesis generator (reads journal + rankings)
            try:
                from brain.thesis import ThesisGenerator
                from brain.ai_client import create_ai_client
                ai = create_ai_client(self.config, mode="intraday")
                thesis_gen = ThesisGenerator(ai)
                thesis = thesis_gen.generate(
                    dependents=dependents,
                    research={},
                    recent_journal=recent_journal,
                    strategy_rankings=strategy_rankings,
                )
            except Exception as e:
                print(f"[Sim] AI thesis failed: {e}. Using momentum fallback.")
                thesis = self._momentum_thesis(dependents, recent_journal)
        else:
            # No-AI: derive thesis from price momentum and recent journal lessons
            thesis = self._momentum_thesis(dependents, recent_journal)

        return {"thesis": thesis, "dependents": dependents, "research": {}}

    def _compute_momentum_bias(self, prior_candles: pd.DataFrame, trade_date) -> dict:
        """
        Compute a simple pre-market bias from recent price momentum.
        Replaces web scraping for historical simulation.

        Signals used:
          - 3-day price momentum (% change over last 3 closes)
          - Prior day close vs 5-day EMA direction
          - Prior day range (ATR proxy)
        """
        if prior_candles is None or len(prior_candles) < 10:
            return {"weighted_bias": 0.0, "bias_direction": "NEUTRAL", "momentum_pct": 0.0}

        # Get daily closes (last candle of each day as proxy)
        close_col = "close" if "close" in prior_candles.columns else "Close"
        closes = prior_candles.groupby(
            prior_candles.iloc[:, 0].apply(
                lambda x: pd.Timestamp(x).date() if hasattr(x, 'date') else x
            )
        )[close_col].last().sort_index()

        if len(closes) < 2:
            return {"weighted_bias": 0.0, "bias_direction": "NEUTRAL", "momentum_pct": 0.0}

        # 3-day momentum
        n = min(3, len(closes) - 1)
        momentum_pct = (closes.iloc[-1] - closes.iloc[-1 - n]) / closes.iloc[-1 - n] * 100

        # Normalize to -1..+1 (2% move = signal of 1.0)
        signal = momentum_pct / 2.0
        signal = max(-1.0, min(1.0, signal))

        bias_direction = "BULLISH" if signal > 0.15 else ("BEARISH" if signal < -0.15 else "NEUTRAL")

        return {
            "weighted_bias": round(signal, 4),
            "bias_direction": bias_direction,
            "momentum_pct": round(momentum_pct, 4),
            "prior_close": round(float(closes.iloc[-1]), 2),
            "fetch_errors": [],
        }

    def _momentum_thesis(self, dependents: dict, recent_journal: list) -> dict:
        """
        Generate a simple rule-based thesis from momentum + journal lessons.
        Used when --no-ai is set or AI fails.
        """
        bias = dependents.get("weighted_bias", 0.0)
        bias_dir = dependents.get("bias_direction", "NEUTRAL")
        momentum_pct = dependents.get("momentum_pct", 0.0)

        # Derive confidence from signal strength
        confidence = min(abs(bias) * 1.5, 0.65)

        # Extract any recent lessons that mention direction bias
        lessons = []
        for entry in recent_journal[:5]:
            for trade in entry.get("trades", []):
                lesson = trade.get("ai_review", {}).get("lesson", "")
                if lesson:
                    lessons.append(lesson)

        reasoning = (
            f"Momentum-based thesis: {momentum_pct:+.2f}% over last 3 days. "
            f"Prior close: {dependents.get('prior_close', 0):.0f}. "
            f"Recent lessons: {len(lessons)} available."
        )

        # Determine entry time based on confidence
        if confidence >= 0.5:
            bias_entry_after = "09:30"
        elif confidence >= 0.3:
            bias_entry_after = "10:15"
        else:
            bias_entry_after = "10:30"

        return {
            "direction": bias_dir,
            "confidence": round(confidence, 2),
            "reasoning": reasoning,
            "key_factors": ["price_momentum", "journal_lessons"],
            "suggested_strategy": None,
            "risk_note": "Momentum-only thesis — no AI research",
            "expected_range_pts": 300,
            "bias_entry_after": bias_entry_after,
        }

    # ─────────────────────────────────────────────────
    #  Loop patching for no-AI mode
    # ─────────────────────────────────────────────────

    def _patch_loop_for_no_ai(self):
        """
        Replace the AI evaluator in the loop with a strategy-signal evaluator.

        In no-AI mode, decisions come from the strategy implementations directly
        (first_hour_verdict, gap_fill, etc.) instead of the AI.
        """
        if not hasattr(self, "_original_run_one_tick"):
            self._original_run_one_tick = self.loop._run_one_tick

        strategy_filter = self.strategy_filter
        loop = self.loop

        def _technical_tick(tick_time: str, security_id: str, context: dict):
            """Tick handler using deterministic strategy signals instead of AI."""
            candles_df = loop._fetch_latest_candles(security_id, tick_time)
            if candles_df is None or len(candles_df) < 5:
                return

            current_candle = candles_df.iloc[-1].to_dict()
            current_price = float(current_candle.get("Close", current_candle.get("close", 0)))

            indicators = loop._compute_indicators(candles_df)

            # Check SL/target hit
            if loop.current_position:
                if loop._check_sl_target(current_price, tick_time):
                    return

            # Check phase gating
            try:
                phase = loop.state_machine.get_current_phase(tick_time) if tick_time < "15:00" else None
            except ValueError:
                phase = None

            # Exit if in closing phase
            if loop.state_machine.must_exit_all(tick_time) and loop.current_position:
                loop._force_close_position(tick_time)
                return

            # Build strategy context
            day_data = {
                "date": str(loop._trade_date),
                "open_price": current_price,
                "daily": {},
            }
            filters = {
                "combined_long_multiplier": 1.0,
                "combined_short_multiplier": 1.0,
            }

            # Get strategy signals
            signals = _gather_strategy_signals(
                loop=loop,
                day_data=day_data,
                indicators=indicators,
                tick_time=tick_time,
                filters=filters,
                phase=phase,
                strategy_filter=strategy_filter,
            )

            # Arbitrate with scorer
            decision = {"action": "HOLD", "reasoning": "no signal"}
            if signals and not loop.current_position:
                best = loop.scorer.select_trade(signals, filters) if hasattr(loop, "scorer") else signals[0]
                if best:
                    action = "ENTER_LONG" if best.direction == "LONG" else "ENTER_SHORT"
                    decision = {
                        "action": action,
                        "entry_price": best.entry_price,
                        "stop_loss": best.stop_loss,
                        "target": best.target,
                        "confidence": best.confidence,
                        "reasoning": best.reason,
                        "suggested_strategy": best.strategy_name,
                    }

            decision["tick_time"] = tick_time
            decision["current_price"] = current_price
            loop.daily_decisions.append(decision)

            action = decision.get("action", "HOLD")
            if action in ("ENTER_LONG", "ENTER_SHORT") and not loop.current_position:
                loop._attempt_entry(decision, action, tick_time, current_price)

        loop._run_one_tick = _technical_tick

    def _unpatch_loop(self):
        """Restore the original AI-based tick handler."""
        if hasattr(self, "_original_run_one_tick"):
            self.loop._run_one_tick = self._original_run_one_tick

    def _patch_strategy_filter(self):
        """Limit which strategies fire (used with --strategy flag)."""
        # Already handled inside _technical_tick via strategy_filter param
        pass

    # ─────────────────────────────────────────────────
    #  Incremental ranking
    # ─────────────────────────────────────────────────

    def _run_incremental_ranking(self, as_of_date):
        """
        Re-rank strategies using journal data accumulated so far.
        Updates lab/rankings.json so future thesis generation reflects current performance.
        """
        print(f"\n[Sim] Re-ranking strategies as of {as_of_date}...")
        try:
            from lab.ranker import run_ranking
            # Get candles for the last 20 days of simulation
            recent_dates = [d for d in self.trading_dates if d <= as_of_date][-20:]
            if not recent_dates:
                return

            recent_candles = pd.concat([
                self._get_day_candles(d) for d in recent_dates
                if self._get_day_candles(d) is not None
            ], ignore_index=True)

            run_ranking(
                config=self.config,
                candle_data=recent_candles,
                daily_data=pd.DataFrame(),
            )
            print(f"[Sim] Rankings updated.")
        except Exception as e:
            print(f"[Sim] Ranking failed: {e}")

    def _load_rankings(self) -> list:
        """Load current strategy rankings."""
        rankings_path = "lab/rankings.json"
        if os.path.exists(rankings_path):
            try:
                with open(rankings_path) as f:
                    return json.load(f).get("rankings", [])
            except Exception:
                pass
        return []

    # ─────────────────────────────────────────────────
    #  Data helpers
    # ─────────────────────────────────────────────────

    def _get_day_candles(self, trade_date) -> Optional[pd.DataFrame]:
        """Get 5-minute candles for a specific trading date."""
        date_col = _find_date_column(self.all_candles)
        if date_col is None:
            return None

        mask = self.all_candles[date_col].apply(
            lambda x: _to_date(x) == trade_date
        )
        day_df = self.all_candles[mask].copy()
        return day_df if len(day_df) > 0 else None

    def _get_candles_before(self, trade_date, days: int = 5) -> Optional[pd.DataFrame]:
        """Get candles from the N days before trade_date."""
        date_col = _find_date_column(self.all_candles)
        if date_col is None:
            return None

        mask = self.all_candles[date_col].apply(
            lambda x: _to_date(x) < trade_date
        )
        prior = self.all_candles[mask]
        if len(prior) == 0:
            return None

        # Get last N distinct dates
        prior_dates = sorted(prior[date_col].apply(_to_date).unique())[-days:]
        mask2 = self.all_candles[date_col].apply(lambda x: _to_date(x) in prior_dates)
        return self.all_candles[mask2].copy()

    # ─────────────────────────────────────────────────
    #  Results aggregation
    # ─────────────────────────────────────────────────

    def _aggregate_results(self) -> dict:
        """Compute aggregate statistics across all simulated days."""
        if not self.day_results:
            return {}

        all_trades = []
        for day in self.day_results:
            all_trades.extend(day.get("trades", []))

        daily_pnls = [d.get("daily_pnl", 0) for d in self.day_results]
        trade_days = [d for d in self.day_results if d.get("trades")]

        total_pnl = sum(daily_pnls)
        winning_trades = [t for t in all_trades if t.get("net_pnl", 0) > 0]
        losing_trades = [t for t in all_trades if t.get("net_pnl", 0) <= 0]

        win_rate = len(winning_trades) / len(all_trades) * 100 if all_trades else 0

        # Sharpe
        import numpy as np
        sharpe = 0.0
        if len(daily_pnls) > 1 and np.std(daily_pnls) > 0:
            sharpe = (np.mean(daily_pnls) / np.std(daily_pnls)) * math.sqrt(252)

        # Max drawdown
        initial_capital = self.config.get("trading", {}).get("initial_capital", 1000000)
        equity = initial_capital
        peak = initial_capital
        max_dd = 0.0
        for pnl in daily_pnls:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        final_capital = initial_capital + total_pnl

        return {
            "period": {
                "from": str(self.trading_dates[0]),
                "to": str(self.trading_dates[-1]),
                "total_days": len(self.trading_dates),
                "trading_days_simulated": len(self.day_results),
                "days_with_trades": len(trade_days),
            },
            "performance": {
                "total_pnl": round(total_pnl, 2),
                "initial_capital": initial_capital,
                "final_capital": round(final_capital, 2),
                "return_pct": round(total_pnl / initial_capital * 100, 2),
                "win_rate_pct": round(win_rate, 2),
                "total_trades": len(all_trades),
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "avg_win": round(
                    sum(t.get("net_pnl", 0) for t in winning_trades) / len(winning_trades), 2
                ) if winning_trades else 0,
                "avg_loss": round(
                    sum(t.get("net_pnl", 0) for t in losing_trades) / len(losing_trades), 2
                ) if losing_trades else 0,
                "max_drawdown_pct": round(max_dd, 2),
                "sharpe_ratio": round(sharpe, 3),
                "avg_daily_pnl": round(total_pnl / len(self.day_results), 2) if self.day_results else 0,
            },
            "strategy_breakdown": _strategy_breakdown(all_trades),
            "daily_results": self.day_results,
        }


# ─────────────────────────────────────────────────
#  Batch AI pre-warming
# ─────────────────────────────────────────────────

def _run_batch_prewarming(
    all_candles: pd.DataFrame,
    trading_dates: list,
    config: dict,
    batch_size: int,
    output_dir: str,
) -> dict:
    """
    Pre-compute AI decisions for all trading_dates in batches of batch_size days.

    For each batch:
      1. Extract candles + compute indicators for each day
      2. Build a momentum thesis per day (no AI call needed for thesis)
      3. Send the whole batch to AI in ONE call
      4. Cache the responses to disk

    Returns a merged cache dict covering all dates.
    """
    from brain.ai_client import create_ai_client
    from brain.batch_evaluator import BatchEvaluator
    from indicators.registry import IndicatorRegistry

    print(f"\n[BatchAI] Pre-warming decisions for {len(trading_dates)} days "
          f"in batches of {batch_size}...")

    ai = create_ai_client(config, mode="intraday")
    cache_dir = os.path.join(output_dir, "cache", "batch_decisions")
    evaluator = BatchEvaluator(ai_client=ai, cache_dir=cache_dir)
    indicator_registry = IndicatorRegistry("indicators/")

    merged_cache: dict = {}

    # Split trading dates into batches
    batches = [
        trading_dates[i : i + batch_size]
        for i in range(0, len(trading_dates), batch_size)
    ]

    for batch_num, batch_dates in enumerate(batches, start=1):
        print(f"[BatchAI] Batch {batch_num}/{len(batches)}: {batch_dates[0]} to {batch_dates[-1]}")

        days_data = []
        for trade_date in batch_dates:
            day_candles = _get_day_candles_from_df(all_candles, trade_date)
            if day_candles is None or len(day_candles) < 5:
                continue

            # Compute indicators for this day
            try:
                df_std = day_candles.copy()
                df_std.columns = [c.lower() for c in df_std.columns]
                df_with_ind = indicator_registry.compute_all(
                    df_std,
                    ["ema", "rsi", "atr", "vwap"],
                    params_override={"ema": {"period": 20}, "rsi": {"period": 14}, "atr": {"period": 14}},
                )
            except Exception:
                df_with_ind = day_candles

            # Build candle list for the prompt
            candles_for_prompt = []
            for _, row in df_with_ind.iterrows():
                time_str = _extract_candle_time(row)
                rsi_val = _get_indicator(row, ["rsi_14", "rsi", "RSI"])
                ema_val = _get_indicator(row, ["ema_20", "ema20", "EMA_20"])
                vwap_val = _get_indicator(row, ["vwap", "VWAP"])
                atr_val = _get_indicator(row, ["atr_14", "atr", "ATR"])

                candles_for_prompt.append({
                    "time": time_str,
                    "open": _row_float(row, ["open", "Open"]),
                    "high": _row_float(row, ["high", "High"]),
                    "low": _row_float(row, ["low", "Low"]),
                    "close": _row_float(row, ["close", "Close"]),
                    "rsi": rsi_val,
                    "ema20": ema_val,
                    "vwap": vwap_val,
                    "atr": atr_val,
                    "pcr": 1.0,  # Not available in historical CSV — neutral default
                    "max_pain": None,
                })

            # Simple momentum thesis (same logic as _momentum_thesis, no AI needed)
            prior_candles = _get_candles_before_date(all_candles, trade_date, days=5)
            thesis = _compute_simple_thesis(prior_candles)

            days_data.append({
                "date": str(trade_date),
                "thesis": thesis,
                "candles": candles_for_prompt,
            })

        if not days_data:
            continue

        batch_cache = evaluator.evaluate_days(days_data)
        merged_cache.update(batch_cache)

    print(f"[BatchAI] Pre-warming complete. {len(merged_cache)} days cached.\n")
    return merged_cache


def _get_day_candles_from_df(all_candles: pd.DataFrame, trade_date) -> Optional[pd.DataFrame]:
    """Extract candles for a single date from the full DataFrame."""
    date_col = _find_date_column(all_candles)
    if date_col is None:
        return None
    mask = all_candles[date_col].apply(lambda x: _to_date(x) == trade_date)
    df = all_candles[mask].copy()
    return df if len(df) > 0 else None


def _get_candles_before_date(all_candles: pd.DataFrame, trade_date, days: int = 5) -> Optional[pd.DataFrame]:
    """Extract candles from the N days immediately before trade_date."""
    date_col = _find_date_column(all_candles)
    if date_col is None:
        return None
    prior_dates = sorted(set(
        _to_date(x) for x in all_candles[date_col] if _to_date(x) < trade_date
    ))[-days:]
    if not prior_dates:
        return None
    mask = all_candles[date_col].apply(lambda x: _to_date(x) in prior_dates)
    return all_candles[mask].copy()


def _compute_simple_thesis(prior_candles: Optional[pd.DataFrame]) -> dict:
    """Derive a momentum-based thesis from the last few days of candles."""
    if prior_candles is None or len(prior_candles) < 5:
        return {"direction": "NEUTRAL", "confidence": 0.3, "reasoning": "Insufficient prior data"}

    close_col = "close" if "close" in prior_candles.columns else "Close"
    try:
        closes = prior_candles[close_col].dropna()
        if len(closes) < 2:
            raise ValueError
        momentum_pct = (float(closes.iloc[-1]) - float(closes.iloc[0])) / float(closes.iloc[0]) * 100
        signal = max(-1.0, min(1.0, momentum_pct / 2.0))
        direction = "BULLISH" if signal > 0.15 else ("BEARISH" if signal < -0.15 else "NEUTRAL")
        confidence = round(min(abs(signal) * 1.5, 0.65), 2)
        return {
            "direction": direction,
            "confidence": confidence,
            "reasoning": f"{momentum_pct:+.2f}% momentum over prior days",
        }
    except Exception:
        return {"direction": "NEUTRAL", "confidence": 0.3, "reasoning": "Momentum calc failed"}


def _extract_candle_time(row) -> str:
    """Extract HH:MM time string from a candle row."""
    for key in ("datetime", "Datetime", "date", "Date"):
        val = row.get(key)
        if val is not None:
            try:
                return pd.Timestamp(val).strftime("%H:%M")
            except Exception:
                pass
    return "09:15"


def _get_indicator(row, keys: list):
    """Read first matching key from a row dict."""
    d = row.to_dict() if hasattr(row, "to_dict") else row
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                f = float(v)
                return round(f, 2) if not (f != f) else None  # NaN check
            except (TypeError, ValueError):
                pass
    return None


def _row_float(row, keys: list) -> float:
    """Read first matching key from a row as float."""
    d = row.to_dict() if hasattr(row, "to_dict") else row
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


# ─────────────────────────────────────────────────
#  Strategy signal gathering (no-AI mode)
# ─────────────────────────────────────────────────

def _gather_strategy_signals(loop, day_data, indicators, tick_time, filters, phase, strategy_filter):
    """
    Call each registered strategy's check_entry() and collect signals.
    Used in --no-ai mode instead of the AI evaluator.
    """
    from engine.state_machine import StateMachine

    if phase is None or "enter" not in phase.allowed_actions:
        return []

    # Strategies eligible at this time
    eligible = phase.eligible_strategies if phase.eligible_strategies != ["ALL"] else [
        "first_hour_verdict", "gap_fill", "gap_up_fade", "streak_fade",
        "bb_squeeze", "vwap_reversion", "afternoon_breakout",
    ]

    if strategy_filter:
        eligible = [s for s in eligible if s == strategy_filter]

    signals = []
    strategy_map = {
        "first_hour_verdict": ("strategies.first_hour_verdict", "FirstHourVerdict"),
        "gap_fill": ("strategies.gap_fill", "GapFill"),
        "gap_up_fade": ("strategies.gap_up_fade", "GapUpFade"),
        "streak_fade": ("strategies.streak_fade", "StreakFade"),
        "bb_squeeze": ("strategies.bb_squeeze", "BBSqueezeBreakout"),
        "vwap_reversion": ("strategies.vwap_reversion", "VWAPReversion"),
        "afternoon_breakout": ("strategies.afternoon_breakout", "AfternoonBreakout"),
        "theta_harvest": ("strategies.theta_harvest", "ThetaHarvest"),
    }

    for name in eligible:
        if name not in strategy_map:
            continue
        try:
            import importlib
            mod_path, cls_name = strategy_map[name]
            module = importlib.import_module(mod_path)
            cls = getattr(module, cls_name)
            strategy = cls({})
            signal = strategy.check_entry(
                day_data=day_data,
                lookback={},
                indicators=indicators,
                current_time=tick_time,
                filters=filters,
            )
            if signal is not None:
                signals.append(signal)
        except Exception:
            pass

    return signals


# ─────────────────────────────────────────────────
#  CSV loading helpers
# ─────────────────────────────────────────────────

def load_candle_csv(filepath: str) -> Optional[pd.DataFrame]:
    """
    Load and normalize a 5-minute candle CSV.

    Handles common column name variants, parses datetime column,
    sorts by datetime ascending.
    """
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        print(f"[Sim] CSV read error: {e}")
        return None

    # Normalize column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    # Find datetime column
    dt_candidates = ["datetime", "date", "timestamp", "time"]
    dt_col = next((c for c in dt_candidates if c in df.columns), None)
    if dt_col is None:
        print(f"[Sim] ERROR: No datetime column found. Columns: {list(df.columns)}")
        return None

    # Parse datetime
    df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
    df = df.dropna(subset=[dt_col])
    df = df.rename(columns={dt_col: "datetime"})

    # Normalize OHLCV columns
    col_map = {}
    for std, variants in {
        "open": ["open", "o"],
        "high": ["high", "h"],
        "low": ["low", "l"],
        "close": ["close", "c", "ltp"],
        "volume": ["volume", "vol", "v"],
    }.items():
        for v in variants:
            if v in df.columns and std not in col_map:
                col_map[v] = std
                break

    df = df.rename(columns=col_map)

    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"[Sim] ERROR: Missing columns after normalization: {missing}")
        print(f"[Sim] Available columns: {list(df.columns)}")
        return None

    # Sort ascending
    df = df.sort_values("datetime").reset_index(drop=True)

    print(f"[Sim] Loaded {len(df):,} candles from {df['datetime'].min()} to {df['datetime'].max()}")
    return df


def get_trading_dates(df: pd.DataFrame, from_date: Optional[str], to_date: Optional[str]) -> list:
    """Extract sorted list of unique trading dates within the specified range."""
    dates = df["datetime"].dt.date.unique()
    dates = sorted(dates)

    if from_date:
        fd = datetime.strptime(from_date, "%Y-%m-%d").date()
        dates = [d for d in dates if d >= fd]

    if to_date:
        td = datetime.strptime(to_date, "%Y-%m-%d").date()
        dates = [d for d in dates if d <= td]

    return dates


def _find_date_column(df: pd.DataFrame) -> Optional[str]:
    """Find the datetime column in a DataFrame."""
    for col in ("datetime", "date", "Datetime", "Date"):
        if col in df.columns:
            return col
    return None


def _to_date(val):
    """Convert a value to datetime.date."""
    # Call .date() on anything that has it (Timestamp, datetime) — returns a plain date object
    if hasattr(val, "date") and callable(val.date):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return val


# ─────────────────────────────────────────────────
#  Reporting helpers
# ─────────────────────────────────────────────────

def _strategy_breakdown(all_trades: list) -> list:
    """Compute per-strategy win rate and P&L from all trades."""
    by_strategy: dict = {}
    for t in all_trades:
        name = t.get("strategy", "unknown")
        if name not in by_strategy:
            by_strategy[name] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        by_strategy[name]["trades"] += 1
        pnl = t.get("net_pnl", 0)
        by_strategy[name]["total_pnl"] += pnl
        if pnl > 0:
            by_strategy[name]["wins"] += 1

    result = []
    for name, stats in by_strategy.items():
        t = stats["trades"]
        w = stats["wins"]
        result.append({
            "strategy": name,
            "trades": t,
            "wins": w,
            "win_rate_pct": round(w / t * 100, 1) if t else 0,
            "total_pnl": round(stats["total_pnl"], 2),
            "avg_pnl": round(stats["total_pnl"] / t, 2) if t else 0,
        })

    return sorted(result, key=lambda x: x["total_pnl"], reverse=True)


def _print_final_report(results: dict, trading_dates: list) -> None:
    """Print a formatted final report to the console."""
    if not results:
        print("\n[Sim] No results to report.")
        return

    perf = results.get("performance", {})
    period = results.get("period", {})

    print(f"\n{'='*60}")
    print(f"  JACK v3 SIMULATION RESULTS")
    print(f"{'='*60}")
    print(f"  Period:        {period.get('from')} -> {period.get('to')}")
    print(f"  Days traded:   {period.get('days_with_trades')} / {period.get('trading_days_simulated')}")
    print(f"")
    print(f"  Total P&L:     Rs.{perf.get('total_pnl', 0):>12,.0f}")
    print(f"  Return:        {perf.get('return_pct', 0):>11.2f}%")
    print(f"  Win Rate:      {perf.get('win_rate_pct', 0):>11.1f}%")
    print(f"  Total Trades:  {perf.get('total_trades', 0):>12}")
    print(f"  Avg Win:       Rs.{perf.get('avg_win', 0):>12,.0f}")
    print(f"  Avg Loss:      Rs.{perf.get('avg_loss', 0):>12,.0f}")
    print(f"  Max Drawdown:  {perf.get('max_drawdown_pct', 0):>10.2f}%")
    print(f"  Sharpe Ratio:  {perf.get('sharpe_ratio', 0):>12.3f}")
    print(f"  Final Capital: Rs.{perf.get('final_capital', 0):>12,.0f}")
    print(f"")

    breakdown = results.get("strategy_breakdown", [])
    if breakdown:
        print(f"  Strategy Breakdown:")
        print(f"  {'Strategy':<25} {'Trades':>7} {'Win%':>7} {'Total P&L':>12}")
        print(f"  {'-'*55}")
        for s in breakdown:
            print(f"  {s['strategy']:<25} {s['trades']:>7} {s['win_rate_pct']:>6.1f}% "
                  f"Rs.{s['total_pnl']:>11,.0f}")

    print(f"{'='*60}\n")


def _save_final_report(results: dict, output_dir: str) -> None:
    """Save the full results dict to a JSON file."""
    output_path = os.path.join(output_dir, "simulation_results.json")
    try:
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"[Sim] Full results saved to: {output_path}")
    except Exception as e:
        print(f"[Sim] Could not save results: {e}")


def _build_sim_config(config: dict, output_dir: str) -> dict:
    """Build a simulation-specific config with adjusted output paths."""
    import copy
    sim_config = copy.deepcopy(config)
    sim_config.setdefault("journal", {})
    sim_config["journal"]["output_dir"] = f"{output_dir}/journal"
    return sim_config


if __name__ == "__main__":
    main()
