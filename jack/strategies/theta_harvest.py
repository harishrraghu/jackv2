"""
Strategy: Theta Harvester.

Sells OTM strangles on Bank Nifty weekly expiry days (Thursday) in calm markets.
"""

from typing import Optional
from strategies.base import Strategy, TradeSignal, ExitSignal
from engine.options import StrikeSelector


class ThetaHarvest(Strategy):
    """Sell OTM strangles on Expiry days."""

    def __init__(self, params: dict = None):
        default_params = {
            "atr_otm_multiplier": 1.5,
            "stop_loss_multiplier": 2.0, # Stop loss if premium doubles
        }
        if params:
            default_params.update(params)

        super().__init__(name="theta_harvest", params=default_params)
        self.required_indicators = ["atr"]
        self.eligible_timeframes = ["09:30"]

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
        Check entry conditions.

        1. Thursday
        2. ATR < 60d median (handled by volatility filter being 'contracting' or 'normal' but < 1.0 ratio)
        """
        if current_time != "09:30":
            return None

        day_of_week = filters.get("day_of_week", "")
        if day_of_week != "Thursday":
            if diagnostics is not None: diagnostics["reason_skipped"] = "not_thursday"
            return None

        vol_filter = filters.get("filters", {}).get("volatility", {})
        if vol_filter.get("atr_ratio", 1.0) >= 1.0:
            if diagnostics is not None: diagnostics["reason_skipped"] = "not_calm_day"
            return None

        current_price = indicators.get("current_price", 0)
        daily = indicators.get("daily", {})
        atr = daily.get("ATR", 0)

        if current_price <= 0 or atr <= 0:
            return None

        # Simulate options strike selection
        selector = StrikeSelector()
        options = selector.select_theta_harvest(current_price, atr)

        if diagnostics is not None:
            diagnostics["base_condition_met"] = True
            diagnostics["signal_generated"] = True
            diagnostics["reason_skipped"] = None

        return TradeSignal(
            strategy_name=self.name,
            direction="SHORT", # Short volatility/premium
            entry_price=current_price, # We track spot price to gauge stop or use theoretical premium
            stop_loss=current_price + atr * 2, # Fallback spot stop if we were outright
            target=current_price,
            confidence=0.7,
            reason=f"Theta Harvest Strangle on Expiry. ATR Ratio: {vol_filter.get('atr_ratio')}",
            metadata={
                "options_strategy": options,
                "atr": atr,
                "entry_premium": "unknown", # Normally would be fetched from OptionsPricer
            }
        )

    def check_exit(
        self,
        position: dict,
        day_data: dict,
        current_time: str,
        current_price: float,
    ) -> ExitSignal:
        """Exit at 13:00 or stop."""
        if current_time >= "13:00":
            return ExitSignal(True, current_price, "time_exit")

        # In a real engine, we'd price the options here and check if premium doubled.
        # As a fallback, we check if spot moved wildly
        atr = position.get("metadata", {}).get("atr", 100)
        entry_price = position.get("entry_price", current_price)
        
        move = abs(current_price - entry_price)
        if move > atr * 1.5:
            return ExitSignal(True, current_price, "stop_hit_spot_moved")

        return ExitSignal(False, current_price, "hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        return signal.confidence
