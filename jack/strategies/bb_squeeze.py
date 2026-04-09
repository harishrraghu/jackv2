"""
Strategy D: BB Squeeze Breakout.

12:15 is the most reliably bullish hour (55%). BB squeeze in the dead zone
precedes breakout. Trades breakouts when Bollinger Bands tighten during the
lunch hour.

Parameters (4 of 5 budget):
    squeeze_threshold_pct: 25
    atr_target_multiplier: 1.0
    max_candles_to_confirm: 3
    prefer_long: True
"""

from typing import Optional

import numpy as np

from strategies.base import Strategy, TradeSignal, ExitSignal


class BBSqueezeBreakout(Strategy):
    """Trade BB squeeze breakouts during the lunch hour."""

    def __init__(self, params: dict = None):
        default_params = {
            "squeeze_threshold_pct": 25,
            "atr_target_multiplier": 1.0,
            "max_candles_to_confirm": 3,
            "prefer_long": True,
        }
        if params:
            default_params.update(params)

        super().__init__(name="bb_squeeze", params=default_params)
        self.required_indicators = ["bbands", "atr", "ema"]
        self.eligible_timeframes = ["12:15-14:15"]

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
        Check entry for BB squeeze breakout.

        Requires:
        1. BB_Width below squeeze_threshold_pct percentile (last 20 candles)
        2. Close breaks outside Bollinger Band
        """
        intraday_15m = indicators.get("intraday_15m", {})

        bb_width = intraday_15m.get("BB_Width")
        bb_upper = intraday_15m.get("BB_Upper")
        bb_lower = intraday_15m.get("BB_Lower")
        current_price = indicators.get("current_price", 0)

        if (bb_width is None or bb_upper is None or
                bb_lower is None or current_price <= 0):
            if diagnostics is not None: diagnostics["reason_skipped"] = "missing_data"
            return None

        # Check if in squeeze
        bb_width_history = intraday_15m.get("BB_Width_history", [])
        if len(bb_width_history) < 5:
            if diagnostics is not None: diagnostics["reason_skipped"] = "insufficient_history"
            return None

        threshold = np.percentile(bb_width_history, self.params["squeeze_threshold_pct"])
        
        is_squeeze = bb_width <= threshold
        if diagnostics is not None: diagnostics["base_condition_met"] = is_squeeze
        
        if not is_squeeze:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"no_squeeze_detected_bb_width_pctile>{self.params['squeeze_threshold_pct']}"
            return None  # Not in squeeze

        atr = indicators.get("daily", {}).get("ATR", 100)
        if atr <= 0:
            return None

        target_mult = self.params["atr_target_multiplier"]

        # Check for breakout
        if current_price > bb_upper:
            direction = "LONG"
            entry_price = current_price
            stop_loss = bb_lower
            target = entry_price + target_mult * atr
            confidence = 0.55

            # 12:15 bullish lean bonus
            if self.params["prefer_long"] and "12:15" <= current_time <= "13:00":
                confidence += 0.1

        elif current_price < bb_lower:
            direction = "SHORT"
            entry_price = current_price
            stop_loss = bb_upper
            target = entry_price - target_mult * atr
            confidence = 0.55

        else:
            if diagnostics is not None: diagnostics["reason_skipped"] = "no_breakout"
            return None  # No breakout

        if diagnostics is not None:
            diagnostics["signal_generated"] = True
            diagnostics["reason_skipped"] = None

        return TradeSignal(
            strategy_name=self.name,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            confidence=confidence,
            reason=(
                f"BB squeeze breakout {direction}: BB_Width={bb_width:.2f} "
                f"(threshold={threshold:.2f})"
            ),
            metadata={
                "bb_width": bb_width,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower,
                "atr": atr,
                "candles_since_breakout": 0,
            },
        )

    def check_exit(
        self,
        position: dict,
        day_data: dict,
        current_time: str,
        current_price: float,
    ) -> ExitSignal:
        """
        Check exit for BB squeeze positions.

        Exits: stop, target, no follow-through in 3 candles, time exit 15:15.
        """
        direction = position.get("direction", "LONG")
        stop_loss = position.get("stop_loss", 0)
        target = position.get("target", 0)
        max_candles = self.params["max_candles_to_confirm"]
        candles_elapsed = position.get("metadata", {}).get("candles_since_breakout", 0)

        # Time exit
        if current_time >= "15:15":
            return ExitSignal(
                should_exit=True,
                exit_price=current_price,
                reason="time_exit",
            )

        # No follow-through exit
        if candles_elapsed >= max_candles:
            entry_price = position.get("entry_price", 0)
            if direction == "LONG" and current_price <= entry_price:
                return ExitSignal(
                    should_exit=True,
                    exit_price=current_price,
                    reason="filter_exit",
                )
            elif direction == "SHORT" and current_price >= entry_price:
                return ExitSignal(
                    should_exit=True,
                    exit_price=current_price,
                    reason="filter_exit",
                )

        if direction == "LONG":
            if current_price <= stop_loss:
                return ExitSignal(
                    should_exit=True,
                    exit_price=stop_loss,
                    reason="stop_hit",
                )
            if current_price >= target:
                return ExitSignal(
                    should_exit=True,
                    exit_price=target,
                    reason="target_hit",
                )
        else:
            if current_price >= stop_loss:
                return ExitSignal(
                    should_exit=True,
                    exit_price=stop_loss,
                    reason="stop_hit",
                )
            if current_price <= target:
                return ExitSignal(
                    should_exit=True,
                    exit_price=target,
                    reason="target_hit",
                )

        return ExitSignal(should_exit=False, exit_price=current_price, reason="hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        """
        Score BB squeeze signal.

        First hour direction agrees: *1.2
        Daily trend agrees: *1.1
        Morning already moved > 1 ATR: *0.7 (exhaustion)
        """
        score = 0.55

        fh_direction = filters.get("fh_direction", 0)
        if signal.direction == "LONG" and fh_direction == 1:
            score *= 1.2
        elif signal.direction == "SHORT" and fh_direction == -1:
            score *= 1.2

        # Daily trend alignment
        ema_9 = filters.get("ema_9", 0)
        ema_21 = filters.get("ema_21", 0)
        if ema_9 and ema_21:
            if signal.direction == "LONG" and ema_9 > ema_21:
                score *= 1.1
            elif signal.direction == "SHORT" and ema_9 < ema_21:
                score *= 1.1

        # Morning exhaustion check
        morning_move = filters.get("morning_move_atr", 0)
        if morning_move > 1.0:
            score *= 0.7

        return min(score, 2.0)
