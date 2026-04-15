"""
Strategy: VWAP Mean Reversion.

Trades mean reversion to VWAP during the dead zone (11:00-13:00) on range days.
"""

from typing import Optional
from strategies.base import Strategy, TradeSignal, ExitSignal


class VWAPReversion(Strategy):
    """Mean reversion to VWAP on range days."""

    def __init__(self, params: dict = None):
        default_params = {
            "vwap_dev_pct": 0.60,          # Raised further — only trade extreme stretches
            "rsi_extreme_offset": 20,       # RSI 70+ short, 30- long
            "adx_threshold": 22,            # Strict range-day filter
            "max_dev_stop_pct": 0.25,       # Wider stop to avoid noise stops
            "target_overshoot_pct": 0.25,  # Bigger target for 3:1+ R:R
        }
        if params:
            default_params.update(params)

        super().__init__(name="vwap_reversion", params=default_params)
        self.required_indicators = ["vwap", "rsi", "adx"]
        self.eligible_timeframes = ["11:15-13:00"]

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
        Check entry conditions for VWAP reversion.
        """
        current_price = indicators.get("current_price", 0)
        daily = indicators.get("daily", {})
        
        vwap = indicators.get("vwap")

        if not vwap or current_price <= 0:
            if diagnostics is not None: diagnostics["reason_skipped"] = "missing_vwap"
            return None

        dev_pct = abs(current_price - vwap) / vwap * 100
        min_dev = self.params["vwap_dev_pct"]
        
        if dev_pct < min_dev:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"dev_pct_too_low: {dev_pct:.2f} < {min_dev}"
            return None

        adx = daily.get("ADX", 100)
        if adx >= self.params["adx_threshold"]:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"adx_too_high: {adx:.1f}"
            return None
            
        rsi = indicators.get("rsi_5m", 50)

        dev_dir = 1 if current_price > vwap else -1 # 1 means price is above VWAP (needs short)

        if dev_dir == 1:
            if rsi < 50 + self.params["rsi_extreme_offset"]:
                 if diagnostics is not None: diagnostics["reason_skipped"] = f"rsi_not_extreme_short: {rsi}"
                 return None
            
            direction = "SHORT"
            stop_loss = current_price * (1 + self.params["max_dev_stop_pct"] / 100)
            target = vwap * (1 - self.params["target_overshoot_pct"] / 100)
            
        else:
            if rsi > 50 - self.params["rsi_extreme_offset"]:
                 if diagnostics is not None: diagnostics["reason_skipped"] = f"rsi_not_extreme_long: {rsi}"
                 return None
                 
            direction = "LONG"
            stop_loss = current_price * (1 - self.params["max_dev_stop_pct"] / 100)
            target = vwap * (1 + self.params["target_overshoot_pct"] / 100)

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
            confidence=0.6,
            reason=f"VWAP Reversion {direction}. Dev: {dev_pct:.2f}%, RSI: {rsi:.1f}, ADX: {adx:.1f}",
            metadata={
                "vwap": vwap,
                "dev_pct": dev_pct,
                "rsi": rsi,
                "adx": adx,
                "risk_multiplier": 0.15,  # Minimal size — mean reversion is weak on trending market
            }
        )

    def check_exit(
        self,
        position: dict,
        day_data: dict,
        current_time: str,
        current_price: float,
    ) -> ExitSignal:
        """Exit at target (VWAP overshot), stop, or time."""
        direction = position.get("direction", "LONG")
        target = position.get("target", None)
        stop_loss = position.get("stop_loss", None)

        # Validate stop/target exist before using them
        if stop_loss is None or target is None or stop_loss <= 0 or target <= 0:
            return ExitSignal(False, current_price, "hold")

        # Time exit at 13:30
        if current_time >= "13:30":
            return ExitSignal(True, current_price, "time_exit")

        if direction == "LONG":
            if current_price <= stop_loss:
                return ExitSignal(True, stop_loss, "stop_hit")
            if current_price >= target:
                return ExitSignal(True, target, "target_hit")
        else:  # SHORT
            if current_price >= stop_loss:
                return ExitSignal(True, stop_loss, "stop_hit")
            if current_price <= target:
                return ExitSignal(True, target, "target_hit")

        return ExitSignal(False, current_price, "hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        """Basic score."""
        return signal.confidence
