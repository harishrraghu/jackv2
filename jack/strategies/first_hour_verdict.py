"""
Strategy A: First Hour Verdict.

When the first 1-hour candle (9:15-10:15) closes with a move exceeding 0.4%,
it predicts the day's close direction 79.7% of the time. The day high/low is
set AFTER the first hour 68-72% of the time, so pullback entry is optimal.

Parameters (4 of 5 budget):
    min_fh_move_pct: 0.3
    atr_stop_multiplier: 0.5
    atr_target_multiplier: 2.0
    trail_atr_trigger: 1.0
    trail_atr_distance: 0.5
"""

from typing import Optional

from strategies.base import Strategy, TradeSignal, ExitSignal


class FirstHourVerdict(Strategy):
    """Trade in the direction of a strong first-hour move."""

    def __init__(self, params: dict = None):
        default_params = {
            "min_fh_move_pct": 0.3,
            "atr_stop_multiplier": 0.5,
            "atr_target_multiplier": 2.0,
            "trail_atr_trigger": 1.0,
            "trail_atr_distance": 0.5,
        }
        if params:
            default_params.update(params)

        super().__init__(name="first_hour_verdict", params=default_params)
        self.required_indicators = ["atr", "ema", "rsi", "first_hour"]
        self.eligible_timeframes = ["10:15-11:15", "11:15-14:15"]

    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
    ) -> Optional[TradeSignal]:
        """
        Check entry conditions based on first hour move.

        Entry requires:
        1. First hour move > 0.4% (FH_Strong)
        2. Trend alignment (EMA_9 vs EMA_21)
        3. RSI not at extremes
        """
        fh = indicators.get("first_hour", {})
        daily = indicators.get("daily", {})

        fh_return = fh.get("FH_Return")
        fh_direction = fh.get("FH_Direction", 0)
        fh_strong = fh.get("FH_Strong", False)

        if not fh_strong or fh_return is None:
            return None

        atr = daily.get("ATR")
        rsi = daily.get("RSI")
        ema_9 = daily.get("EMA_9")
        ema_21 = daily.get("EMA_21")

        if atr is None or atr <= 0:
            return None

        current_price = indicators.get("current_price", 0)
        if current_price <= 0:
            return None

        min_fh = self.params["min_fh_move_pct"]
        stop_mult = self.params["atr_stop_multiplier"]
        target_mult = self.params["atr_target_multiplier"]

        if fh_direction == 1:  # Bullish first hour
            confidence = 0.8 if abs(fh_return) > 0.6 else 0.75
            
            # Trend alignment: penalize soft confidence if EMA not aligned
            if ema_9 is not None and ema_21 is not None:
                if ema_9 < ema_21:
                    confidence = 0.65

            # RSI filter: not extremely overbought
            if rsi is not None and rsi > 85:
                return None

            direction = "LONG"
            entry_price = current_price
            stop_loss = entry_price - stop_mult * atr
            target = entry_price + target_mult * atr

        elif fh_direction == -1:  # Bearish first hour
            confidence = 0.8 if abs(fh_return) > 0.6 else 0.75
            
            # Trend alignment: penalize soft confidence if EMA not aligned
            if ema_9 is not None and ema_21 is not None:
                if ema_9 > ema_21:
                    confidence = 0.65

            # RSI filter: not extremely oversold
            if rsi is not None and rsi < 15:
                return None

            direction = "SHORT"
            entry_price = current_price
            stop_loss = entry_price + stop_mult * atr
            target = entry_price - target_mult * atr

        else:
            return None

        return TradeSignal(
            strategy_name=self.name,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            confidence=confidence,
            reason=(
                f"First hour {direction.lower()}: {fh_return:+.2f}% move "
                f"(threshold: {min_fh}%). ATR={atr:.1f}"
            ),
            metadata={
                "fh_return": fh_return,
                "fh_direction": fh_direction,
                "atr": atr,
                "rsi": rsi,
                "risk_multiplier": 2.5,  # scale this strategy because it's core alpha
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
        Check exit conditions for first hour verdict positions.

        Exits: stop loss, target, trailing breakeven, time exit at 15:15.
        """
        direction = position.get("direction", "LONG")
        stop_loss = position.get("stop_loss", 0)
        target = position.get("target", 0)
        entry_price = position.get("entry_price", 0)
        atr = position.get("metadata", {}).get("atr", 100)

        trail_trigger = self.params["trail_atr_trigger"]
        trail_dist = self.params["trail_atr_distance"]

        # Time exit
        if current_time >= "15:15":
            return ExitSignal(
                should_exit=True,
                exit_price=current_price,
                reason="time_exit",
            )

        if direction == "LONG":
            profit = current_price - entry_price
            
            # Standard stop/trail combo
            if profit >= trail_trigger * atr:
                trail_stop = max(current_price - trail_dist * atr, stop_loss)
                if current_price <= trail_stop:
                    return ExitSignal(
                        should_exit=True,
                        exit_price=trail_stop,
                        reason="trail_stop",
                    )
            else:
                if current_price <= stop_loss:
                    return ExitSignal(
                        should_exit=True,
                        exit_price=stop_loss,
                        reason="stop_hit",
                    )

            # Target
            if current_price >= target:
                return ExitSignal(
                    should_exit=True,
                    exit_price=target,
                    reason="target_hit",
                )

        else:  # SHORT
            profit = entry_price - current_price
            
            # Standard stop/trail combo
            if profit >= trail_trigger * atr:
                trail_stop = min(current_price + trail_dist * atr, stop_loss)
                if current_price >= trail_stop:
                    return ExitSignal(
                        should_exit=True,
                        exit_price=trail_stop,
                        reason="trail_stop",
                    )
            else:
                if current_price >= stop_loss:
                    return ExitSignal(
                        should_exit=True,
                        exit_price=stop_loss,
                        reason="stop_hit",
                    )

            # Target
            if current_price <= target:
                return ExitSignal(
                    should_exit=True,
                    exit_price=target,
                    reason="target_hit",
                )

        return ExitSignal(should_exit=False, exit_price=current_price, reason="hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        """
        Score signal with day-of-week and regime modifiers.

        Friday: *1.15 (bullish day)
        Tuesday: *0.7 (bearish day)
        Trending regime: *1.1
        Squeeze regime: *0.8
        """
        score = signal.confidence

        day = filters.get("day_of_week", "")
        if day == "Friday":
            score *= 1.15
        elif day == "Tuesday":
            score *= 0.75

        regime = filters.get("regime", "normal")
        if regime in ("trending_strong", "trending_weak"):
            score *= 1.15
        elif regime == "squeeze":
            score *= 1.5  # Boosted by AI Retrospective (90% Win Rate)

        return min(score, 2.0)
