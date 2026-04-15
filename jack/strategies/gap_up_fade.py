"""
Strategy E: Large Gap-Up Fade.

Large gap-ups (>0.5%) average -0.30% day return. Only 44.4% fill.
Wait for bearish confirmation in first 15m candle before shorting.

Parameters (4 of 5 budget):
    min_gap_up_pct: 0.75
    partial_target_ratio: 0.6
    atr_stop_multiplier: 1.0
    max_hold_time: "11:30"
"""

from typing import Optional

from strategies.base import Strategy, TradeSignal, ExitSignal


class GapUpFade(Strategy):
    """Fade large gap-ups with bearish confirmation."""

    def __init__(self, params: dict = None):
        default_params = {
            "min_gap_up_pct": 0.75,
            "partial_target_ratio": 0.6,
            "atr_stop_multiplier": 1.0,
            "max_hold_time": "11:30",
        }
        if params:
            default_params.update(params)

        super().__init__(name="gap_up_fade", params=default_params)
        self.required_indicators = ["gap", "orb", "rsi", "ema", "adx", "atr"]
        self.eligible_timeframes = ["09:30-10:15"]

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
        Check entry for gap-up fade.

        Requires: gap > 0.5% AND bearish first 15m candle.
        If both first two 15m candles are bullish -> NO TRADE (breakaway gap).
        """
        gap = indicators.get("gap", {})
        orb = indicators.get("orb", {})
        daily = indicators.get("daily", {})

        gap_pct = gap.get("Gap_Pct", 0)
        gap_type = gap.get("Gap_Type", "flat")

        base_condition = gap_pct >= self.params["min_gap_up_pct"]
        if diagnostics is not None: diagnostics["base_condition_met"] = base_condition

        # Must be a large gap up
        if gap_type != "large_up":
            if diagnostics is not None: diagnostics["reason_skipped"] = f"gap_type={gap_type}_not_large_up"
            return None

        if not base_condition:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"gap_pct_below_threshold"
            return None

        # Trend filter to prevent fading gap-ups in strong bull runs
        ema_9 = daily.get("EMA_9")
        ema_21 = daily.get("EMA_21")
        adx = daily.get("ADX")
        if ema_9 is not None and ema_21 is not None and adx is not None:
            if ema_9 > ema_21 * 1.003 and adx > 28:
                return None

        # Check first 15m candle for bearish confirmation
        # Ignore second candle fallback, require first to be bearish
        first_candle_bearish = not orb.get("ORB_Bullish", True)
        if not first_candle_bearish:
            if diagnostics is not None: diagnostics["reason_skipped"] = "first_candle_bullish"
            return None

        current_price = indicators.get("current_price", 0)
        day_high = indicators.get("day_high", current_price)
        prev_close = gap.get("prev_close", 0)

        if current_price <= 0 or prev_close <= 0:
            return None

        atr = daily.get("ATR")
        if atr is None or atr <= 0:
            return None

        gap_size = current_price - prev_close
        partial_ratio = self.params["partial_target_ratio"]

        entry_price = current_price
        stop_loss = entry_price + (atr * self.params["atr_stop_multiplier"])
        target_1 = entry_price - (gap_size * partial_ratio)  # Partial gap fill
        target_2 = prev_close  # Full gap fill

        # R:R check using primary target
        risk = stop_loss - entry_price
        reward = entry_price - target_1
        if risk <= 0 or (reward / risk) < 1.5:
            if diagnostics is not None: diagnostics["reason_skipped"] = "poor_rr"
            return None

        if diagnostics is not None:
            diagnostics["signal_generated"] = True
            diagnostics["reason_skipped"] = None

        return TradeSignal(
            strategy_name=self.name,
            direction="SHORT",
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target_1,  # Use partial target as primary
            confidence=0.62,
            reason=(
                f"Gap-up fade: gap={gap_pct:.2f}%, "
                f"bearish confirmation, target fill={target_1:.0f}"
            ),
            metadata={
                "gap_pct": gap_pct,
                "gap_size": gap_size,
                "prev_close": prev_close,
                "target_1": target_1,
                "target_2": target_2,
                "day_high": day_high,
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
        Check exit for gap-up fade positions.

        Partial target (half gap fill), full target, stop, time exit.
        """
        stop_loss = position.get("stop_loss", 0)
        target_1 = position.get("metadata", {}).get("target_1", position.get("target", 0))
        target_2 = position.get("metadata", {}).get("target_2", 0)
        max_hold = self.params["max_hold_time"]

        # Time exit
        if current_time >= max_hold:
            return ExitSignal(
                should_exit=True,
                exit_price=current_price,
                reason="time_exit",
            )

        # Stop loss
        if current_price >= stop_loss:
            return ExitSignal(
                should_exit=True,
                exit_price=stop_loss,
                reason="stop_hit",
            )

        # Target 1 (partial gap fill)
        if current_price <= target_1:
            return ExitSignal(
                should_exit=True,
                exit_price=target_1,
                reason="target_hit",
            )

        return ExitSignal(should_exit=False, exit_price=current_price, reason="hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        """
        Score gap-up fade signal.

        Tuesday/Wednesday: *1.2 (bearish bias amplifies fade)
        Friday: *0.6 (bullish day works against fade)
        RSI > 70 at open: *1.15 (overbought confirms fade)
        Trending regime penalty: *0.5
        """
        score = signal.confidence

        day = filters.get("day_of_week", "")
        if day in ("Tuesday", "Wednesday"):
            score *= 1.2
        elif day == "Friday":
            score *= 0.6

        rsi = filters.get("daily_rsi", 50)
        if rsi > 70:
            score *= 1.15
            
        regime = filters.get("regime", "normal")
        if regime in ("trending_strong", "trending_weak"):
            score *= 0.5

        return min(score, 2.0)
