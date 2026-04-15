"""
IV Analysis — Implied Volatility Rank, Percentile, Skew, and Regime.

Deterministic IV analysis from option chain data:
- IV Rank: Where current IV sits relative to 52-week range
- IV Percentile: % of days in last year with IV below current
- IV Skew: Put IV vs Call IV imbalance (fear gauge)
- IV Regime: low / normal / elevated / extreme classification

Usage:
    from indicators.iv_analysis import IVAnalyzer
    analyzer = IVAnalyzer()
    result = analyzer.analyze(chain_df, historical_iv_values)
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Registry-compatible metadata so IndicatorRegistry auto-discovers this module
METADATA = {
    "name": "iv_analysis",
    "display_name": "IV Analysis (Rank / Percentile / Skew / Regime)",
    "params": {},
    "output_columns": ["IV_Rank", "IV_Regime"],
    "timeframes": ["1d"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """No-op compute for registry compatibility.

    IV analysis requires option-chain data, not OHLC candles.
    Use IVAnalyzer class methods directly with chain DataFrames.
    """
    return df


class IVAnalyzer:
    """
    Implied Volatility analysis engine.
    
    Computes IV metrics from option chain data to determine
    whether options are cheap/expensive and whether fear is elevated.
    """

    def __init__(self, strike_interval: int = 100):
        """
        Args:
            strike_interval: Strike interval for ATM determination.
        """
        self.strike_interval = strike_interval

    # =========================================================================
    # ATM IV Extraction
    # =========================================================================

    def get_atm_iv(self, chain: pd.DataFrame, spot: float) -> dict:
        """
        Extract ATM implied volatility for both CE and PE.
        
        Args:
            chain: Option chain DataFrame with ce_iv, pe_iv, strike.
            spot: Current spot price.
            
        Returns:
            Dict with ce_iv, pe_iv, avg_iv, atm_strike.
        """
        if chain is None or chain.empty or spot is None:
            return {"atm_iv": None}
        
        # Find ATM strike
        atm_strike = round(spot / self.strike_interval) * self.strike_interval
        
        atm_row = chain[chain["strike"] == atm_strike]
        if atm_row.empty:
            # Find nearest available strike
            chain["dist"] = abs(chain["strike"] - spot)
            atm_row = chain.nsmallest(1, "dist")
            atm_strike = float(atm_row.iloc[0]["strike"])
        
        if atm_row.empty:
            return {"atm_iv": None}
        
        ce_iv = float(atm_row.iloc[0].get("ce_iv", 0))
        pe_iv = float(atm_row.iloc[0].get("pe_iv", 0))
        
        # Average IV (common market convention)
        valid_ivs = [iv for iv in [ce_iv, pe_iv] if iv > 0]
        avg_iv = sum(valid_ivs) / len(valid_ivs) if valid_ivs else 0
        
        return {
            "atm_strike": atm_strike,
            "ce_iv": round(ce_iv, 2),
            "pe_iv": round(pe_iv, 2),
            "atm_iv": round(avg_iv, 2),
        }

    # =========================================================================
    # IV Rank
    # =========================================================================

    def compute_iv_rank(self, current_iv: float, 
                         iv_history: list[float]) -> dict:
        """
        IV Rank = (Current IV - 52w Low) / (52w High - 52w Low) * 100.
        
        Tells where current IV sits in its year range.
        0 = at yearly low, 100 = at yearly high.
        
        Args:
            current_iv: Current ATM IV.
            iv_history: List of historical IV values (ideally 252 trading days).
            
        Returns:
            Dict with iv_rank, yearly_high, yearly_low.
        """
        if not iv_history or current_iv is None:
            return {"iv_rank": None}
        
        iv_high = max(iv_history)
        iv_low = min(iv_history)
        
        if iv_high == iv_low:
            return {"iv_rank": 50.0, "iv_high": iv_high, "iv_low": iv_low}
        
        iv_rank = (current_iv - iv_low) / (iv_high - iv_low) * 100
        
        return {
            "iv_rank": round(iv_rank, 1),
            "iv_high": round(iv_high, 2),
            "iv_low": round(iv_low, 2),
            "current_iv": round(current_iv, 2),
        }

    # =========================================================================
    # IV Percentile
    # =========================================================================

    def compute_iv_percentile(self, current_iv: float, 
                               iv_history: list[float]) -> dict:
        """
        IV Percentile = % of historical observations below current IV.
        
        More robust than IV Rank as it accounts for distribution shape.
        
        Args:
            current_iv: Current ATM IV.
            iv_history: List of historical IV values.
            
        Returns:
            Dict with iv_percentile, sample_size.
        """
        if not iv_history or current_iv is None:
            return {"iv_percentile": None}
        
        below = sum(1 for iv in iv_history if iv < current_iv)
        percentile = below / len(iv_history) * 100
        
        return {
            "iv_percentile": round(percentile, 1),
            "sample_size": len(iv_history),
        }

    # =========================================================================
    # IV Skew
    # =========================================================================

    def compute_iv_skew(self, chain: pd.DataFrame, spot: float,
                         otm_distance: int = 2) -> dict:
        """
        Compute IV Skew — Put IV vs Call IV for OTM options.
        
        Positive skew = puts more expensive than calls (fear).
        Negative skew = calls more expensive than puts (greed/FOMO).
        
        Args:
            chain: Option chain DataFrame.
            spot: Current spot price.
            otm_distance: Number of strikes OTM to measure.
            
        Returns:
            Dict with skew value, interpretation.
        """
        if chain is None or chain.empty or spot is None:
            return {"iv_skew": None}
        
        atm_strike = round(spot / self.strike_interval) * self.strike_interval
        
        # Get OTM strikes
        otm_ce_strike = atm_strike + (otm_distance * self.strike_interval)
        otm_pe_strike = atm_strike - (otm_distance * self.strike_interval)
        
        otm_ce = chain[chain["strike"] == otm_ce_strike]
        otm_pe = chain[chain["strike"] == otm_pe_strike]
        
        if otm_ce.empty or otm_pe.empty:
            return {"iv_skew": None, "note": "OTM strikes not found"}
        
        ce_iv = float(otm_ce.iloc[0].get("ce_iv", 0))
        pe_iv = float(otm_pe.iloc[0].get("pe_iv", 0))
        
        if ce_iv == 0 or pe_iv == 0:
            return {"iv_skew": None, "note": "Zero IV on OTM strikes"}
        
        skew = pe_iv - ce_iv
        skew_ratio = pe_iv / ce_iv if ce_iv > 0 else 1.0
        
        # Interpretation
        if skew > 5:
            interpretation = "high_fear"  # Puts significantly more expensive
        elif skew > 2:
            interpretation = "moderate_fear"
        elif skew > -2:
            interpretation = "neutral"
        elif skew > -5:
            interpretation = "moderate_greed"
        else:
            interpretation = "high_greed"
        
        return {
            "iv_skew": round(skew, 2),
            "skew_ratio": round(skew_ratio, 3),
            "otm_ce_iv": round(ce_iv, 2),
            "otm_pe_iv": round(pe_iv, 2),
            "otm_ce_strike": otm_ce_strike,
            "otm_pe_strike": otm_pe_strike,
            "interpretation": interpretation,
        }

    # =========================================================================
    # IV Regime Classification
    # =========================================================================

    def classify_iv_regime(self, current_iv: float, 
                            iv_history: list[float] = None,
                            vix: float = None) -> dict:
        """
        Classify the current IV environment.
        
        Uses either ATM IV or India VIX as proxy.
        
        Regimes (for BankNifty proxy via VIX):
            < 12: low_iv (options cheap, good for buying)
            12-16: normal_iv
            16-22: elevated_iv
            > 22: extreme_iv (options expensive, sell strategies favored)
            
        With IV Rank:
            < 20: low_iv
            20-50: normal_iv
            50-80: elevated_iv
            > 80: extreme_iv
            
        Returns:
            Dict with regime, strategy_implication.
        """
        regime = "normal_iv"
        implication = "Normal options pricing"
        
        # Prefer IV rank if history available
        if iv_history and current_iv is not None:
            rank_data = self.compute_iv_rank(current_iv, iv_history)
            iv_rank = rank_data.get("iv_rank", 50)
            
            if iv_rank is not None:
                if iv_rank < 20:
                    regime = "low_iv"
                    implication = "IV is low — options are cheap. Buy strategies preferred."
                elif iv_rank < 50:
                    regime = "normal_iv"
                    implication = "IV is normal — both buy and sell strategies viable."
                elif iv_rank < 80:
                    regime = "elevated_iv"
                    implication = "IV is elevated — sell strategies preferred. Wider stops needed."
                else:
                    regime = "extreme_iv"
                    implication = "IV is extreme — strong mean reversion expected. Sell strategies only."
        
        # Fallback to VIX if available
        elif vix is not None:
            if vix < 12:
                regime = "low_iv"
                implication = "VIX low — complacent market. Options cheap."
            elif vix < 16:
                regime = "normal_iv"
                implication = "VIX normal."
            elif vix < 22:
                regime = "elevated_iv"
                implication = "VIX elevated — increased uncertainty."
            else:
                regime = "extreme_iv"
                implication = "VIX extreme — high fear. Options very expensive."
        
        return {
            "iv_regime": regime,
            "strategy_implication": implication,
            "current_iv": current_iv,
            "vix": vix,
        }

    # =========================================================================
    # IV Term Structure
    # =========================================================================

    def compute_term_structure(self, near_iv: float, 
                                far_iv: float) -> dict:
        """
        Compute IV term structure (contango vs backwardation).
        
        Normal: Far IV > Near IV (contango — normal time premium)
        Inverted: Near IV > Far IV (backwardation — event/fear premium)
        
        Args:
            near_iv: ATM IV of nearest expiry.
            far_iv: ATM IV of next expiry.
            
        Returns:
            Dict with term_structure type and ratio.
        """
        if not near_iv or not far_iv or near_iv == 0 or far_iv == 0:
            return {"term_structure": "unknown"}
        
        ratio = near_iv / far_iv
        
        if ratio > 1.1:
            structure = "inverted"
            implication = "Event premium in near term. Market expects imminent move."
        elif ratio > 0.95:
            structure = "flat"
            implication = "Normal term structure. No unusual event pricing."
        else:
            structure = "contango"
            implication = "Normal contango. Time premium working normally."
        
        return {
            "term_structure": structure,
            "near_over_far_ratio": round(ratio, 3),
            "near_iv": round(near_iv, 2),
            "far_iv": round(far_iv, 2),
            "implication": implication,
        }

    # =========================================================================
    # Full IV Analysis
    # =========================================================================

    def full_analysis(self, chain: pd.DataFrame, spot: float,
                       iv_history: list[float] = None,
                       vix: float = None) -> dict:
        """
        Run complete IV analysis.
        
        Returns:
            Dict with atm_iv, iv_rank, iv_percentile, iv_skew, iv_regime.
        """
        atm_data = self.get_atm_iv(chain, spot)
        current_iv = atm_data.get("atm_iv")
        
        iv_rank = self.compute_iv_rank(current_iv, iv_history) if iv_history else {"iv_rank": None}
        iv_percentile = self.compute_iv_percentile(current_iv, iv_history) if iv_history else {"iv_percentile": None}
        iv_skew = self.compute_iv_skew(chain, spot)
        iv_regime = self.classify_iv_regime(current_iv, iv_history, vix)
        
        return {
            "atm": atm_data,
            "iv_rank": iv_rank,
            "iv_percentile": iv_percentile,
            "iv_skew": iv_skew,
            "iv_regime": iv_regime,
        }
