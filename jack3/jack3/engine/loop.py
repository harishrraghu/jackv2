"""
Jack v3 Main Trading Loop.

Orchestrates the full trading day from 08:45 pre-market research
to 15:35 post-market review. Runs every 5 minutes during market hours.

Timeline:
  08:45 -> Fetch pre-market dependent data
  08:50 -> AI news research (optional)
  08:55 -> Generate pre-market thesis via AI
  09:00 -> Load strategy rankings from lab
  09:15 -> Market opens. 5-minute tick loop begins.
  15:15 -> Force close all positions
  15:30 -> Loop ends
  15:35 -> Post-trade journal review
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yaml


class JackMainLoop:
    """
    The central orchestrator for Jack v3 intraday trading.

    Coordinates data ingestion, AI decision-making, risk management,
    order execution, and journaling across the full trading day.
    """

    def __init__(self, config_path: str = "config/settings.yaml", live: bool = False):
        self.config_path = config_path
        self.live = live

        # Load config
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.paper_mode = not live
        print(f"[Loop] Starting Jack v3 | Mode: {'LIVE' if live else 'PAPER'}")

        # Lazy imports -- all modules loaded after config
        self._init_components()

        # State
        self.thesis: dict = {}
        self.option_chain: dict = {}
        self.current_position: Optional[dict] = None
        self.trade_log: list = []
        self.daily_decisions: list = []
        self.tick_count: int = 0
        self._trade_date = None  # Set during simulation
        self._ticks_below_vwap: int = 0  # Consecutive ticks where price < VWAP

        # Simulation mode -- populated by run_simulation_day()
        self._sim_mode: bool = False
        self._sim_candles: Optional[pd.DataFrame] = None
        self._sim_trade_date = None  # datetime.date of current sim day

    def _init_components(self):
        """Initialize all system components."""
        from engine.risk import RiskManager
        from engine.state_machine import StateMachine
        from engine.scorer import StrategyScorer
        from engine.broker_dhan import DhanBroker
        from indicators.registry import IndicatorRegistry
        from journal.logger import JournalLogger

        dhan_cfg = self.config.get("dhan", {})
        client_id = os.environ.get("DHAN_CLIENT_ID", dhan_cfg.get("client_id", ""))
        access_token = os.environ.get("DHAN_ACCESS_TOKEN", dhan_cfg.get("access_token", ""))

        self.broker = DhanBroker(
            client_id=client_id,
            access_token=access_token,
            paper_mode=self.paper_mode,
        )

        self.risk = RiskManager(
            config={**self.config.get("trading", {}), "lot_size": self.config["market"]["lot_size"]}
        )
        self.state_machine = StateMachine()
        self.indicator_registry = IndicatorRegistry("indicators/")
        self.journal = JournalLogger(
            output_dir=self.config.get("journal", {}).get("output_dir", "journal/notes")
        )

        print("[Loop] All components initialized.")

    # ─────────────────────────────────────────────────
    #  PRE-MARKET (08:45 - 09:14)
    # ─────────────────────────────────────────────────

    def run_pre_market(self) -> dict:
        """Run all pre-market preparation steps. Returns context dict."""
        print("\n[Loop] === PRE-MARKET PHASE ===")
        context = {}

        # 08:45 -- Dependent data
        print("[Loop] 08:45 Fetching pre-market dependents...")
        try:
            from data.dependents import DependentsFetcher
            fetcher = DependentsFetcher(self.config.get("dependents", {}))
            context["dependents"] = fetcher.fetch_all()
            print(f"[Loop] Dependents bias: {context['dependents'].get('bias_direction', 'UNKNOWN')}")
        except Exception as e:
            print(f"[Loop] Dependents fetch failed: {e}")
            context["dependents"] = {"bias_direction": "NEUTRAL", "weighted_bias": 0.0}

        # 08:50 -- AI news research (optional, best-effort)
        print("[Loop] 08:50 Running AI news research...")
        try:
            from data.researcher import MarketResearcher
            from brain.ai_client import create_ai_client
            ai = create_ai_client(self.config, mode="nightly")
            researcher = MarketResearcher(ai)
            context["research"] = researcher.research()
            print(f"[Loop] Research sentiment: {context['research'].get('sentiment', 'N/A')}")
        except Exception as e:
            print(f"[Loop] Research skipped: {e}")
            context["research"] = {}

        # 08:55 -- Pre-market thesis
        print("[Loop] 08:55 Generating pre-market thesis...")
        try:
            from brain.thesis import ThesisGenerator
            from brain.ai_client import create_ai_client
            ai = create_ai_client(self.config, mode="intraday")
            recent_journal = self.journal.get_recent_entries(n=5)
            strategy_rankings = self._load_strategy_rankings()
            thesis_gen = ThesisGenerator(ai)
            self.thesis = thesis_gen.generate(
                dependents=context["dependents"],
                research=context.get("research", {}),
                recent_journal=recent_journal,
                strategy_rankings=strategy_rankings,
            )
            print(f"[Loop] Thesis: {self.thesis.get('direction')} | Confidence: {self.thesis.get('confidence')}")
        except Exception as e:
            print(f"[Loop] Thesis generation failed: {e}")
            bias = context["dependents"].get("bias_direction", "NEUTRAL")
            self.thesis = {
                "direction": bias,
                "confidence": 0.4,
                "reasoning": "Fallback: AI unavailable, using dependent bias",
                "key_factors": [],
                "suggested_strategy": None,
                "risk_note": "Low confidence -- AI thesis generation failed",
                "expected_range_pts": 300,
                "bias_entry_after": "10:15",
            }

        context["thesis"] = self.thesis
        return context

    # ─────────────────────────────────────────────────
    #  MAIN 5-MINUTE TICK LOOP (09:15 - 15:30)
    # ─────────────────────────────────────────────────

    def run_market_hours(self, pre_market_context: dict) -> None:
        """Run the 5-minute tick loop from 09:15 to 15:30."""
        print("\n[Loop] === MARKET HOURS PHASE ===")

        security_id = self.config["dhan"]["banknifty_index_id"]
        tick_minutes = self.config["market"]["tick_interval_minutes"]

        # Generate all tick times: 09:15, 09:20, ..., 15:30
        tick_times = self._generate_tick_times("09:15", "15:30", tick_minutes)

        for tick_time in tick_times:
            self.tick_count += 1
            self._run_one_tick(tick_time, security_id, pre_market_context)

            # Hard close at 15:15
            if tick_time >= "15:15" and self.current_position:
                print(f"[Loop] {tick_time} Force-closing position (time limit)")
                self._force_close_position(tick_time)

            # Stop trading if daily loss limit hit
            dd = self.risk.get_drawdown()
            if dd["daily_drawdown_pct"] >= self.config["trading"]["max_daily_loss_pct"]:
                print(f"[Loop] Daily loss limit hit ({dd['daily_drawdown_pct']:.2f}%). Stopping.")
                break

            # In live mode: sleep until next 5-minute mark
            if self.live:
                self._sleep_to_next_tick(tick_minutes)

        print("[Loop] Market hours complete.")

    def _run_one_tick(self, tick_time: str, security_id: str, context: dict) -> None:
        """Process one 5-minute tick."""
        _sim = getattr(self, "_sim_mode", False) or getattr(self, "_sim_candles", None) is not None
        if not _sim:
            print(f"\n[Loop] -- Tick {tick_time} --")

        # Step 1: Fetch latest candles
        candles_df = self._fetch_latest_candles(security_id, tick_time)
        if candles_df is None or len(candles_df) < 5:
            print(f"[Loop] {tick_time} Insufficient candle data, skipping tick")
            return

        current_candle = candles_df.iloc[-1].to_dict()
        current_price = float(current_candle.get("Close", current_candle.get("close", 0)))

        # Step 1b: Track consecutive ticks below VWAP (used for thesis override logic)
        indicators_preview = self._compute_indicators(candles_df)
        vwap_val = None
        for k, v in indicators_preview.items():
            if "vwap" in k.lower() and "upper" not in k.lower() and "lower" not in k.lower():
                try:
                    vwap_val = float(v)
                    break
                except (TypeError, ValueError):
                    pass
        if vwap_val and vwap_val > 0:
            if current_price < vwap_val:
                self._ticks_below_vwap += 1
            else:
                self._ticks_below_vwap = 0

        # Step 2: Every 3rd tick (15 min), refresh option chain from Dhan live API
        if self.tick_count % 3 == 0:
            try:
                self.option_chain = self.broker.get_option_chain(security_id)
            except Exception as e:
                print(f"[Loop] Option chain fetch failed: {e}")

        # Step 3: Reuse already-computed indicators
        indicators = indicators_preview

        # Step 4: Check stop loss / target hit on open position
        if self.current_position:
            if self._check_sl_target(current_price, tick_time):
                return  # Position was closed

        # Step 5: AI evaluation
        daily_pnl = self.risk.daily_pnl

        # Check batch cache first (set by historical simulator via --batch-ai)
        batch_cache = getattr(self, "_batch_decision_cache", {})
        batch_date = getattr(self, "_batch_decision_date", "")
        cached_decision = None
        if batch_cache and batch_date:
            day_cache = batch_cache.get(batch_date, {})
            cached_decision = day_cache.get(tick_time)

        if cached_decision:
            decision = cached_decision
        else:
            try:
                from brain.evaluator import Evaluator
                from brain.ai_client import create_ai_client
                ai = create_ai_client(self.config, mode="intraday")
                evaluator = Evaluator(ai)
                decision = evaluator.evaluate(
                    thesis=self.thesis,
                    current_candle=current_candle,
                    option_chain_summary=self._summarize_option_chain(),
                    open_position=self.current_position,
                    indicators=indicators,
                    time=tick_time,
                    daily_pnl=daily_pnl,
                    ticks_below_vwap=self._ticks_below_vwap,
                )
            except Exception as e:
                print(f"[Loop] AI evaluation failed: {e}")
                decision = {"action": "HOLD", "reasoning": f"AI error: {e}"}

        # Log decision
        decision["tick_time"] = tick_time
        decision["current_price"] = current_price
        self.daily_decisions.append(decision)

        # Step 6 + 7: Validate and execute
        action = decision.get("action", "HOLD")
        if not _sim:
            print(f"[Loop] {tick_time} AI action: {action} | {decision.get('reasoning', '')[:80]}")

        if action in ("ENTER_LONG", "ENTER_SHORT") and not self.current_position:
            self._attempt_entry(decision, action, tick_time, current_price)

        elif action == "EXIT" and self.current_position:
            self._execute_exit(current_price, tick_time, reason="ai_exit")

        elif action == "TIGHTEN_SL" and self.current_position:
            self._tighten_stop_loss(decision, tick_time)

        elif action == "HOLD":
            pass  # Nothing to do

    # ─────────────────────────────────────────────────
    #  Entry / Exit execution
    # ─────────────────────────────────────────────────

    def _attempt_entry(self, decision: dict, action: str, tick_time: str, current_price: float) -> None:
        """Validate AI entry decision and place order if valid."""
        direction = "LONG" if action == "ENTER_LONG" else "SHORT"
        entry_price = float(decision.get("entry_price", current_price))
        stop_loss = float(decision.get("stop_loss", 0))
        target = float(decision.get("target", 0))

        # ── VALIDATION GATE (hard-coded, AI cannot bypass) ──

        # 1. Must be in a valid trading phase for entries
        phase = self.state_machine.get_current_phase(tick_time) if tick_time < "15:00" else None
        if phase is None or "enter" not in phase.allowed_actions:
            print(f"[Loop] Entry blocked: not in entry phase at {tick_time}")
            return

        # 2. No entries after 15:00
        if tick_time >= "15:00":
            print(f"[Loop] Entry blocked: too late in session ({tick_time})")
            return

        # 3. SL must be within 1.5% of entry
        if entry_price > 0:
            sl_distance_pct = abs(entry_price - stop_loss) / entry_price * 100
            if sl_distance_pct > 1.5:
                print(f"[Loop] Entry rejected: SL too far ({sl_distance_pct:.2f}%) -- capping")
                stop_loss = entry_price * (0.985 if direction == "LONG" else 1.015)

        # 4. R:R must be > 1.0
        risk = abs(entry_price - stop_loss)
        reward = abs(target - entry_price)
        if risk > 0 and reward / risk < 1.0:
            print(f"[Loop] Entry rejected: R:R {reward/risk:.2f} < 1.0")
            return

        # 5. Daily loss limit
        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            print(f"[Loop] Entry blocked by risk: {reason}")
            return

        # ── POSITION SIZING ──
        quantity = self.risk.calculate_position_size(entry_price, stop_loss)
        if quantity == 0:
            print("[Loop] Entry rejected: insufficient capital for stop distance")
            return

        # ── PLACE ORDER ──
        security_id = self.config["dhan"]["banknifty_index_id"]
        try:
            order_id = self.broker.place_super_order(
                symbol=security_id,
                qty=quantity,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                target=target,
            )
        except Exception as e:
            print(f"[Loop] Order placement failed: {e}")
            return

        self.current_position = {
            "order_id": order_id,
            "direction": direction,
            "entry_price": entry_price,
            "entry_time": tick_time,
            "stop_loss": stop_loss,
            "target": target,
            "quantity": quantity,
            "strategy": decision.get("suggested_strategy", "ai_direct"),
            "reasoning": decision.get("reasoning", ""),
        }

        # Sync to risk manager so execute_exit() tracks P&L, peak capital, and stop-outs correctly
        self.risk.open_position = {
            **self.current_position,
            "original_entry": entry_price,
            "confidence": float(decision.get("confidence", 0.5)),
            "reason": decision.get("reasoning", ""),
            "metadata": {},
        }
        self.risk.trades_today += 1
        print(f"[Loop] Entered {direction} | {quantity} units @ {entry_price} | SL: {stop_loss} | TGT: {target}")

        # Journal entry
        self.journal.log_entry(
            tick_time=tick_time,
            position=self.current_position,
            thesis=self.thesis,
            indicators={},
            decision=decision,
        )

    def _execute_exit(self, exit_price: float, tick_time: str, reason: str = "ai_exit") -> None:
        """Close the current position via the risk manager (handles P&L, peak capital, stop-out tracking)."""
        if not self.current_position:
            return

        from strategies.base import ExitSignal

        # Ensure risk manager's open_position is in sync (may have been set at entry, but guard anyway)
        if self.risk.open_position is None:
            self.risk.open_position = {
                **self.current_position,
                "original_entry": self.current_position["entry_price"],
                "confidence": 0.5,
                "reason": self.current_position.get("reasoning", ""),
                "metadata": {},
            }

        exit_sig = ExitSignal(should_exit=True, exit_price=exit_price, reason=reason)
        trade_result = self.risk.execute_exit(exit_sig, exit_price)

        if "error" in trade_result:
            err = trade_result["error"]
            print(f"[Loop] Exit error from risk manager: {err} -- clearing position")
            self.current_position = None
            return

        trade_result["exit_time"] = tick_time
        # Carry over fields the risk manager doesn't set
        trade_result.setdefault("entry_time", self.current_position.get("entry_time"))
        trade_result.setdefault("order_id", self.current_position.get("order_id"))

        self.trade_log.append(trade_result)

        net_pnl = trade_result.get("net_pnl", 0)
        pnl_str = f"+{net_pnl:.0f}" if net_pnl >= 0 else f"{net_pnl:.0f}"
        direction_str = trade_result.get("direction")
        print(f"[Loop] EXIT {direction_str} @ {exit_price} | P&L: Rs.{pnl_str} | Reason: {reason}")

        self.journal.log_exit(trade_result=trade_result, thesis=self.thesis)
        self.current_position = None

    def _check_sl_target(self, current_price: float, tick_time: str) -> bool:
        """Check if SL or target was hit. Returns True if position was closed."""
        if not self.current_position:
            return False

        pos = self.current_position
        direction = pos["direction"]
        sl = pos["stop_loss"]
        target = pos["target"]

        if direction == "LONG":
            if current_price <= sl:
                self._execute_exit(sl, tick_time, reason="stop_hit")
                return True
            if current_price >= target:
                self._execute_exit(target, tick_time, reason="target_hit")
                return True
        else:
            if current_price >= sl:
                self._execute_exit(sl, tick_time, reason="stop_hit")
                return True
            if current_price <= target:
                self._execute_exit(target, tick_time, reason="target_hit")
                return True

        return False

    def _force_close_position(self, tick_time: str) -> None:
        """Force close any open position (time exit)."""
        if not self.current_position:
            return
        ltp = self.broker.get_ltp(self.config["dhan"]["banknifty_index_id"])
        if ltp == 0:
            ltp = self.current_position.get("entry_price", 0)
        self._execute_exit(ltp, tick_time, reason="time_exit")

    def _tighten_stop_loss(self, decision: dict, tick_time: str) -> None:
        """Tighten stop loss if AI recommends it (only allows moving SL in favorable direction)."""
        if not self.current_position:
            return

        new_sl = float(decision.get("stop_loss", 0))
        if new_sl == 0:
            return

        pos = self.current_position
        direction = pos["direction"]
        old_sl = pos["stop_loss"]

        # Validate: only allow tightening
        if direction == "LONG" and new_sl <= old_sl:
            print(f"[Loop] SL tighten rejected: new SL {new_sl} not better than {old_sl}")
            return
        if direction == "SHORT" and new_sl >= old_sl:
            print(f"[Loop] SL tighten rejected: new SL {new_sl} not better than {old_sl}")
            return

        try:
            self.broker.modify_stop_loss(pos["order_id"], new_sl)
            self.current_position["stop_loss"] = new_sl
            print(f"[Loop] SL tightened: {old_sl} -> {new_sl}")
        except Exception as e:
            print(f"[Loop] SL modify failed: {e}")

    # ─────────────────────────────────────────────────
    #  Post-market
    # ─────────────────────────────────────────────────

    def run_post_market(self, trade_date=None, skip_ai_review: bool = False) -> None:
        """Run post-market journal review.

        Args:
            trade_date: Date to log under. Defaults to today (for live mode).
            skip_ai_review: If True, skip the AI post-trade review (useful for fast simulation).
        """
        print("\n[Loop] === POST-MARKET PHASE ===")

        from datetime import date as date_cls
        log_date = trade_date if trade_date is not None else date_cls.today()

        total_pnl = sum(t.get("net_pnl", 0) for t in self.trade_log)
        wins = sum(1 for t in self.trade_log if t.get("net_pnl", 0) > 0)
        total = len(self.trade_log)

        print(f"[Loop] {log_date} P&L: Rs.{total_pnl:.0f} | Trades: {total} | Wins: {wins}")

        # Save daily summary to journal
        self.journal.log_day_summary(
            date=log_date,
            thesis=self.thesis,
            trades=self.trade_log,
            decisions=self.daily_decisions,
            capital_state=self.risk.get_state(),
        )

        # AI post-trade review (optional -- skip for fast simulation)
        if not skip_ai_review:
            try:
                from journal.reviewer import PostTradeReviewer
                from brain.ai_client import create_ai_client
                ai = create_ai_client(self.config, mode="nightly")
                reviewer = PostTradeReviewer(ai, self.journal)
                reviewer.review_today(
                    trades=self.trade_log,
                    thesis=self.thesis,
                    decisions=self.daily_decisions,
                )
                print("[Loop] Post-trade review complete.")
            except Exception as e:
                print(f"[Loop] Post-trade review failed: {e}")
    # ─────────────────────────────────────────────────
    #  Full day orchestration
    # ─────────────────────────────────────────────────


    # ─────────────────────────────────────────────────
    #  Simulation support
    # ─────────────────────────────────────────────────

    def reset_for_new_day(self, trade_date=None) -> None:
        """Reset all per-day state. Called between simulated trading days."""
        self.current_position = None
        self.trade_log = []
        self.daily_decisions = []
        self.tick_count = 0
        self.thesis = {}
        self.option_chain = {}
        self.risk.open_position = None
        self.risk.reset_daily()
        self._trade_date = trade_date
        self._ticks_below_vwap = 0

    def run_simulation_day(
        self,
        trade_date,
        day_candles_df: pd.DataFrame,
        pre_market_context: dict,
        skip_ai_review: bool = True,
        lookback_candles_df: pd.DataFrame = None,
    ) -> dict:
        """
        Run one complete trading day from a pre-loaded DataFrame.

        Args:
            trade_date: datetime.date for this trading day.
            day_candles_df: 5-minute OHLCV candles for this day only.
            pre_market_context: Dict with 'thesis', 'dependents', etc.
            skip_ai_review: Skip AI post-trade review (default True for speed).
            lookback_candles_df: Previous days' candles for indicator warmup.
                                 RSI(14)/EMA(20) need at least 20 prior candles.
                                 If not provided, indicators will be NaN early in the session.

        Returns:
            Day result dict: date, trades, daily_pnl, capital, thesis.
        """
        self.reset_for_new_day(trade_date=trade_date)
        self.thesis = pre_market_context.get("thesis", {})

        # Activate simulation mode -- _fetch_latest_candles reads from this DataFrame
        self._sim_mode = True
        self._sim_trade_date = trade_date  # Used by _fetch_latest_candles for datetime filter

        # Combine lookback candles (prior days) + today's candles for indicator warmup
        if lookback_candles_df is not None and len(lookback_candles_df) > 0:
            self._sim_candles = pd.concat([lookback_candles_df, day_candles_df], ignore_index=True)
        else:
            self._sim_candles = day_candles_df.copy()

        print(f"\n[Loop:Sim] -- {trade_date} | Thesis: {self.thesis.get('direction')} "
              f"({self.thesis.get('confidence', 0):.0%}) --")

        security_id = self.config["dhan"]["banknifty_index_id"]
        tick_minutes = self.config["market"]["tick_interval_minutes"]
        tick_times = self._generate_tick_times("09:15", "15:30", tick_minutes)

        for tick_time in tick_times:
            self.tick_count += 1
            self._run_one_tick(tick_time, security_id, pre_market_context)

            # Hard close at 15:15
            if tick_time >= "15:15" and self.current_position:
                self._force_close_position(tick_time)

            # Daily loss limit
            dd = self.risk.get_drawdown()
            if dd["daily_drawdown_pct"] >= self.config["trading"]["max_daily_loss_pct"]:
                print(f"[Loop:Sim] Daily loss limit hit. Stopping day.")
                break

        # Deactivate simulation mode
        self._sim_mode = False
        self._sim_candles = None

        # Post-market (with simulated date, optionally skip AI review for speed)
        self.run_post_market(trade_date=trade_date, skip_ai_review=skip_ai_review)

        daily_pnl = sum(t.get("net_pnl", 0) for t in self.trade_log)
        return {
            "date": str(trade_date),
            "trades": list(self.trade_log),
            "thesis": dict(self.thesis),
            "daily_pnl": round(daily_pnl, 2),
            "capital": self.risk.get_state(),
            "wins": sum(1 for t in self.trade_log if t.get("net_pnl", 0) > 0),
            "losses": sum(1 for t in self.trade_log if t.get("net_pnl", 0) <= 0 and t),
        }

    def run_full_day(self) -> dict:
        """Run the complete trading day. Entry point for scripts/run_live.py."""
        print("\n" + "=" * 60)
        print("  JACK v3 -- BankNifty Intraday AI Trader")
        print("=" * 60)

        # Pre-market
        if self.live:
            self._wait_until("08:45")
        pre_market_context = self.run_pre_market()

        # Market hours
        if self.live:
            self._wait_until("09:15")
        self.run_market_hours(pre_market_context)

        # Post-market
        if self.live:
            self._wait_until("15:35")
        self.run_post_market(skip_ai_review=False)

        return {
            "trades": self.trade_log,
            "thesis": self.thesis,
            "daily_pnl": sum(t.get("net_pnl", 0) for t in self.trade_log),
        }

    # ─────────────────────────────────────────────────
    #  Utilities
    # ─────────────────────────────────────────────────

    def _fetch_latest_candles(self, security_id: str, tick_time: str) -> Optional[pd.DataFrame]:
        """Fetch latest 5-minute candles. Uses simulation data if in sim mode, else calls Dhan."""
        # ── Simulation mode: return candles from pre-loaded DataFrame up to tick_time ──
        # _sim_candles contains a multi-day lookback (previous days for indicator warmup
        # plus today's candles up to the current tick). Filter by full datetime so RSI/EMA
        # have enough prior candles to warm up.
        if self._sim_mode and self._sim_candles is not None:
            df = self._sim_candles.copy()
            time_col = None
            for col in ("datetime", "Datetime", "date", "Date"):
                if col in df.columns:
                    time_col = col
                    break
            if time_col:
                df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
                # Keep: all rows from prior days + today's rows up to tick_time
                today = self._sim_trade_date  # set in run_simulation_day
                if today is not None:
                    today_ts = pd.Timestamp(today)
                    tick_dt = today_ts + pd.to_timedelta(
                        int(tick_time.split(":")[0]) * 60 + int(tick_time.split(":")[1]),
                        unit="m",
                    )
                    df = df[df[time_col] <= tick_dt]
                else:
                    # Fallback: time-only filter (less accurate)
                    df = df[df[time_col].dt.strftime("%H:%M") <= tick_time]
            df.columns = [c.capitalize() for c in df.columns]
            return df if len(df) >= 5 else None

        # ── Live/paper mode: fetch from Dhan ──
        try:
            df = self.broker.get_historical_intraday(
                security_id=security_id,
                interval=5,
                days_back=2,
            )
            if df is not None and len(df) > 0:
                df.columns = [c.capitalize() for c in df.columns]
                return df
        except Exception as e:
            print(f"[Loop] Candle fetch error: {e}")
        return None

    def _compute_indicators(self, df: pd.DataFrame) -> dict:
        """Compute key indicators on the candle DataFrame."""
        indicators = {}
        try:
            # Indicators expect capitalized OHLCV columns (Open, High, Low, Close, Volume)
            # VWAP also needs a 'Date' column (just the date portion, for daily reset)
            import pandas as _pd
            df_std = df.copy()
            # Normalize column names: capitalize OHLCV, keep Datetime as-is
            rename_map = {}
            for col in df_std.columns:
                cl = col.lower()
                if cl in ("open", "high", "low", "close", "volume"):
                    rename_map[col] = cl.capitalize()
                elif cl in ("datetime", "date", "timestamp"):
                    rename_map[col] = "Datetime"
            df_std = df_std.rename(columns=rename_map)
            # Add 'Date' column for VWAP daily reset
            if "Datetime" in df_std.columns and "Date" not in df_std.columns:
                df_std["Date"] = _pd.to_datetime(df_std["Datetime"]).dt.date

            result = self.indicator_registry.compute_all(
                df_std,
                ["ema", "rsi", "atr", "vwap"],
                params_override={"ema": {"period": 20}, "rsi": {"period": 14}, "atr": {"period": 14}},
            )

            # Extract latest values -- skip raw OHLCV columns
            ohlcv = {"Open", "High", "Low", "Close", "Volume", "Datetime", "open", "high", "low", "close", "volume", "date", "datetime"}
            last = result.iloc[-1]
            indicators = {k: v for k, v in last.items() if k not in ohlcv}
        except Exception as e:
            print(f"[Loop] Indicator computation failed: {e}")
        return indicators

    def _summarize_option_chain(self) -> dict:
        """Return a compact option chain summary for the AI prompt."""
        if not self.option_chain:
            return {}
        return {
            "last_price": self.option_chain.get("last_price"),
            "max_pain": self.option_chain.get("max_pain"),
            "pcr": self.option_chain.get("pcr"),
            "atm_iv": self.option_chain.get("atm_iv"),
            "atm_strike": self.option_chain.get("atm_strike"),
        }

    def _load_strategy_rankings(self) -> list:
        """Load strategy rankings from lab/rankings.json if it exists."""
        rankings_path = "lab/rankings.json"
        if os.path.exists(rankings_path):
            try:
                with open(rankings_path) as f:
                    return json.load(f).get("rankings", [])
            except Exception:
                pass
        return []

    def _generate_tick_times(self, start: str, end: str, interval_min: int) -> list:
        """Generate list of HH:MM tick times from start to end inclusive."""
        times = []
        h, m = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        while h * 60 + m <= eh * 60 + em:
            times.append(f"{h:02d}:{m:02d}")
            m += interval_min
            if m >= 60:
                h += 1
                m -= 60
        return times

    def _sleep_to_next_tick(self, interval_min: int) -> None:
        """Sleep until the next 5-minute boundary."""
        now = datetime.now()
        next_tick_seconds = interval_min * 60 - (now.second + now.minute % interval_min * 60)
        if next_tick_seconds > 0:
            print(f"[Loop] Sleeping {next_tick_seconds}s until next tick...")
            time.sleep(next_tick_seconds)

    def _wait_until(self, time_str: str) -> None:
        """Block until the given HH:MM time (IST)."""
        while True:
            now = datetime.now()
            h, m = map(int, time_str.split(":"))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                return
            print(f"[Loop] Waiting {remaining:.0f}s until {time_str}...")
            time.sleep(min(remaining, 30))
