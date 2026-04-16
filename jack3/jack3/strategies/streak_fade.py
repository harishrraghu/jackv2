"""
Strategy C: Streak Fade.

After 3 consecutive green days, next day is red 75%.
After 3 red days, bounce 55%. Mean-reversion strategy.

Parameters (3 of 5 budget):
    min_streak: 4
    atr_stop_multiplier: 0.6
    atr_target_multiplier: 1.5
"""

from typing import Optional

from strategies.base import Strategy, TradeSignal, ExitSignal


class StreakFade(Strategy):
    """Fade extended consecutive day streaks."""

    def __init__(self, params: dict = None):
        default_params = {
            "min_streak": 4,
            "atr_stop_multiplier": 0.6,
            "atr_target_multiplier": 1.5,
        }
        if params:
            default_params.update(params)

        super().__init__(name="streak_fade", params=default_params)
        self.required_indicators = ["streaks", "sma", "atr", "adx", "ema"]
        self.eligible_timeframes = ["09:15-09:30"]

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
        Check entry for streak fade.

        Uses YESTERDAY's streak values from lookback.
        """
        # Disabled per analysis: 25% win rate and causes major drawdowns
        if diagnostics is not None: diagnostics["reason_skipped"] = "strategy_disabled"
        return None

        daily = indicators.get("daily", {})
        lookback_daily = indicators.get("lookback_daily", {})

        bull_streak = lookback_daily.get("Bull_Streak", 0)
        bear_streak = lookback_daily.get("Bear_Streak", 0)

        min_streak = self.params["min_streak"]
        atr = daily.get("ATR", 0)
        # sma_20 = daily.get("SMA_20", 0)

        adx = daily.get("ADX")
        ema_9 = daily.get("EMA_9")
        ema_21 = daily.get("EMA_21")

        if atr is None or atr <= 0:
            return None

        # Mean reversion only in ranging markets
        if adx is not None and adx > 25:
            return None

        current_price = indicators.get("current_price", 0)
        if current_price <= 0:
            if diagnostics is not None: diagnostics["reason_skipped"] = "invalid_price"
            return None

        if diagnostics is not None:
            diagnostics["base_condition_met"] = (bull_streak >= min_streak or bear_streak >= min_streak)

        stop_mult = self.params["atr_stop_multiplier"]
        target_mult = self.params["atr_target_multiplier"]

        if bull_streak >= min_streak:
            # For bull streak SHORT, check trend alignment
            if ema_9 is not None and ema_21 is not None:
                if ema_9 > ema_21:
                    if diagnostics is not None: diagnostics["reason_skipped"] = "trend_alignment_wrong"
                    return None

            # Fade the bull streak -> SHORT
            entry_price = current_price  # Enter at open
            # Stop above highest high of the streak
            streak_high = lookback_daily.get("streak_high", entry_price + atr)
            stop_loss = streak_high + stop_mult * atr

            target = entry_price - atr * target_mult

            # R:R check
            risk = stop_loss - entry_price
            reward = entry_price - target
            if risk <= 0 or (reward / risk) < 1.2:
                if diagnostics is not None: diagnostics["reason_skipped"] = "poor_rr"
                return None

            confidence = 0.8 if bull_streak >= 5 else 0.7

            return TradeSignal(
                strategy_name=self.name,
                direction="SHORT",
                entry_price=entry_price,
                stop_loss=stop_loss,
                target=target,
                confidence=confidence,
                reason=(
                    f"Streak fade: {bull_streak} consecutive green days. "
                    f"Target: {target:.0f}"
                ),
                metadata={
                    "streak_length": bull_streak,
                    "streak_type": "bull",
                    "entry_day": 1,
                    "max_hold_days": 2,
                },
            )

        elif bear_streak >= min_streak:
            # For bear streak LONG, check trend alignment
            if ema_9 is not None and ema_21 is not None:
                if ema_9 < ema_21:
                    if diagnostics is not None: diagnostics["reason_skipped"] = "trend_alignment_wrong"
                    return None

            # Fade the bear streak -> LONG
            entry_price = current_price
            streak_low = lookback_daily.get("streak_low", entry_price - atr)
            stop_loss = streak_low - stop_mult * atr

            target = entry_price + atr * target_mult

            # R:R check
            risk = entry_price - stop_loss
            reward = target - entry_price
            if risk <= 0 or (reward / risk) < 1.2:
                if diagnostics is not None: diagnostics["reason_skipped"] = "poor_rr"
                return None

            confidence = 0.55  # Lower edge for bear streak bounce

            return TradeSignal(
                strategy_name=self.name,
                direction="LONG",
                entry_price=entry_price,
                stop_loss=stop_loss,
                target=target,
                confidence=confidence,
                reason=(
                    f"Streak fade: {bear_streak} consecutive red days. "
                    f"Target: {target:.0f}"
                ),
                metadata={
                    "streak_length": bear_streak,
                    "streak_type": "bear",
                    "entry_day": 1,
                    "max_hold_days": 2,
                },
            )

        if diagnostics is not None: diagnostics["reason_skipped"] = f"no_{min_streak}day_streak"
        return None

    def check_exit(
        self,
        position: dict,
        day_data: dict,
        current_time: str,
        current_price: float,
    ) -> ExitSignal:
        """
        Check exit for streak fade positions.

        This strategy can hold overnight — max 2 trading days.
        """
        direction = position.get("direction", "LONG")
        stop_loss = position.get("stop_loss", 0)
        target = position.get("target", 0)
        entry_day = position.get("metadata", {}).get("entry_day", 1)
        max_hold = position.get("metadata", {}).get("max_hold_days", 2)

        # Max hold period
        if entry_day > max_hold and current_time >= "15:15":
            return ExitSignal(
                should_exit=True,
                exit_price=current_price,
                reason="time_exit",
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
        else:  # SHORT
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
        Score streak fade signal.

        4+ day streak: *1.2
        Fading trends: *0.7
        """
        score = signal.confidence

        streak_len = signal.metadata.get("streak_length", 3)
        if streak_len >= 5: # Since min streak is 4 now
            score *= 1.2

        regime = filters.get("regime", "normal")
        if regime in ("trending_strong", "trending_weak"):
            # Don't fade trends aggressively
            score *= 0.7

        return min(score, 2.0)
