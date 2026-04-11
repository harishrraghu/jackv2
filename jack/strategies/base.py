"""
Strategy base class and data classes for trade signals.

All trading strategies inherit from Strategy and implement:
- check_entry(): Returns TradeSignal or None
- check_exit(): Returns ExitSignal
- score(): Returns float for arbitration
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class TradeSignal:
    """Output of a strategy's check_entry method."""
    strategy_name: str
    direction: str          # "LONG" or "SHORT"
    entry_price: float      # Suggested entry price
    stop_loss: float        # Hard stop loss price
    target: float           # Take profit price
    confidence: float       # 0.0 to 1.0 — used by scorer for arbitration
    reason: str             # Human-readable explanation of why this trade triggered
    metadata: dict = field(default_factory=dict)  # Strategy-specific data


@dataclass
class ExitSignal:
    """Output of a strategy's check_exit method."""
    should_exit: bool
    exit_price: float
    reason: str             # "target_hit", "stop_hit", "time_exit", "trail_stop", "filter_exit", "partial_exit"
    partial_pct: Optional[float] = None  # E.g., 0.5 for 50% exit


class Strategy(ABC):
    """
    Abstract base class for all trading strategies.

    Subclasses must implement check_entry(), check_exit(), and score().
    Each strategy is capped at 5 tunable parameters to prevent overfitting.
    """

    def __init__(self, name: str, params: dict):
        """
        Initialize strategy.

        Args:
            name: Strategy identifier (e.g., "first_hour_verdict").
            params: Strategy parameters dict.
        """
        self.name = name
        self.params = params
        self.required_indicators: list[str] = []
        self.eligible_timeframes: list[str] = []
        self.max_params: int = 5  # Anti-overfit budget

    @abstractmethod
    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
        diagnostics: dict = None,
    ) -> Optional[TradeSignal]:
        """
        Check if entry conditions are met.

        Args:
            day_data: Today's candle data across all timeframes (from daily iterator).
            lookback: Historical data (from get_lookback) — N days before today.
            indicators: Pre-computed indicator values for today and lookback period.
            current_time: Current time in the simulation (e.g., "10:15").
            filters: Output of the filter stack (day_of_week bias, RSI filter, etc.).

        Returns:
            TradeSignal if entry conditions met, None otherwise.
        """
        pass

    @abstractmethod
    def check_exit(
        self,
        position: dict,
        day_data: dict,
        current_time: str,
        current_price: float,
    ) -> ExitSignal:
        """
        Check if an open position should be closed.

        Args:
            position: The open position dict (entry_price, stop_loss, target, etc.).
            day_data: Today's data.
            current_time: Current time.
            current_price: Current price (from the relevant candle).

        Returns:
            ExitSignal with should_exit=True/False and the reason.
        """
        pass

    @abstractmethod
    def score(self, signal: TradeSignal, filters: dict) -> float:
        """
        Score a trade signal for arbitration when multiple strategies trigger.

        Base score is signal.confidence. Modifiers applied by filter weights
        and regime assessment.

        Args:
            signal: The trade signal to score.
            filters: Filter stack output.

        Returns:
            Float 0.0 to 2.0. Higher = more conviction.
        """
        pass

    def validate_params(self) -> None:
        """
        Ensure strategy doesn't exceed the 5-parameter anti-overfit budget.

        Raises:
            ValueError: If more than max_params tunable parameters exist.
        """
        tunable = [k for k, v in self.params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(tunable) > self.max_params:
            raise ValueError(
                f"Strategy '{self.name}' has {len(tunable)} tunable params "
                f"(max {self.max_params}): {tunable}. Reduce to prevent overfitting."
            )

class PositionManager:
    """Manages position lifecycle with partial exits and adaptive stops."""
    
    def manage(self, position: dict, current_price: float, current_time: str, attr: float, day_type: str) -> Optional[ExitSignal]:
        """
        Checks adaptive rules and alters position.
        Returns Optional[ExitSignal] if a partial exit is triggered.
        """
        if not attr or attr <= 0:
            return None
        
        entry_price = position["entry_price"]
        direction = position["direction"]
        meta = position.setdefault("metadata", {})
        
        if direction == "LONG":
            profit = current_price - entry_price
        else:
            profit = entry_price - current_price
            
        # 1. Move stop to breakeven after 0.5 ATR profit
        if profit >= 0.5 * attr and not meta.get("breakeven_set"):
            meta["breakeven_set"] = True
            if direction == "LONG":
                position["stop_loss"] = max(position["stop_loss"], entry_price)
            else:
                position["stop_loss"] = min(position["stop_loss"], entry_price)
                
        # 2. Partial exit (50%) at 1.0 ATR
        if profit >= 1.0 * attr and not meta.get("partial_taken"):
            meta["partial_taken"] = True
            return ExitSignal(True, current_price, "partial_exit", partial_pct=0.5)
            
        # 3. Adjust targets based on day type
        if "adaptive_applied" not in meta:
            if day_type == "range":
                if direction == "LONG":
                    position["target"] -= 0.3 * attr
                else:
                    position["target"] += 0.3 * attr
            elif day_type in ("trend_up", "trend_down"):
                if direction == "LONG":
                    position["target"] += 0.5 * attr
                else:
                    position["target"] -= 0.5 * attr
            meta["adaptive_applied"] = True
            
        return None
