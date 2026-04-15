"""
Strategy: OI Confirmed Breakout.

Buys options only when price breakouts are confirmed by OI flow.
"""

from typing import Optional
from strategies.base import Strategy, TradeSignal, ExitSignal

class OIConfirmedBreakout(Strategy):
    """Breakout confirmed by Option OI Flow."""

    def __init__(self, params: dict = None):
        default_params = {
            "min_adx": 25,
            "required_oi_signal": True
        }
        if params:
            default_params.update(params)

        super().__init__(name="oi_confirmed_breakout", params=default_params)
        self.required_indicators = ["oi_flow", "greeks_momentum"]
        self.eligible_timeframes = ["10:15-14:30"]

    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
        diagnostics: dict = None,
    ) -> Optional[TradeSignal]:
        
        oi_flow = indicators.get("oi_flow", {})
        flow_sig = oi_flow.get("flow_signal", "NEUTRAL")
        
        if flow_sig == "NEUTRAL" and self.params["required_oi_signal"]:
            if diagnostics is not None: diagnostics["reason_skipped"] = "no_oi_confirmation"
            return None
            
        # Check VWAP breakout
        current_price = indicators.get("current_price", 0)
        vwap = indicators.get("vwap", 0)
        
        direction = None
        if current_price > vwap and flow_sig in ["OI_SURGE_PUT", "OI_UNWIND_CALLS"]:
            direction = "LONG"
        elif current_price < vwap and flow_sig in ["OI_SURGE_CALL", "OI_UNWIND_PUTS"]:
            direction = "SHORT"
            
        if not direction:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"price_oi_mismatch (Flow: {flow_sig})"
            return None

        if diagnostics is not None:
            diagnostics["base_condition_met"] = True
            diagnostics["signal_generated"] = True
            diagnostics["reason_skipped"] = None

        return TradeSignal(
            strategy_name=self.name,
            direction=direction,
            entry_price=current_price,
            stop_loss=vwap,
            target=current_price + (current_price - vwap)*2 if direction=="LONG" else current_price - (vwap - current_price)*2,
            confidence=0.75,
            reason=f"OI Confirmed Breakout: {flow_sig}",
            metadata={}
        )

    def check_exit(self, position: dict, day_data: dict, current_time: str, current_price: float) -> ExitSignal:
        if current_time >= "15:15":
            return ExitSignal(True, current_price, "time_exit")
        return ExitSignal(False, current_price, "hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        return signal.confidence
