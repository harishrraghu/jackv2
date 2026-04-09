"""
Strategy B: Gap Fill.

Small gap-downs (0.1-0.5%) fill 81.5% of the time.
First 15-min candle must be bullish for confirmation.

Parameters (4 of 5 budget):
    min_gap_pct: 0.1
    max_gap_pct: 0.5
    stop_buffer_pts: 20
    max_hold_time: "11:00"
"""

from typing import Optional

from strategies.base import Strategy, TradeSignal, ExitSignal


class GapFill(Strategy):
    """Trade gap-down fills with bullish ORB confirmation."""

    def __init__(self, params: dict = None):
        default_params = {
            "min_gap_pct": 0.1,
            "max_gap_pct": 0.5,
            "stop_buffer_pts": 20,
            "max_hold_time": "11:00",
        }
        if params:
            default_params.update(params)

        super().__init__(name="gap_fill", params=default_params)
        self.required_indicators = ["gap", "orb", "rsi"]
        self.eligible_timeframes = ["09:30-10:15"]

    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
    ) -> Optional[TradeSignal]:
        """
        Check entry for gap fill.

        Requires: small gap-down + bullish first 15m candle.
        """
        gap = indicators.get("gap", {})
        orb = indicators.get("orb", {})

        gap_type = gap.get("Gap_Type", "flat")
        gap_pct = gap.get("Gap_Pct", 0)

        # Must be a small gap down
        if gap_type != "small_down":
            return None

        # Block entry in losing regimes identified by AI Retrospective
        regime = filters.get("regime", "normal")
        if regime in ["ranging", "squeeze", "trending_weak"]:
            return None

        # Verify gap size is within range
        abs_gap = abs(gap_pct)
        if abs_gap < self.params["min_gap_pct"] or abs_gap > self.params["max_gap_pct"]:
            return None

        # First 15m candle must be bullish
        orb_bullish = orb.get("ORB_Bullish", False)
        if not orb_bullish:
            return None

        orb_low = orb.get("ORB_Low", 0)
        current_price = indicators.get("current_price", 0)
        prev_close = gap.get("prev_close", 0)

        if current_price <= 0 or prev_close <= 0:
            return None

        entry_price = current_price
        stop_loss = orb_low - self.params["stop_buffer_pts"]
        target = prev_close  # Gap fill level

        # Not enough reward (increased from 20 to 40 to overcome fixed costs)
        if target - entry_price < 40:
            return None

        return TradeSignal(
            strategy_name=self.name,
            direction="LONG",
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            confidence=0.75,
            reason=(
                f"Gap fill setup: gap={gap_pct:.2f}%, "
                f"ORB bullish, target=prev close ({prev_close:.0f})"
            ),
            metadata={
                "gap_pct": gap_pct,
                "gap_type": gap_type,
                "orb_low": orb_low,
                "prev_close": prev_close,
                "risk_multiplier": 0.5,  # scale down risk to reduce quantity/costs
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
        Check exit for gap fill positions.

        Exits: stop, target, time exit at max_hold_time, extended target.
        """
        stop_loss = position.get("stop_loss", 0)
        target = position.get("target", 0)
        prev_close = position.get("metadata", {}).get("prev_close", target)
        max_hold = self.params["max_hold_time"]

        # Time exit
        if current_time >= max_hold:
            return ExitSignal(
                should_exit=True,
                exit_price=current_price,
                reason="time_exit",
            )

        # Stop loss
        if current_price <= stop_loss:
            return ExitSignal(
                should_exit=True,
                exit_price=stop_loss,
                reason="stop_hit",
            )

        # Target hit (gap filled)
        if current_price >= target:
            # Extended: if price goes 50pts beyond prev close, trail stop
            if current_price >= prev_close + 50:
                return ExitSignal(
                    should_exit=True,
                    exit_price=current_price,
                    reason="target_hit",
                )
            return ExitSignal(
                should_exit=True,
                exit_price=target,
                reason="target_hit",
            )

        return ExitSignal(should_exit=False, exit_price=current_price, reason="hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        """
        Score gap fill signal.

        Friday: *1.2 (bullish day + gap fill confluence)
        Tuesday: *0.5 (bearish day kills the edge)
        """
        score = 0.75

        day = filters.get("day_of_week", "")
        if day == "Friday":
            score *= 1.2
        elif day == "Tuesday":
            score *= 0.5

        # High RSI + long bear streak = trend too strong against us
        rsi = filters.get("daily_rsi", 50)
        bear_streak = filters.get("bear_streak", 0)
        if rsi < 35 and bear_streak > 3:
            score *= 0.6

        return min(score, 2.0)
