"""
Strike Selector v2 — Greeks-based option strike selection.

Enhanced strike selector that scores available strikes using:
- Delta (target range: 0.45-0.65 for directional)
- Theta decay (minimize daily bleed)
- Bid-ask spread (liquidity)
- OI concentration (high OI = better liquidity)
- IV relative to ATM (avoid overpaying)

Replaces the basic ATM/OTM selector in engine/options.py.

Usage:
    from engine.strike_selector import StrikeSelectorV2
    selector = StrikeSelectorV2()
    pick = selector.select_best(chain_df, spot=52100, direction="LONG")
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class StrikeSelectorV2:
    """
    Advanced strike selection using real option chain data and Greeks.
    """

    def __init__(self, lot_size: int = 15, strike_interval: int = 100):
        """
        Args:
            lot_size: Contract lot size.
            strike_interval: Strike price interval.
        """
        self.lot_size = lot_size
        self.strike_interval = strike_interval

    def select_best(self, chain: pd.DataFrame, spot: float,
                     direction: str, strategy: str = "directional",
                     max_premium: float = None,
                     days_to_expiry: float = 1.0) -> dict:
        """
        Select the best strike from the option chain.
        
        Args:
            chain: Option chain DataFrame (from DhanFetcher).
            spot: Current spot price.
            direction: "LONG" or "SHORT".
            strategy: "directional" (buy ATM/ITM) or "hedged" (spread).
            max_premium: Maximum acceptable premium per lot.
            days_to_expiry: Trading days to expiry.
            
        Returns:
            Dict with selected strike, option_type, premium, greeks, score.
        """
        if chain is None or chain.empty:
            return self._fallback_selection(spot, direction)
        
        option_type = "CE" if direction == "LONG" else "PE"
        atm_strike = round(spot / self.strike_interval) * self.strike_interval
        
        # Define candidate range: ATM +- 5 strikes
        candidates = self._get_candidates(chain, spot, direction, n_strikes=5)
        
        if candidates.empty:
            return self._fallback_selection(spot, direction)
        
        # Score each candidate
        scored = self._score_candidates(candidates, spot, direction, 
                                        days_to_expiry, max_premium)
        
        if scored.empty:
            return self._fallback_selection(spot, direction)
        
        # Select highest scored
        best = scored.iloc[0]
        
        prefix = "ce" if direction == "LONG" else "pe"
        
        result = {
            "strike": float(best["strike"]),
            "option_type": option_type,
            "premium": float(best.get(f"{prefix}_ltp", 0)),
            "delta": float(best.get(f"{prefix}_delta", 0)),
            "gamma": float(best.get(f"{prefix}_gamma", 0)),
            "theta": float(best.get(f"{prefix}_theta", 0)),
            "vega": float(best.get(f"{prefix}_vega", 0)),
            "iv": float(best.get(f"{prefix}_iv", 0)),
            "oi": int(best.get(f"{prefix}_oi", 0)),
            "score": float(best.get("total_score", 0)),
            "atm_strike": atm_strike,
            "spot": spot,
            "direction": direction,
            "moneyness": self._classify_moneyness(
                float(best["strike"]), spot, direction
            ),
            "lot_cost": float(best.get(f"{prefix}_ltp", 0)) * self.lot_size,
            "security_id": best.get(f"{prefix}_security_id", ""),
        }
        
        # Add stop loss and target suggestions
        premium = result["premium"]
        if premium > 0:
            result["suggested_sl"] = round(premium * 0.75, 2)      # 25% loss
            result["suggested_target"] = round(premium * 1.5, 2)    # 50% gain
            result["risk_reward"] = "1:2"
        
        return result

    def select_spread(self, chain: pd.DataFrame, spot: float,
                       direction: str, width: int = 1) -> dict:
        """
        Select strikes for a vertical spread.
        
        Args:
            chain: Option chain DataFrame.
            spot: Current spot price.
            direction: "LONG" for bull call spread, "SHORT" for bear put spread.
            width: Number of strikes wide.
            
        Returns:
            Dict with buy_strike, sell_strike, max_profit, max_loss.
        """
        atm_strike = round(spot / self.strike_interval) * self.strike_interval
        
        if direction == "LONG":
            # Bull call spread: Buy ATM CE, Sell OTM CE
            buy_strike = atm_strike
            sell_strike = atm_strike + (width * self.strike_interval)
            
            buy_row = chain[chain["strike"] == buy_strike]
            sell_row = chain[chain["strike"] == sell_strike]
            
            if buy_row.empty or sell_row.empty:
                return {"error": "Strikes not available"}
            
            buy_premium = float(buy_row.iloc[0].get("ce_ltp", 0))
            sell_premium = float(sell_row.iloc[0].get("ce_ltp", 0))
            net_debit = buy_premium - sell_premium
            max_profit = (sell_strike - buy_strike) - net_debit
            
            return {
                "strategy": "bull_call_spread",
                "buy_strike": buy_strike,
                "sell_strike": sell_strike,
                "buy_premium": round(buy_premium, 2),
                "sell_premium": round(sell_premium, 2),
                "net_debit": round(net_debit, 2),
                "max_profit": round(max_profit, 2),
                "max_loss": round(net_debit, 2),
                "lot_cost": round(net_debit * self.lot_size, 2),
                "breakeven": buy_strike + net_debit,
            }
        else:
            # Bear put spread: Buy ATM PE, Sell OTM PE
            buy_strike = atm_strike
            sell_strike = atm_strike - (width * self.strike_interval)
            
            buy_row = chain[chain["strike"] == buy_strike]
            sell_row = chain[chain["strike"] == sell_strike]
            
            if buy_row.empty or sell_row.empty:
                return {"error": "Strikes not available"}
            
            buy_premium = float(buy_row.iloc[0].get("pe_ltp", 0))
            sell_premium = float(sell_row.iloc[0].get("pe_ltp", 0))
            net_debit = buy_premium - sell_premium
            max_profit = (buy_strike - sell_strike) - net_debit
            
            return {
                "strategy": "bear_put_spread",
                "buy_strike": buy_strike,
                "sell_strike": sell_strike,
                "buy_premium": round(buy_premium, 2),
                "sell_premium": round(sell_premium, 2),
                "net_debit": round(net_debit, 2),
                "max_profit": round(max_profit, 2),
                "max_loss": round(net_debit, 2),
                "lot_cost": round(net_debit * self.lot_size, 2),
                "breakeven": buy_strike - net_debit,
            }

    # =========================================================================
    # Internal Scoring
    # =========================================================================

    def _get_candidates(self, chain: pd.DataFrame, spot: float,
                         direction: str, n_strikes: int = 5) -> pd.DataFrame:
        """Get candidate strikes around ATM."""
        atm = round(spot / self.strike_interval) * self.strike_interval
        
        if direction == "LONG":
            # For calls: ATM to slightly ITM (2 below ATM, 3 above)
            lower = atm - (2 * self.strike_interval)
            upper = atm + (n_strikes * self.strike_interval)
        else:
            # For puts: ATM to slightly ITM
            lower = atm - (n_strikes * self.strike_interval)
            upper = atm + (2 * self.strike_interval)
        
        return chain[(chain["strike"] >= lower) & 
                     (chain["strike"] <= upper)].copy()

    def _score_candidates(self, candidates: pd.DataFrame, spot: float,
                           direction: str, dte: float,
                           max_premium: float = None) -> pd.DataFrame:
        """
        Score candidate strikes across multiple criteria.
        
        Scoring weights:
            Delta score: 30% (prefer 0.45-0.65 range)
            Theta score: 20% (less decay = better)
            Spread score: 20% (tighter bid-ask = better liquidity)
            OI score: 15% (higher OI = better liquidity)
            IV score: 15% (prefer lower IV relative to ATM)
        """
        prefix = "ce" if direction == "LONG" else "pe"
        
        df = candidates.copy()
        
        # Filter out zero-premium strikes
        df = df[df[f"{prefix}_ltp"] > 0]
        
        # Filter by max premium if specified
        if max_premium is not None:
            df = df[df[f"{prefix}_ltp"] <= max_premium]
        
        if df.empty:
            return df
        
        # --- Delta Score (30%) ---
        # Target: 0.45-0.65 for directional trades
        target_delta = 0.55
        delta_col = f"{prefix}_delta"
        if delta_col in df.columns and df[delta_col].abs().sum() > 0:
            deltas = df[delta_col].abs()
            df["delta_score"] = 1.0 - (deltas - target_delta).abs() / 0.5
            df["delta_score"] = df["delta_score"].clip(0, 1)
        else:
            # Estimate delta from moneyness
            df["delta_score"] = df["strike"].apply(
                lambda k: self._estimate_delta_score(k, spot, direction)
            )
        
        # --- Theta Score (20%) ---
        theta_col = f"{prefix}_theta"
        if theta_col in df.columns and df[theta_col].abs().sum() > 0:
            max_theta = df[theta_col].abs().max()
            if max_theta > 0:
                df["theta_score"] = 1.0 - df[theta_col].abs() / max_theta
            else:
                df["theta_score"] = 0.5
        else:
            # More OTM = worse theta-to-premium ratio
            df["theta_score"] = 0.5
        
        # --- Spread Score (20%) ---
        bid_col = f"{prefix}_bid"
        ask_col = f"{prefix}_ask"
        if bid_col in df.columns and ask_col in df.columns:
            df["spread"] = (df[ask_col] - df[bid_col]).clip(0)
            max_spread = df["spread"].max()
            if max_spread > 0:
                df["spread_score"] = 1.0 - df["spread"] / max_spread
            else:
                df["spread_score"] = 1.0
        else:
            df["spread_score"] = 0.5
        
        # --- OI Score (15%) ---
        oi_col = f"{prefix}_oi"
        if oi_col in df.columns:
            max_oi = df[oi_col].max()
            if max_oi > 0:
                df["oi_score"] = df[oi_col] / max_oi
            else:
                df["oi_score"] = 0.5
        else:
            df["oi_score"] = 0.5
        
        # --- IV Score (15%) ---
        iv_col = f"{prefix}_iv"
        if iv_col in df.columns and df[iv_col].sum() > 0:
            min_iv = df[iv_col].min()
            max_iv = df[iv_col].max()
            if max_iv > min_iv:
                df["iv_score"] = 1.0 - (df[iv_col] - min_iv) / (max_iv - min_iv)
            else:
                df["iv_score"] = 0.5
        else:
            df["iv_score"] = 0.5
        
        # --- Total Score ---
        df["total_score"] = (
            df["delta_score"] * 0.30 +
            df["theta_score"] * 0.20 +
            df["spread_score"] * 0.20 +
            df["oi_score"] * 0.15 +
            df["iv_score"] * 0.15
        )
        
        return df.sort_values("total_score", ascending=False)

    def _estimate_delta_score(self, strike: float, spot: float, 
                               direction: str) -> float:
        """Estimate delta score from moneyness when Greeks unavailable."""
        if direction == "LONG":
            moneyness = (spot - strike) / self.strike_interval
        else:
            moneyness = (strike - spot) / self.strike_interval
        
        # ITM 1-2 strikes deep: good delta range
        if 0 <= moneyness <= 1:
            return 0.9
        elif -1 <= moneyness < 0:
            return 0.7  # Slightly OTM
        elif 1 < moneyness <= 2:
            return 0.6  # Deep ITM
        else:
            return 0.3  # Far OTM or deep ITM

    def _classify_moneyness(self, strike: float, spot: float, 
                             direction: str) -> str:
        """Classify strike as ATM, ITM, or OTM."""
        distance = abs(strike - spot)
        if distance < self.strike_interval * 0.5:
            return "ATM"
        
        if direction == "LONG":
            return "ITM" if strike < spot else "OTM"
        else:
            return "ITM" if strike > spot else "OTM"

    def _fallback_selection(self, spot: float, direction: str) -> dict:
        """Fallback when no chain data available."""
        atm = round(spot / self.strike_interval) * self.strike_interval
        option_type = "CE" if direction == "LONG" else "PE"
        
        return {
            "strike": atm,
            "option_type": option_type,
            "premium": 0,
            "delta": 0.5 if direction == "LONG" else -0.5,
            "theta": 0,
            "vega": 0,
            "gamma": 0,
            "iv": 0,
            "oi": 0,
            "score": 0,
            "atm_strike": atm,
            "spot": spot,
            "direction": direction,
            "moneyness": "ATM",
            "lot_cost": 0,
            "note": "Fallback selection — no chain data available",
        }
