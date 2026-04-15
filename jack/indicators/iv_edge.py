"""
IV Edge Analysis — Implied vs Realized Volatility Comparison.

Analyzes if options are currently cheap or expensive.
Compares Realized Volatility (RV) from price action against Implied Volatility (IV) from the option chain.
"""

import logging
from typing import Optional
import pandas as pd
import numpy as np
import math

logger = logging.getLogger(__name__)

METADATA = {
    "name": "iv_edge",
    "display_name": "IV vs RV Edge Analysis",
    "params": {},
    "output_columns": ["IV_Edge_Signal", "VRP"],
    "timeframes": ["1d"],
}

def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """No-op for registry compatibility. Use IVEdgeAnalyzer class methods."""
    return df

class IVEdgeAnalyzer:
    """Deterministic IV Edge analysis engine."""

    def __init__(self, rv_window: int = 14):
        self.rv_window = rv_window

    def compute_rv(self, daily_df: pd.DataFrame) -> float:
        """
        Compute Realized Volatility (annualized) using Parkinson estimator.
        Parkinson uses High and Low prices for better intraday capture.
        """
        if daily_df is None or daily_df.empty or len(daily_df) < 5:
            return 15.0 # Fallback default
        
        # We need recent window
        df = daily_df.tail(self.rv_window).copy()
        
        # Parkinson estimator: sum(log(H/L)^2) / (4*n*ln(2))
        try:
            hl_ratio = np.log(df['High'] / df['Low'])
            parkinson_var = (1.0 / (4.0 * len(df) * math.log(2))) * np.sum(hl_ratio**2)
            rv_daily = math.sqrt(parkinson_var)
            rv_annualized = rv_daily * math.sqrt(252) * 100
            return round(rv_annualized, 2)
        except Exception as e:
            logger.warning(f"Failed to compute RV: {e}")
            return 15.0

    def analyze(self, atm_iv: float, daily_df: pd.DataFrame, current_vix: float = None) -> dict:
        """
        Analyze current IV edge based on RV and VIX.
        """
        if not atm_iv or atm_iv <= 0:
            return {"vrp_signal": "NEUTRAL", "vrp_ratio": 1.0, "is_cheap": False, "is_expensive": False}
            
        rv = self.compute_rv(daily_df)
        
        # Volatility Risk Premium (VRP) ratio -> IV / RV
        vrp_ratio = atm_iv / rv if rv > 0 else 1.0
        
        signal = "NEUTRAL"
        is_cheap = False
        is_expensive = False
        
        if vrp_ratio < 0.85:
            signal = "IV_CHEAP"
            is_cheap = True
        elif vrp_ratio > 1.3:
            signal = "IV_EXPENSIVE"
            is_expensive = True
            
        return {
            "atm_iv": round(atm_iv, 2),
            "rv": rv,
            "vrp_ratio": round(vrp_ratio, 3),
            "vrp_signal": signal,
            "is_cheap": is_cheap,
            "is_expensive": is_expensive
        }
