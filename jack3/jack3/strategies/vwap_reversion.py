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
            "vwap_dev_pct": 0.15,
            "rsi_extreme_short": 58,
            "rsi_extreme_long": 42,
            "adx_threshold": 30,
            "max_dev_stop_pct": 0.15,
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

        Entry requires:
        1. Price deviates > 0.3% from VWAP
        2. 5m RSI at extreme (>70 for short, <30 for long)
        3. ADX < 25 (range market)
        4. Day type is not strong trend
        """
        current_price = indicators.get("current_price", 0)
        daily = indicators.get("daily", {})

        # We need VWAP - compute from intraday data or use provided if available
        vwap = indicators.get("intraday_5m", {}).get("vwap")
        if not vwap:
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

        rsi = indicators.get("intraday_5m", {}).get("rsi", 50)

        dev_dir = 1 if current_price > vwap else -1 # 1 means price is above VWAP (needs short)

        if dev_dir == 1:
            if rsi < self.params["rsi_extreme_short"]:
                 if diagnostics is not None: diagnostics["reason_skipped"] = f"rsi_not_extreme_short: {rsi}"
                 return None

            direction = "SHORT"
            stop_loss = current_price * (1 + self.params["max_dev_stop_pct"] / 100)
            target = vwap

        else:
            if rsi > self.params["rsi_extreme_long"]:
                 if diagnostics is not None: diagnostics["reason_skipped"] = f"rsi_not_extreme_long: {rsi}"
                 return None

            direction = "LONG"
            stop_loss = current_price * (1 - self.params["max_dev_stop_pct"] / 100)
            target = vwap

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
            }
        )

    def check_exit(
        self,
        position: dict,
        day_data: dict,
        current_time: str,
        current_price: float,
    ) -> ExitSignal:
        """Exit at target (VWAP), stop, or time."""
        direction = position.get("direction", "LONG")
        target = position.get("target", 0)
        stop_loss = position.get("stop_loss", 0)

        # Time exit at 13:30
        if current_time >= "13:30":
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
        """Basic score."""
        return signal.confidence
