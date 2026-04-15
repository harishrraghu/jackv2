"""
OI Analysis — Put-Call Ratio, Max Pain, OI Buildup Classification.

Deterministic analysis of option chain open interest data:
- PCR (Put-Call Ratio) from OI and volume
- Max Pain calculation (strike where option buyers lose most)
- OI Buildup classifier (long/short buildup, covering, unwinding)
- Support/Resistance from high-OI strikes
- Whale detection (unusual OI changes)

Usage:
    from indicators.oi_analysis import OIAnalyzer
    analyzer = OIAnalyzer()
    pcr = analyzer.compute_pcr(chain_df)
    max_pain = analyzer.compute_max_pain(chain_df, spot)
    buildup = analyzer.classify_buildup(chain_df, prev_chain_df)
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Registry-compatible metadata so IndicatorRegistry auto-discovers this module
METADATA = {
    "name": "oi_analysis",
    "display_name": "OI Analysis (PCR / Max Pain / Buildup)",
    "params": {},
    "output_columns": ["PCR", "MaxPain", "OI_Signal"],
    "timeframes": ["1d"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """No-op compute for registry compatibility.

    OI analysis requires option-chain data, not OHLC candles.
    Use OIAnalyzer class methods directly with chain DataFrames.
    """
    return df


class OIAnalyzer:
    """
    Deterministic OI analysis engine.
    
    All methods accept option chain DataFrames (from DhanFetcher) and
    return structured analysis results.
    """

    def __init__(self, lot_size: int = 15, strike_interval: int = 100):
        """
        Args:
            lot_size: Contract lot size (BankNifty = 15).
            strike_interval: Strike interval (BankNifty = 100).
        """
        self.lot_size = lot_size
        self.strike_interval = strike_interval

    # =========================================================================
    # Put-Call Ratio
    # =========================================================================

    def compute_pcr(self, chain: pd.DataFrame, 
                     method: str = "oi") -> dict:
        """
        Compute Put-Call Ratio.
        
        Args:
            chain: Option chain DataFrame with ce_oi, pe_oi, ce_volume, pe_volume.
            method: "oi" for OI-based PCR, "volume" for volume-based.
            
        Returns:
            Dict with pcr, interpretation, and raw totals.
        """
        if chain is None or chain.empty:
            return {"pcr": None, "interpretation": "no_data"}
        
        if method == "oi":
            total_ce = chain["ce_oi"].sum()
            total_pe = chain["pe_oi"].sum()
        elif method == "volume":
            total_ce = chain["ce_volume"].sum()
            total_pe = chain["pe_volume"].sum()
        else:
            total_ce = chain["ce_oi"].sum()
            total_pe = chain["pe_oi"].sum()
        
        if total_ce == 0:
            return {"pcr": None, "interpretation": "no_ce_data"}
        
        pcr = total_pe / total_ce
        
        # Interpretation thresholds (India-specific for BankNifty)
        if pcr > 1.5:
            interpretation = "extreme_bullish"  # Excessive put writing = support
            signal = "LONG"
        elif pcr > 1.2:
            interpretation = "bullish"
            signal = "LONG"
        elif pcr > 0.8:
            interpretation = "neutral"
            signal = "NEUTRAL"
        elif pcr > 0.5:
            interpretation = "bearish"
            signal = "SHORT"
        else:
            interpretation = "extreme_bearish"  # Excessive call writing = resistance
            signal = "SHORT"
        
        return {
            "pcr": round(pcr, 3),
            "total_ce_oi": int(total_ce),
            "total_pe_oi": int(total_pe),
            "interpretation": interpretation,
            "signal": signal,
            "method": method,
        }

    # =========================================================================
    # Max Pain
    # =========================================================================

    def compute_max_pain(self, chain: pd.DataFrame, 
                          spot: float = None) -> dict:
        """
        Compute Max Pain — the strike where total option buyer loss is maximum.
        
        For each candidate strike, compute:
        - CE buyer loss = sum of (max(0, strike - K)) * CE_OI for all call strikes K
        - PE buyer loss = sum of (max(0, K - strike)) * PE_OI for all put strikes K
        - Total loss = CE loss + PE loss
        
        Max pain = strike with highest total loss.
        
        Args:
            chain: Option chain DataFrame.
            spot: Current spot price (for distance calculation).
            
        Returns:
            Dict with max_pain strike, losses, and spot relationship.
        """
        if chain is None or chain.empty:
            return {"max_pain": None}
        
        strikes = chain["strike"].values
        ce_oi = chain["ce_oi"].values
        pe_oi = chain["pe_oi"].values
        
        max_total_loss = -1
        max_pain_strike = 0
        loss_at_strikes = {}
        
        for candidate in strikes:
            # CE buyer loss if expiry at candidate
            ce_loss = 0
            for i, k in enumerate(strikes):
                intrinsic_ce = max(0, candidate - k)
                ce_loss += intrinsic_ce * ce_oi[i]
            
            # PE buyer loss if expiry at candidate
            pe_loss = 0
            for i, k in enumerate(strikes):
                intrinsic_pe = max(0, k - candidate)
                pe_loss += intrinsic_pe * pe_oi[i]
            
            total_loss = ce_loss + pe_loss
            loss_at_strikes[float(candidate)] = total_loss
            
            if total_loss > max_total_loss:
                max_total_loss = total_loss
                max_pain_strike = candidate
        
        result = {
            "max_pain": float(max_pain_strike),
            "total_buyer_loss": float(max_total_loss),
        }
        
        if spot is not None:
            distance = spot - max_pain_strike
            result["distance_from_spot"] = round(distance, 2)
            result["distance_pct"] = round(distance / spot * 100, 3) if spot > 0 else 0
            
            # Max pain pull direction
            if distance > 0:
                result["pull_direction"] = "DOWN"  # Spot above max pain
            elif distance < 0:
                result["pull_direction"] = "UP"    # Spot below max pain
            else:
                result["pull_direction"] = "AT_MAXPAIN"
        
        return result

    # =========================================================================
    # OI-Based Support/Resistance
    # =========================================================================

    def compute_oi_levels(self, chain: pd.DataFrame, 
                           spot: float, 
                           top_n: int = 3) -> dict:
        """
        Find support and resistance levels from high-OI strikes.
        
        CE OI concentration = Resistance (writers don't want price above)
        PE OI concentration = Support (writers don't want price below)
        
        Args:
            chain: Option chain DataFrame.
            spot: Current spot price.
            top_n: Number of top levels to return.
            
        Returns:
            Dict with support_levels, resistance_levels, immediate_range.
        """
        if chain is None or chain.empty:
            return {"support_levels": [], "resistance_levels": []}
        
        # Resistance: high CE OI at strikes above spot
        ce_above = chain[chain["strike"] >= spot].nlargest(top_n, "ce_oi")
        resistance = [
            {"strike": float(r["strike"]), "oi": int(r["ce_oi"])}
            for _, r in ce_above.iterrows()
        ]
        
        # Support: high PE OI at strikes below spot
        pe_below = chain[chain["strike"] <= spot].nlargest(top_n, "pe_oi")
        support = [
            {"strike": float(r["strike"]), "oi": int(r["pe_oi"])}
            for _, r in pe_below.iterrows()
        ]
        
        # Immediate range
        nearest_resistance = resistance[0]["strike"] if resistance else spot + self.strike_interval
        nearest_support = support[0]["strike"] if support else spot - self.strike_interval
        
        return {
            "resistance_levels": resistance,
            "support_levels": support,
            "immediate_range": {
                "upper": nearest_resistance,
                "lower": nearest_support,
                "width": nearest_resistance - nearest_support,
            },
        }

    # =========================================================================
    # OI Buildup Classifier
    # =========================================================================

    def classify_buildup(self, current_chain: pd.DataFrame,
                          prev_chain: pd.DataFrame = None,
                          spot: float = None) -> dict:
        """
        Classify OI buildup patterns.
        
        If previous chain is available (for change-in-OI):
        - Price UP + OI UP = Long Buildup (bullish)
        - Price DOWN + OI UP = Short Buildup (bearish)
        - Price UP + OI DOWN = Short Covering (bullish, weak)
        - Price DOWN + OI DOWN = Long Unwinding (bearish, weak)
        
        Without previous data, uses change_oi columns if available.
        
        Returns:
            Dict with classification, confidence, and details.
        """
        if current_chain is None or current_chain.empty:
            return {"classification": "no_data", "confidence": 0}
        
        # Use change_oi columns if available
        has_change_oi = ("ce_change_oi" in current_chain.columns and 
                         "pe_change_oi" in current_chain.columns)
        
        if has_change_oi:
            total_ce_change = current_chain["ce_change_oi"].sum()
            total_pe_change = current_chain["pe_change_oi"].sum()
        elif prev_chain is not None and not prev_chain.empty:
            # Compute change from previous chain
            merged = current_chain[["strike", "ce_oi", "pe_oi"]].merge(
                prev_chain[["strike", "ce_oi", "pe_oi"]],
                on="strike", suffixes=("", "_prev")
            )
            total_ce_change = (merged["ce_oi"] - merged["ce_oi_prev"]).sum()
            total_pe_change = (merged["pe_oi"] - merged["pe_oi_prev"]).sum()
        else:
            return {
                "classification": "insufficient_data",
                "confidence": 0,
                "note": "Need previous chain or change_oi data",
            }
        
        # Determine buildup pattern
        ce_writing_up = total_ce_change > 0
        pe_writing_up = total_pe_change > 0
        
        net_change = total_pe_change - total_ce_change
        
        if pe_writing_up and not ce_writing_up:
            classification = "long_buildup"
            signal = "LONG"
            confidence = min(abs(net_change) / 100000, 1.0)
        elif ce_writing_up and not pe_writing_up:
            classification = "short_buildup"
            signal = "SHORT"
            confidence = min(abs(net_change) / 100000, 1.0)
        elif pe_writing_up and ce_writing_up:
            if total_pe_change > total_ce_change:
                classification = "mixed_bullish"
                signal = "LONG"
            else:
                classification = "mixed_bearish"
                signal = "SHORT"
            confidence = min(abs(net_change) / 200000, 0.6)
        else:
            # Both declining
            classification = "unwinding"
            signal = "NEUTRAL"
            confidence = 0.3
        
        return {
            "classification": classification,
            "signal": signal,
            "confidence": round(confidence, 3),
            "ce_oi_change": int(total_ce_change),
            "pe_oi_change": int(total_pe_change),
            "net_change": int(net_change),
        }

    # =========================================================================
    # Trap Detection
    # =========================================================================

    def detect_trap(self, chain: pd.DataFrame, spot: float,
                     prev_spot: float = None) -> dict:
        """
        Detect potential bull/bear traps from OI patterns.
        
        Bear Trap: Price breaks below support but PE OI is unwinding
                   (put sellers closing -> support will hold)
        Bull Trap: Price breaks above resistance but CE OI is unwinding
                   (call sellers closing -> resistance will hold)
        
        Returns:
            Dict with trap_type, probability, and details.
        """
        if chain is None or chain.empty or spot is None:
            return {"trap_type": "none", "probability": 0}
        
        oi_levels = self.compute_oi_levels(chain, spot)
        
        # Find if we're near a high-OI strike
        nearest_ce_resistance = oi_levels["resistance_levels"][0]["strike"] if oi_levels["resistance_levels"] else None
        nearest_pe_support = oi_levels["support_levels"][0]["strike"] if oi_levels["support_levels"] else None
        
        trap_type = "none"
        probability = 0.0
        details = ""
        
        # Check for bull trap (price near/above resistance but CE OI declining)
        if nearest_ce_resistance and spot >= nearest_ce_resistance * 0.998:
            # Check if CE OI at this strike is showing unwinding
            ce_at_resistance = chain[chain["strike"] == nearest_ce_resistance]
            if not ce_at_resistance.empty:
                if "ce_change_oi" in ce_at_resistance.columns:
                    change = ce_at_resistance.iloc[0]["ce_change_oi"]
                    if change < 0:
                        trap_type = "bull_trap"
                        probability = 0.6
                        details = (f"Price at resistance {nearest_ce_resistance} "
                                   f"but CE OI declining ({change})")
        
        # Check for bear trap (price near/below support but PE OI declining)
        if nearest_pe_support and spot <= nearest_pe_support * 1.002:
            pe_at_support = chain[chain["strike"] == nearest_pe_support]
            if not pe_at_support.empty:
                if "pe_change_oi" in pe_at_support.columns:
                    change = pe_at_support.iloc[0]["pe_change_oi"]
                    if change < 0:
                        trap_type = "bear_trap"
                        probability = 0.6
                        details = (f"Price at support {nearest_pe_support} "
                                   f"but PE OI declining ({change})")
        
        return {
            "trap_type": trap_type,
            "probability": round(probability, 3),
            "details": details,
        }

    # =========================================================================
    # Full OI Summary
    # =========================================================================

    def full_analysis(self, chain: pd.DataFrame, spot: float,
                       prev_chain: pd.DataFrame = None) -> dict:
        """
        Run complete OI analysis and return structured summary.
        
        Returns:
            Dict with pcr, max_pain, levels, buildup, trap.
        """
        # Filter chain to ±15% of spot for max pain + levels (removes far-OTM noise)
        if spot and spot > 0:
            lo = spot * 0.85
            hi = spot * 1.15
            relevant_chain = chain[(chain["strike"] >= lo) & (chain["strike"] <= hi)]
            if relevant_chain.empty:
                relevant_chain = chain  # fallback if filter is too tight
        else:
            relevant_chain = chain

        pcr = self.compute_pcr(relevant_chain)
        pcr_volume = self.compute_pcr(relevant_chain, method="volume")
        max_pain = self.compute_max_pain(relevant_chain, spot)
        levels = self.compute_oi_levels(relevant_chain, spot)
        buildup = self.classify_buildup(chain, prev_chain, spot)
        trap = self.detect_trap(chain, spot)
        
        # Overall signal aggregation
        signals = []
        if pcr.get("signal"): signals.append(pcr["signal"])
        if buildup.get("signal"): signals.append(buildup["signal"])
        if max_pain.get("pull_direction"):
            if max_pain["pull_direction"] == "DOWN":
                signals.append("SHORT")
            elif max_pain["pull_direction"] == "UP":
                signals.append("LONG")
        
        long_votes = signals.count("LONG")
        short_votes = signals.count("SHORT")
        neutral_votes = signals.count("NEUTRAL")
        
        if long_votes > short_votes:
            overall_signal = "LONG"
        elif short_votes > long_votes:
            overall_signal = "SHORT"
        else:
            overall_signal = "NEUTRAL"
        
        return {
            "pcr_oi": pcr,
            "pcr_volume": pcr_volume,
            "max_pain": max_pain,
            "oi_levels": levels,
            "buildup": buildup,
            "trap": trap,
            "overall_signal": overall_signal,
            "signal_votes": {
                "long": long_votes,
                "short": short_votes,
                "neutral": neutral_votes,
            },
            "spot": spot,
        }
