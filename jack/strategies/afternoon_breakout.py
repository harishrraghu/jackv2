"""
Strategy: Afternoon Breakout.

Capitalizes on low-volatility mornings that break into a trend after 13:00.
Tracks High/Low up to 12:30.
If price breaks those boundaries after 13:00 with RSI momentum, it enters in the breakout direction.
"""

from typing import Optional
from strategies.base import Strategy, TradeSignal, ExitSignal

class AfternoonBreakout(Strategy):
    """Afternoon Breakout Strategy."""

    def __init__(self, params: dict = None):
        default_params = {
            "breakout_buffer_pct": 0.05,
            "rsi_long_min": 60,
            "rsi_short_max": 40,
            "target_atr_mult": 1.5,
            "stop_atr_mult": 0.5,
        }
        if params:
            default_params.update(params)

        super().__init__(name="afternoon_breakout", params=default_params)
        self.required_indicators = ["rsi", "atr"]
        self.eligible_timeframes = ["13:00-14:30"]

    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
        diagnostics: dict = None,
    ) -> Optional[TradeSignal]:
        current_price = indicators.get("current_price", 0)
        daily = indicators.get("daily", {})
        
        if current_price <= 0:
            if diagnostics is not None: diagnostics["reason_skipped"] = "missing_price"
            return None

        # Check ADX for trend filter
        adx = daily.get("ADX", 0)
        if adx < 20:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"adx_too_low: {adx:.1f} < 20"
            return None

        # Track morning range (09:15 to 12:30)
        day_15m = day_data.get("15m")
        if day_15m is None or day_15m.empty:
            if diagnostics is not None: diagnostics["reason_skipped"] = "missing_15m_data"
            return None

        morning_data = day_15m[day_15m["Time"] <= "12:30"]
        if morning_data.empty:
            if diagnostics is not None: diagnostics["reason_skipped"] = "missing_morning_data"
            return None

        morning_high = morning_data["High"].max()
        morning_low = morning_data["Low"].min()

        # Buffer limits
        upper_bound = morning_high * (1 + self.params["breakout_buffer_pct"] / 100)
        lower_bound = morning_low * (1 - self.params["breakout_buffer_pct"] / 100)

        # 5m RSI for momentum
        rsi = indicators.get("rsi_5m", 50)
        atr = daily.get("ATR", 100)

        direction = None
        if current_price > upper_bound and rsi >= self.params["rsi_long_min"]:
            direction = "LONG"
            stop_loss = current_price - (atr * self.params["stop_atr_mult"])
            target = current_price + (atr * self.params["target_atr_mult"])
        elif current_price < lower_bound and rsi <= self.params["rsi_short_max"]:
            direction = "SHORT"
            stop_loss = current_price + (atr * self.params["stop_atr_mult"])
            target = current_price - (atr * self.params["target_atr_mult"])

        if direction is None:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"no_breakout_or_momentum (Price: {current_price}, High: {upper_bound}, Low: {lower_bound}, RSI: {rsi})"
            return None

        if diagnostics is not None:
            diagnostics["base_condition_met"] = True
            diagnostics["signal_generated"] = True
            diagnostics["reason_skipped"] = None

        return TradeSignal(
            strategy_name=self.name,
            direction=direction,
            entry_price=current_price,
            stop_loss=stop_loss,
            target=target,
            confidence=0.75,
            reason=f"Afternoon Breakout {direction}. Price {current_price} broke {direction} bound. RSI: {rsi:.1f}",
            metadata={
                "morning_high": morning_high,
                "morning_low": morning_low,
                "rsi_5m": rsi,
            }
        )

    def check_exit(
        self,
        position: dict,
        day_data: dict,
        current_time: str,
        current_price: float,
    ) -> ExitSignal:
        direction = position.get("direction", "LONG")
        target = position.get("target", 0)
        stop_loss = position.get("stop_loss", 0)
        
        # Time exit at 15:15
        if current_time >= "15:15":
            return ExitSignal(True, current_price, "time_exit")
            
        if direction == "LONG":
            if current_price <= stop_loss:
                return ExitSignal(True, stop_loss, "stop_hit")
            if current_price >= target:
                return ExitSignal(True, target, "target_hit")
        else:
            if current_price >= stop_loss:
                return ExitSignal(True, stop_loss, "stop_hit")
            if current_price <= target:
                return ExitSignal(True, target, "target_hit")
                
        return ExitSignal(False, current_price, "hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        return signal.confidence
