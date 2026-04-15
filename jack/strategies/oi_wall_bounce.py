"""
Strategy: OI Wall Bounce.

Fades price extremes approaching massive Option seller walls.
"""

from typing import Optional
from strategies.base import Strategy, TradeSignal, ExitSignal

class OIWallBounce(Strategy):
    """Institutional OI Wall Support/Resistance."""

    def __init__(self, params: dict = None):
        default_params = {
            "wall_proximity_pct": 0.002, # 0.2%
        }
        if params:
            default_params.update(params)

        super().__init__(name="oi_wall_bounce", params=default_params)
        self.required_indicators = ["oi_levels"]
        self.eligible_timeframes = ["10:00-14:30"]

    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
        diagnostics: dict = None,
    ) -> Optional[TradeSignal]:
        
        levels = indicators.get("oi_levels", {})
        support = levels.get("support_levels", [])
        resistance = levels.get("resistance_levels", [])
        
        current_price = indicators.get("current_price", 0)
        
        direction = None
        reason = ""
        
        if len(support) > 0:
            s1 = support[0]["strike"]
            dist_s1 = abs(current_price - s1) / current_price
            if dist_s1 <= self.params["wall_proximity_pct"]:
                direction = "LONG"
                reason = f"Bounce off PE OI Wall at {s1}"
                
        if not direction and len(resistance) > 0:
            r1 = resistance[0]["strike"]
            dist_r1 = abs(current_price - r1) / current_price
            if dist_r1 <= self.params["wall_proximity_pct"]:
                direction = "SHORT"
                reason = f"Bounce off CE OI Wall at {r1}"

        if not direction:
            if diagnostics is not None: diagnostics["reason_skipped"] = "not_near_oi_wall"
            return None

        if diagnostics is not None:
            diagnostics["base_condition_met"] = True
            diagnostics["signal_generated"] = True
            diagnostics["reason_skipped"] = None

        return TradeSignal(
            strategy_name=self.name,
            direction=direction,
            entry_price=current_price,
            stop_loss=current_price * 0.995 if direction=="LONG" else current_price * 1.005,
            target=current_price * 1.01 if direction=="LONG" else current_price * 0.99,
            confidence=0.7,
            reason=reason,
            metadata={}
        )

    def check_exit(self, position: dict, day_data: dict, current_time: str, current_price: float) -> ExitSignal:
        if current_time >= "15:15":
            return ExitSignal(True, current_price, "time_exit")
        return ExitSignal(False, current_price, "hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        return signal.confidence
