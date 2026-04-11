"""
Options pricing and simulation engine.

Provides:
- Black-Scholes pricing for European options
- Strike selection based on directional signal
- Intraday premium decay simulation
- Spread construction (bull call, bear put, strangles)
"""
import math
from typing import Optional

import numpy as np
from scipy.stats import norm


class OptionsPricer:
    """Black-Scholes options pricing engine."""

    def __init__(self, risk_free_rate: float = 0.065):
        self.risk_free_rate = risk_free_rate

    def black_scholes(self, S: float, K: float, T: float, sigma: float, option_type: str = "call") -> float:
        """
        Black-Scholes European option price.

        Args:
            S: Current spot price
            K: Strike price
            T: Time to expiry in years (e.g., 1/365 for 1 day)
            sigma: Implied volatility (annualized, e.g., 0.20 for 20%)
            option_type: "call" or "put"

        Returns:
            Option premium
        """
        if T <= 0 or sigma <= 0:
            # At or past expiry
            if option_type == "call":
                return max(S - K, 0)
            else:
                return max(K - S, 0)

        d1 = (math.log(S / K) + (self.risk_free_rate + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        if option_type == "call":
            price = S * norm.cdf(d1) - K * math.exp(-self.risk_free_rate * T) * norm.cdf(d2)
        else:
            price = K * math.exp(-self.risk_free_rate * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

        return max(price, 0)

    def greeks(self, S: float, K: float, T: float, sigma: float, option_type: str = "call") -> dict:
        """Compute option Greeks."""
        if T <= 0 or sigma <= 0:
            return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}

        d1 = (math.log(S / K) + (self.risk_free_rate + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        # Delta
        if option_type == "call":
            delta = norm.cdf(d1)
        else:
            delta = norm.cdf(d1) - 1

        # Gamma
        gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))

        # Theta (per day)
        theta_part1 = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
        if option_type == "call":
            theta_part2 = -self.risk_free_rate * K * math.exp(-self.risk_free_rate * T) * norm.cdf(d2)
        else:
            theta_part2 = self.risk_free_rate * K * math.exp(-self.risk_free_rate * T) * norm.cdf(-d2)
        theta = (theta_part1 + theta_part2) / 365.0  # Daily theta

        # Vega (per 1% IV change)
        vega = S * math.sqrt(T) * norm.pdf(d1) / 100.0

        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 2),
            "vega": round(vega, 2)
        }


class StrikeSelector:
    """Select optimal strike based on directional signal and market conditions."""

    def __init__(self, lot_size: int = 15, strike_interval: int = 100):
        self.lot_size = lot_size
        self.strike_interval = strike_interval

    def select_directional(self, spot: float, direction: str, atr: float,
                           strategy: str = "buy_atm") -> dict:
        """
        Select strike for directional trade.

        Strategies:
        - "buy_atm": Buy ATM CE/PE (simple directional)
        - "buy_otm1": Buy 1 strike OTM (cheaper, higher leverage)
        - "sell_otm": Sell OTM option opposite to direction (premium collection)
        - "spread": Bull call spread or bear put spread
        """
        # Round spot to nearest strike
        atm_strike = round(spot / self.strike_interval) * self.strike_interval

        if strategy == "buy_atm":
            if direction == "LONG":
                return {
                    "type": "BUY",
                    "option_type": "call",
                    "strike": atm_strike,
                    "lots": 1,
                    "strategy_name": "long_atm_call",
                }
            else:
                return {
                    "type": "BUY",
                    "option_type": "put",
                    "strike": atm_strike,
                    "lots": 1,
                    "strategy_name": "long_atm_put",
                }

        elif strategy == "spread":
            if direction == "LONG":
                return {
                    "legs": [
                        {"type": "BUY", "option_type": "call", "strike": atm_strike},
                        {"type": "SELL", "option_type": "call", "strike": atm_strike + self.strike_interval},
                    ],
                    "strategy_name": "bull_call_spread",
                    "max_loss": None,  # Computed from premiums
                    "max_profit": None,
                }
            else:
                return {
                    "legs": [
                        {"type": "BUY", "option_type": "put", "strike": atm_strike},
                        {"type": "SELL", "option_type": "put", "strike": atm_strike - self.strike_interval},
                    ],
                    "strategy_name": "bear_put_spread",
                    "max_loss": None,
                    "max_profit": None,
                }

        return {"error": f"Unknown strategy: {strategy}"}

    def select_theta_harvest(self, spot: float, atr: float,
                             days_to_expiry: float = 0.01) -> dict:
        """
        Select strikes for theta harvesting (strangle).

        Sell OTM CE and OTM PE, both at ~1.5-2x ATR from spot.
        """
        atm = round(spot / self.strike_interval) * self.strike_interval
        otm_distance = int(round(atr * 1.5 / self.strike_interval)) * self.strike_interval

        return {
            "legs": [
                {"type": "SELL", "option_type": "call", "strike": atm + otm_distance},
                {"type": "SELL", "option_type": "put", "strike": atm - otm_distance},
            ],
            "strategy_name": "short_strangle",
            "breakeven_upper": atm + otm_distance,  # + premium received
            "breakeven_lower": atm - otm_distance,  # - premium received
        }
