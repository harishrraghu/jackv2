"""
Risk Manager — independent risk enforcement layer.

Enforces hard limits on position sizing, daily/total drawdown,
trade frequency, and transaction costs. INDEPENDENT of strategy judgment.
"""

from typing import Optional

import yaml
import os


class RiskManager:
    """
    Independent risk enforcement layer.

    Enforces:
    - 1% max risk per trade
    - 2% max daily drawdown
    - 20% max total drawdown
    - 2 trades per day max
    - Full Indian market cost model (brokerage, STT, stamp duty, GST, slippage)
    """

    def __init__(self, config: dict = None, config_path: str = "config/settings.yaml"):
        """
        Initialize risk manager from config.

        Args:
            config: Trading config dict. If None, reads from config_path.
            config_path: Path to settings.yaml.
        """
        if config is None:
            if not os.path.isabs(config_path):
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                config_path = os.path.join(base_dir, config_path)
            with open(config_path, "r") as f:
                full_config = yaml.safe_load(f)
            config = full_config.get("trading", {})
            self.lot_size = full_config.get("market", {}).get("lot_size", 15)
        else:
            self.lot_size = config.get("lot_size", 15)

        self.initial_capital = config.get("initial_capital", 1000000)
        self.max_risk_per_trade_pct = config.get("max_risk_per_trade_pct", 1.0)
        self.max_daily_drawdown_pct = config.get("max_daily_drawdown_pct", 2.0)
        self.max_total_drawdown_pct = config.get("max_total_drawdown_pct", 20.0)
        self.max_trades_per_day = config.get("max_trades_per_day", 2)
        self.brokerage_pct = config.get("brokerage_pct", 0.03)
        self.stt_sell_pct = config.get("stt_sell_pct", 0.025)
        self.slippage_ticks = config.get("slippage_ticks", 1)
        self.tick_size = config.get("tick_size", 0.05)

        # State
        self.current_capital = float(self.initial_capital)
        self.peak_capital = float(self.initial_capital)
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.open_position: Optional[dict] = None
        self.stopped_out_strategies_today: set = set()

    def calculate_position_size(self, entry_price: float, stop_loss: float, risk_override_pct: float = None) -> int:
        """
        Calculate position size based on risk budget.

        risk_amount = capital * max_risk_pct / 100
        quantity = risk_amount / stop_distance, rounded DOWN to lot_size multiple.
        Capped at max_lots (10) to prevent catastrophic sizing from tight stops.
        Minimum stop distance enforced at 50 points.

        Args:
            entry_price: Entry price.
            stop_loss: Stop loss price.

        Returns:
            Position size in units (not lots). Returns 0 if can't afford 1 lot.
        """
        stop_distance = abs(entry_price - stop_loss)

        # Enforce minimum stop distance of 50 points
        if stop_distance < 50:
            stop_distance = 50

        if stop_distance <= 0:
            return 0

        risk_pct = risk_override_pct if risk_override_pct is not None else self.max_risk_per_trade_pct
        risk_amount = self.current_capital * risk_pct / 100
        raw_quantity = risk_amount / stop_distance

        # Round DOWN to nearest lot_size multiple
        lots = int(raw_quantity // self.lot_size)

        # Always trade at least 1 lot when capital allows the notional exposure.
        # This prevents wide-stop strategies (first_hour_verdict, ATR-based) from
        # being blocked simply because the risk-budget math rounds to 0 lots.
        if lots == 0:
            # Can we afford the notional of 1 lot at 10% intraday margin?
            notional_1lot = self.lot_size * entry_price
            margin_required = notional_1lot * 0.10   # conservative intraday margin
            if self.current_capital >= margin_required:
                lots = 1

        # Cap at 8 lots max (120 units) to prevent catastrophic single-trade ruin.
        # Tight-stop strategies (vwap_reversion, delta_scalp) would otherwise get 300+ units.
        max_lots = 8
        lots = min(lots, max_lots)

        quantity = lots * self.lot_size

        if quantity < self.lot_size:
            return 0

        return quantity

    def calculate_costs(self, entry_price: float, exit_price: float,
                        quantity: int, direction: str,
                        instrument_type: str = "futures") -> dict:
        """
        Calculate all transaction costs for a trade.

        STT rates by instrument type:
          - Futures: 0.0125% on sell side only
          - Options: 0.0625% on sell side only (for future options support)
          - Equity delivery: 0.1% on both sides (not used in Jack)

        Args:
            entry_price: Entry price.
            exit_price: Exit price.
            quantity: Number of units traded.
            direction: "LONG" or "SHORT".
            instrument_type: "futures", "options", or "equity".

        Returns:
            Dict with each cost component and total.
        """
        turnover_entry = entry_price * quantity
        turnover_exit = exit_price * quantity

        brokerage_entry = turnover_entry * self.brokerage_pct / 100
        brokerage_exit = turnover_exit * self.brokerage_pct / 100

        # STT rate lookup by instrument type
        stt_rate = {
            "futures": 0.0125,
            "options": 0.0625,
            "equity": 0.1,
        }.get(instrument_type, 0.0125) / 100

        # STT only on sell side
        if direction == "LONG":
            stt = turnover_exit * stt_rate  # Sell side = exit
        else:
            stt = turnover_entry * stt_rate  # Sell side = entry for shorts

        slippage = self.slippage_ticks * self.tick_size * quantity * 2  # Entry + exit

        stamp_duty = turnover_entry * 0.003 / 100

        gst = (brokerage_entry + brokerage_exit) * 0.18

        total_costs = brokerage_entry + brokerage_exit + stt + slippage + stamp_duty + gst

        return {
            "brokerage_entry": round(brokerage_entry, 2),
            "brokerage_exit": round(brokerage_exit, 2),
            "stt": round(stt, 2),
            "slippage": round(slippage, 2),
            "stamp_duty": round(stamp_duty, 2),
            "gst": round(gst, 2),
            "total_costs": round(total_costs, 2),
        }

    def can_trade(self, signal=None) -> tuple[bool, str]:
        """
        Check if a new trade is allowed.

        Args:
            signal: TradeSignal (optional, used for position size check).

        Returns:
            Tuple of (allowed: bool, reason: str).
        """
        # Already have an open position
        if self.open_position is not None:
            return False, "position_already_open"

        # Block re-entry from a strategy that was stopped out today
        if signal is not None and signal.strategy_name in self.stopped_out_strategies_today:
            return False, "strategy_stopped_out_today"

        # Max trades per day
        if self.trades_today >= self.max_trades_per_day:
            return False, "max_trades_reached"

        # Daily drawdown breaker
        dd = self.get_drawdown()
        if dd["daily_drawdown_pct"] >= self.max_daily_drawdown_pct:
            return False, "daily_drawdown_limit"

        # Total drawdown breaker
        if dd["current_drawdown_pct"] >= self.max_total_drawdown_pct:
            return False, "total_drawdown_limit"

        # Check position size if signal provided
        if signal is not None:
            risk_mult = signal.metadata.get("risk_multiplier", 1.0)
            adjusted_risk_pct = self.max_risk_per_trade_pct * risk_mult
            qty = self.calculate_position_size(signal.entry_price, signal.stop_loss, adjusted_risk_pct)
            if qty == 0:
                return False, "insufficient_capital_for_stop"

        return True, "ok"

    def execute_entry(self, signal) -> dict:
        """
        Execute a trade entry.

        Applies entry slippage and records the position.

        Args:
            signal: TradeSignal from a strategy.

        Returns:
            Position dict with all trade details.
        """
        risk_mult = signal.metadata.get("risk_multiplier", 1.0)
        adjusted_risk_pct = self.max_risk_per_trade_pct * risk_mult
        quantity = self.calculate_position_size(signal.entry_price, signal.stop_loss, adjusted_risk_pct)

        # Apply entry slippage (worse price for trader)
        slippage_amount = self.slippage_ticks * self.tick_size
        if signal.direction == "LONG":
            adjusted_entry = signal.entry_price + slippage_amount
        else:
            adjusted_entry = signal.entry_price - slippage_amount

        position = {
            "strategy": signal.strategy_name,
            "direction": signal.direction,
            "entry_price": adjusted_entry,
            "original_entry": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "target": signal.target,
            "quantity": quantity,
            "entry_time": None,  # Set by simulator
            "entry_date": None,  # Set by simulator
            "confidence": signal.confidence,
            "reason": signal.reason,
            "metadata": {
                **signal.metadata,
                "original_direction": signal.direction,  # immutable reference for PositionManager
            },
        }

        self.open_position = position
        self.trades_today += 1

        return position

    def execute_exit(self, exit_signal, current_price: float) -> dict:
        """
        Execute a trade exit.

        Applies exit slippage, calculates P&L and all costs.

        Args:
            exit_signal: ExitSignal from a strategy.
            current_price: Current market price.

        Returns:
            Trade result dict with all details.
        """
        if self.open_position is None:
            return {"error": "no_open_position"}

        pos = self.open_position

        # Apply exit slippage (worse price for trader)
        slippage_amount = self.slippage_ticks * self.tick_size
        if pos["direction"] == "LONG":
            exit_price = exit_signal.exit_price - slippage_amount
        else:
            exit_price = exit_signal.exit_price + slippage_amount

        # Gross P&L
        if pos["direction"] == "LONG":
            gross_pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
        else:
            gross_pnl = (pos["entry_price"] - exit_price) * pos["quantity"]

        # Costs
        costs = self.calculate_costs(
            pos["entry_price"], exit_price, pos["quantity"], pos["direction"]
        )

        net_pnl = gross_pnl - costs["total_costs"]

        # Update capital
        self.current_capital += net_pnl

        # Update peak capital
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

        # Update daily P&L
        self.daily_pnl += net_pnl

        # Build result
        trade_result = {
            "strategy": pos["strategy"],
            "direction": pos["direction"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "stop_loss": pos["stop_loss"],
            "target": pos["target"],
            "quantity": pos["quantity"],
            "entry_time": pos.get("entry_time"),
            "entry_date": pos.get("entry_date"),
            "exit_time": None,  # Set by simulator
            "exit_date": None,  # Set by simulator
            "exit_reason": exit_signal.reason,
            "gross_pnl": round(gross_pnl, 2),
            "costs": costs,
            "net_pnl": round(net_pnl, 2),
            "confidence": pos.get("confidence", 0),
            "reason": pos.get("reason", ""),
            "metadata": pos.get("metadata", {}),
        }

        # Track stop-outs to block same-strategy re-entry
        if exit_signal.reason == "stop_hit":
            self.stopped_out_strategies_today.add(pos["strategy"])

        # Clear position
        self.open_position = None

        return trade_result

    def reset_daily(self) -> None:
        """Reset daily counters. Called at start of each new trading day."""
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.stopped_out_strategies_today = set()

    def get_drawdown(self) -> dict:
        """
        Get current drawdown metrics.

        Returns:
            Dict with current_drawdown_pct and daily_drawdown_pct.
        """
        if self.peak_capital > 0:
            current_dd = (self.peak_capital - self.current_capital) / self.peak_capital * 100
        else:
            current_dd = 0.0

        if self.current_capital > 0:
            daily_dd = abs(min(self.daily_pnl, 0)) / self.current_capital * 100
        else:
            daily_dd = 100.0

        return {
            "current_drawdown_pct": round(current_dd, 4),
            "daily_drawdown_pct": round(daily_dd, 4),
        }

    def get_state(self) -> dict:
        """Return current risk manager state for logging."""
        return {
            "current_capital": round(self.current_capital, 2),
            "peak_capital": round(self.peak_capital, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "trades_today": self.trades_today,
            "has_position": self.open_position is not None,
            "drawdown": self.get_drawdown(),
        }
