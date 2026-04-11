"""Tests for engine components: filters, state machine, risk manager, scorer."""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.filters import (
    day_of_week_filter, rsi_extreme_filter, volatility_filter,
    streak_filter, expiry_filter, run_filter_stack,
)
from engine.state_machine import StateMachine
from engine.risk import RiskManager
from engine.scorer import StrategyScorer
from strategies.base import TradeSignal, Strategy


# ═══════════ FILTER TESTS ═══════════

class TestFilters:
    def test_tuesday_bearish(self):
        """Tuesday should penalize longs."""
        result = day_of_week_filter(pd.Timestamp("2020-01-07"))  # Tuesday
        assert result["long_multiplier"] == 0.6
        assert result["short_multiplier"] == 1.3

    def test_friday_bullish(self):
        """Friday should encourage longs."""
        result = day_of_week_filter(pd.Timestamp("2020-01-10"))  # Friday
        assert result["long_multiplier"] == 1.3
        assert result["short_multiplier"] == 0.7

    def test_rsi_overbought(self):
        """Overbought RSI should discourage longs."""
        result = rsi_extreme_filter(80, 75)
        assert result["long_multiplier"] == 0.5

    def test_rsi_normal(self):
        """Normal RSI should be neutral."""
        result = rsi_extreme_filter(50, 50)
        assert result["long_multiplier"] == 1.0

    def test_streak_3_bull(self):
        """3+ bull streak should discourage longs."""
        result = streak_filter(3, 0)
        assert result["long_multiplier"] == 0.4

    def test_combined_stack(self):
        """Test that combined multiplier is computed correctly."""
        date = pd.Timestamp("2020-01-07")  # Tuesday
        result = run_filter_stack(
            date,
            lookback_daily={"Bull_Streak": 0, "Bear_Streak": 0, "avg_ATR_60d": 400},
            indicators={"RSI": 50, "hourly_RSI": 50, "ATR": 400},
        )
        assert "combined_long_multiplier" in result
        assert "combined_short_multiplier" in result
        # Tuesday: long=0.6, other filters neutral = 0.6
        assert result["combined_long_multiplier"] < 1.0

    def test_extreme_atr_blocks_trading(self):
        """ATR > 3x average should block trading entirely."""
        date = pd.Timestamp("2020-01-07")
        result = run_filter_stack(
            date,
            lookback_daily={"Bull_Streak": 0, "Bear_Streak": 0, "avg_ATR_60d": 100},
            indicators={"RSI": 50, "hourly_RSI": 50, "ATR": 350},
        )
        assert result["trade_blocked"] is True
        assert result["combined_long_multiplier"] == 0.0

    def test_extreme_atr_half_size(self):
        """ATR 2x-3x average should halve position size."""
        date = pd.Timestamp("2020-01-07")
        # Tuesday -> long_multiplier = 0.6. Volatility filter -> 0.9. Extreme vol -> 0.5.
        # Total with weights [1.5, 1.2, 1.0, 1.0, 0.8]:
        # (0.6*1.5 + 1.0*1.2 + 0.9*1.0 + 1.0*1.0 + 1.0*0.8) / 5.5 = 4.8 / 5.5 = 0.8727
        # 0.8727 * 0.5 (ext_vol) = 0.4364
        result = run_filter_stack(
            date,
            lookback_daily={"Bull_Streak": 0, "Bear_Streak": 0, "avg_ATR_60d": 100},
            indicators={"RSI": 50, "hourly_RSI": 50, "ATR": 250},
        )
        assert result["trade_blocked"] is False
        assert result["combined_long_multiplier"] == 0.4364


# ═══════════ STATE MACHINE TESTS ═══════════

class TestStateMachine:
    def setup_method(self):
        self.sm = StateMachine()

    def test_pre_market(self):
        phase = self.sm.get_current_phase("09:10")
        assert phase.name == "pre_market"

    def test_opening_observation(self):
        phase = self.sm.get_current_phase("09:20")
        assert phase.name == "opening_observation"

    def test_morning_setups(self):
        phase = self.sm.get_current_phase("09:35")
        assert phase.name == "morning_setups"

    def test_gap_fill_can_enter_morning(self):
        """gap_fill can enter at 09:35."""
        assert self.sm.can_enter("09:35", "gap_fill") is True

    def test_gap_fill_cannot_enter_afternoon(self):
        """gap_fill cannot enter at 10:30."""
        assert self.sm.can_enter("10:30", "gap_fill") is False

    def test_first_hour_can_enter_at_1020(self):
        """first_hour_verdict can enter at 10:20."""
        assert self.sm.can_enter("10:20", "first_hour_verdict") is True

    def test_first_hour_cannot_enter_at_0930(self):
        """first_hour_verdict cannot enter at 09:30."""
        assert self.sm.can_enter("09:30", "first_hour_verdict") is False

    def test_must_exit_at_1505(self):
        """Must exit all at 15:05."""
        assert self.sm.must_exit_all("15:05") is True

    def test_no_must_exit_at_1400(self):
        """No forced exit at 14:00."""
        assert self.sm.must_exit_all("14:00") is False


# ═══════════ RISK MANAGER TESTS ═══════════

class TestRiskManager:
    def setup_method(self):
        self.rm = RiskManager(config={
            "initial_capital": 1000000,
            "max_risk_per_trade_pct": 1.0,
            "max_daily_drawdown_pct": 2.0,
            "max_total_drawdown_pct": 20.0,
            "max_trades_per_day": 2,
            "brokerage_pct": 0.03,
            "stt_sell_pct": 0.025,
            "slippage_ticks": 1,
            "tick_size": 0.05,
            "lot_size": 15,
        })

    def test_position_sizing(self):
        """Test position sizing with known values."""
        # 10L capital, 1% risk = 10,000 risk
        # Entry 48000, Stop 47800 = 200pt stop
        # Qty = 10000 / 200 = 50, rounded to 15-lot = 45
        qty = self.rm.calculate_position_size(48000, 47800)
        assert qty == 45  # Floor(50/15)*15

    def test_position_sizing_round_down(self):
        """Test that position sizing rounds DOWN to lot size."""
        # 10L, 1% risk = 10,000
        # Stop = 100pts, qty = 100, rounded to 15-lot = 90
        qty = self.rm.calculate_position_size(48000, 47900)
        assert qty % 15 == 0
        assert qty == 90  # Floor(100/15)*15 = 90

    def test_max_trades_blocks(self):
        """Test that can_trade blocks after max trades."""
        self.rm.trades_today = 2
        can, reason = self.rm.can_trade()
        assert can is False
        assert reason == "max_trades_reached"

    def test_daily_drawdown_blocks(self):
        """Test daily drawdown circuit breaker."""
        # Simulate 2% daily loss
        self.rm.daily_pnl = -20000  # 2% of 1M
        can, reason = self.rm.can_trade()
        assert can is False
        assert reason == "daily_drawdown_limit"

    def test_same_strategy_blocked_after_stopout(self):
        """Test same strategy is blocked from re-entering after stop-out."""
        signal = TradeSignal(
            strategy_name="test_strategy", direction="LONG",
            entry_price=48000, stop_loss=47800, target=48400,
            confidence=0.8, reason="test"
        )
        # Entry
        pos = self.rm.execute_entry(signal)
        # Exit with stop_hit
        from strategies.base import ExitSignal
        exit_sig = ExitSignal(should_exit=True, exit_price=47800, reason="stop_hit")
        self.rm.execute_exit(exit_sig, 47800)
        
        # Try to re-enter
        can, reason = self.rm.can_trade(signal)
        assert can is False
        assert reason == "strategy_stopped_out_today"

    def test_cost_calculation(self):
        """Test cost calculation with 0.0125% futures STT."""
        costs = self.rm.calculate_costs(48000, 48500, 30, "LONG", instrument_type="futures")
        assert costs["total_costs"] > 0
        # Sell turnover = 48500 * 30 = 1,455,000. STT @ 0.0125% = 181.875 -> ~181.88
        assert abs(costs["stt"] - 181.88) < 0.1

    def test_cost_calculation_options_stt(self):
        """Test options STT rate calculation."""
        costs = self.rm.calculate_costs(400, 500, 1500, "LONG", instrument_type="options")
        # Sell turnover = 500 * 1500 = 750,000. STT @ 0.0625% = 468.75
        assert abs(costs["stt"] - 468.75) < 0.1

    def test_slippage_direction(self):
        """Test slippage is applied in correct direction (worse for trader)."""
        signal = TradeSignal(
            strategy_name="test", direction="LONG",
            entry_price=48000, stop_loss=47800,
            target=48400, confidence=0.8, reason="test",
        )
        pos = self.rm.execute_entry(signal)
        # LONG: entry should be higher (worse for buyer)
        assert pos["entry_price"] > 48000


# ═══════════ SCORER TESTS ═══════════

class TestScorer:
    def setup_method(self):
        # Simple mock strategy
        class MockStrategy(Strategy):
            def __init__(self):
                super().__init__("mock", {})
            def check_entry(self, *args, **kwargs):
                return None
            def check_exit(self, *args, **kwargs):
                from strategies.base import ExitSignal
                return ExitSignal(False, 0, "hold")
            def score(self, signal, filters):
                return signal.confidence

        self.scorer = StrategyScorer({"mock": MockStrategy()})

    def test_single_signal_above_threshold(self):
        """Single signal above threshold should be selected."""
        signal = TradeSignal(
            strategy_name="mock", direction="LONG",
            entry_price=48000, stop_loss=47800,
            target=48400, confidence=0.8, reason="test",
        )
        filters = {"combined_long_multiplier": 1.0, "combined_short_multiplier": 1.0}
        result = self.scorer.select_trade([signal], filters)
        assert result is not None
        assert result.strategy_name == "mock"

    def test_single_signal_below_threshold(self):
        """Signal below threshold should return None."""
        signal = TradeSignal(
            strategy_name="mock", direction="LONG",
            entry_price=48000, stop_loss=47800,
            target=48400, confidence=0.3, reason="test",
        )
        filters = {"combined_long_multiplier": 1.0, "combined_short_multiplier": 1.0}
        result = self.scorer.select_trade([signal], filters)
        assert result is None

    def test_filter_multiplier_applied(self):
        """Tuesday + LONG should reduce the score."""
        signal = TradeSignal(
            strategy_name="mock", direction="LONG",
            entry_price=48000, stop_loss=47800,
            target=48400, confidence=0.6, reason="test",
        )
        # Tuesday penalizes longs
        filters = {"combined_long_multiplier": 0.6, "combined_short_multiplier": 1.3}
        scored = self.scorer.score_signals([signal], filters)
        assert scored[0][1] < 0.6  # Score reduced by filter


# ═══════════ SIMULATOR TESTS ═══════════

class TestSimulator:
    def test_sharpe_from_equity_known_curve(self):
        """Test daily Sharpe ratio calculation over a known equity curve including flat days."""
        from engine.simulator import Simulator
        import math
        import numpy as np
        
        sim = Simulator(config_path="config/settings.yaml")
        # create synthetic equity curve
        # flat daily returns: 0, 0.01, -0.005, 0 (4 daily returns from 5 valid days)
        eq = [
            ("2024-01-01", 1000000),
            ("2024-01-02", 1000000),  # 0%
            ("2024-01-03", 1010000),  # +1%
            ("2024-01-04", 1004950),  # -0.5%
            ("2024-01-05", 1004950)   # 0%
        ]
        sharpe = sim._compute_sharpe_from_equity(eq, risk_free_annual=0.0)
        
        returns = np.array([0, 0.01, -0.005, 0])
        mean_ret = np.mean(returns)
        std_ret = np.std(returns, ddof=1)
        expected = (mean_ret / std_ret) * math.sqrt(252)
        assert abs(sharpe - expected) < 0.01
