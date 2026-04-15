"""
Greeks Momentum Analysis — Entry timing based on option Greeks.

Calculates Gamma/Theta ratio, Gamma Sweet Spot, and Theta Cliffs.
"""

import logging
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

METADATA = {
    "name": "greeks_momentum",
    "display_name": "Greeks Momentum & Timing",
    "params": {},
    "output_columns": ["GammaThetaRatio", "GreeksSignal"],
    "timeframes": ["1d"],
}

def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """No-op for registry compatibility. Use GreeksAnalyzer class methods."""
    return df

class GreeksAnalyzer:
    """Timing engine based on Option Greeks."""

    def __init__(self, target_delta_min=0.45, target_delta_max=0.65):
        self.target_delta_min = target_delta_min
        self.target_delta_max = target_delta_max

    def analyze_chain(self, chain: pd.DataFrame, direction: str) -> dict:
        """
        Analyze current Greeks environment for a specific direction.
        """
        if chain is None or chain.empty:
            return {"signal": "NEUTRAL", "ratio": 1.0, "is_favorable": True}

        prefix = "ce" if direction == "LONG" else "pe"
        
        # Require delta, gamma, theta
        required_cols = [f"{prefix}_delta", f"{prefix}_gamma", f"{prefix}_theta"]
        if not all(col in chain.columns for col in required_cols):
            return {"signal": "NEUTRAL", "ratio": 1.0, "is_favorable": True, "note": "Missing greeks data"}
            
        # Target ATM options
        df = chain.copy()
        
        # Filter for Target Delta
        atm_options = df[
            (df[f"{prefix}_delta"].abs() >= self.target_delta_min) & 
            (df[f"{prefix}_delta"].abs() <= self.target_delta_max)
        ]
        
        if atm_options.empty:
            # Fallback to nearest absolute 0.5 delta
            df['delta_diff'] = (df[f"{prefix}_delta"].abs() - 0.5).abs()
            best_strike_row = df.sort_values('delta_diff').iloc[0]
        else:
            df['delta_diff'] = (atm_options[f"{prefix}_delta"].abs() - 0.5).abs()
            best_strike_row = atm_options.sort_values('delta_diff').iloc[0]

        gamma = abs(best_strike_row.get(f"{prefix}_gamma", 0.001))
        theta = abs(best_strike_row.get(f"{prefix}_theta", 0.001))
        premium = best_strike_row.get(f"{prefix}_ltp", 1.0)
        
        if gamma == 0: gamma = 0.001
        if theta == 0: theta = 0.001
        if premium == 0: premium = 1.0
        
        # Ratio of Gamma per unit of Theta decay
        ratio = gamma / theta * 100 # Adjust scale
        
        # Risk of theta erasing premium rapidly (e.g. 0DTE cliff)
        theta_decay_pct = (theta / premium) * 100
        
        is_favorable = True
        signal = "NEUTRAL"
        
        if theta_decay_pct > 15.0:  # Losing 15% of premium to theta per day
            signal = "THETA_CLIFF"
            is_favorable = False
        elif ratio > 1.2:
            signal = "GAMMA_SWEET_SPOT"
        elif ratio < 0.5:
            signal = "POOR_GREEKS"
            is_favorable = False
            
        return {
            "signal": signal,
            "gamma_theta_ratio": round(ratio, 2),
            "theta_decay_pct": round(theta_decay_pct, 2),
            "is_favorable": is_favorable,
            "target_strike": float(best_strike_row["strike"])
        }
