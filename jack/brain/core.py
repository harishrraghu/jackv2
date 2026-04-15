"""
Core Brain — The Intelligent Orchestrator for Jack V2.

This module replaces the "multi-agent prompt" system with pure, math-driven logic.
It analyzes 5-day history, VIX, Put-Call Ratio, and Intraday Context to output:
1. Market Regime
2. Directional Bias
3. Strategy Weights (dynamically scaling strategies up or down based on probability)
"""

import logging
import pandas as pd
from typing import Dict, Any

logger = logging.getLogger(__name__)


class IntelligentBrain:
    """
    The central intelligence layer for Options Trading profitability.
    """

    def __init__(self):
        self.default_weights = {
            "first_hour_verdict": 1.2,
            "gap_fill": 1.1,
            "bb_squeeze": 1.0,
            "vwap_reversion": 1.0,
            "iv_expansion_ride": 0.8,
            "oi_confirmed_breakout": 0.8,
            "delta_scalp": 0.5,
            "oi_wall_bounce": 0.9,
        }

    def analyze_5_day_trend(self, df_5d: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyzes the past 5 daily candles to establish market structure.
        Looks for Higher Highs (HH) / Lower Lows (LL) and momentum.
        """
        if df_5d.empty or len(df_5d) < 2:
            return {"trend": "neutral", "momentum": 0.0, "consecutive_moves": 0}

        # Calculate basic price action structure
        closes = df_5d["Close"].values
        opens = df_5d["Open"].values
        
        # Determine consecutive up/down days
        consecutive_moves = 0
        direction = 0
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                if direction >= 0:
                    consecutive_moves += 1
                    direction = 1
                else:
                    consecutive_moves = 1
                    direction = 1
            elif closes[i] < closes[i-1]:
                if direction <= 0:
                    consecutive_moves += 1
                    direction = -1
                else:
                    consecutive_moves = 1
                    direction = -1

        # Calculate distance from 5-day high to low
        max_high = df_5d["High"].max()
        min_low = df_5d["Low"].min()
        range_pct = (max_high - min_low) / min_low * 100

        trend_status = "neutral"
        if direction == 1 and consecutive_moves >= 2:
            trend_status = "bullish"
        elif direction == -1 and consecutive_moves >= 2:
            trend_status = "bearish"
        
        if range_pct < 1.0:
            trend_status = "ranging"

        return {
            "trend": trend_status,
            "momentum_direction": direction,
            "consecutive_moves": consecutive_moves,
            "5_day_range_pct": range_pct,
            "closes": closes.tolist()
        }

    def generate_strategy_weights(self, context: Dict[str, Any], lookback_5d: pd.DataFrame = None) -> Dict[str, float]:
        """
        Takes the morning context (VIX, PCR, Gap) and historical trend.
        Outputs exact weights for the strategies. 0.0 means the strategy is blocked.
        """
        weights = self.default_weights.copy()
        
        # Analyze historical trend if provided
        trend_data = self.analyze_5_day_trend(lookback_5d) if lookback_5d is not None else {}
        trend = trend_data.get("trend", "neutral")
        
        vix = context.get("india_vix")
        pcr_raw = context.get("pcr")
        # pcr may arrive as a bare float or as {"pcr": float, ...}
        if isinstance(pcr_raw, dict):
            pcr = pcr_raw.get("pcr")
        else:
            pcr = pcr_raw

        gap_pct = context.get("gap_pct", 0.0)
        max_pain = context.get("max_pain") or {}
        if not isinstance(max_pain, dict):
            max_pain = {}
        oi_levels = context.get("oi_levels") or {}
        oi_buildup = context.get("oi_buildup") or {}
        atm_iv = context.get("atm_iv")           # Absolute IV value (e.g. 0.18 = 18%)
        iv_regime = context.get("iv_regime", "normal_iv")  # low_iv / normal_iv / elevated_iv / extreme_iv
        dte = context.get("dte")                 # Days to expiry

        logger.info(
            f"[Brain] Context: Trend={trend}, VIX={vix}, PCR={pcr}, Gap={gap_pct}%, "
            f"IV={atm_iv} ({iv_regime}), DTE={dte}"
        )
        if max_pain and max_pain.get("distance_pct"):
            logger.info(
                f"[Brain] MaxPain Pull={max_pain.get('pull_direction')} "
                f"(Dist: {max_pain.get('distance_pct')}%)"
            )

        # 1. First Hour Verdict (Trend Continuation)
        # Highly effective in trending markets. Weaken if ranging.
        if trend == "ranging":
            weights["first_hour_verdict"] *= 0.5
        elif pcr and pcr > 1.2 and gap_pct > 0: 
            # Bullish PCR, Bullish Gap = High conviction trend structure
            weights["first_hour_verdict"] *= 1.5
        elif pcr and pcr < 0.8 and gap_pct < 0:
            weights["first_hour_verdict"] *= 1.5
        elif trend in ["bullish", "bearish"]:
            weights["first_hour_verdict"] *= 1.3

        # Max Pain Penalty: If spot is far from Max Pain
        if max_pain and max_pain.get("distance_pct"):
            dist = max_pain.get("distance_pct")
            pull = max_pain.get("pull_direction")
            # If Spot is > 1.0% away from Max Pain, gravity is incredibly strong. Soften trend breakouts.
            if abs(dist) > 1.0:
                weights["first_hour_verdict"] *= 0.5

        # 2. Gap Fill (Mean Reversion)
        # Block gap fills entirely if structural trend is powerfully against the gap
        # Or if the gap is too large to realistically fill (> 1.2%)
        abs_gap = abs(gap_pct)
        if abs_gap > 1.2:
            weights["gap_fill"] = 0.0  # Runaway gap, do not fade
        elif trend == "bullish" and gap_pct > 0:
            # Bullish trend + gap up = dangerous to short the gap fill
            weights["gap_fill"] *= 0.3
        elif trend == "bearish" and gap_pct < 0:
            weights["gap_fill"] *= 0.3
        else:
            # Reversion environments (Trend is flat, or countering the gap)
            weights["gap_fill"] *= 1.2

        # 3. Bollinger Band Squeeze (Volatility Expansion)
        # BB Squeeze thrives when VIX is historically low and about to expand.
        if vix is not None:
            if vix < 12.0:
                # Option premiums are cheap, breakout incoming
                weights["bb_squeeze"] *= 1.5
            elif vix > 20.0:
                # Extremely high volatility, squeezes are rare/dangerous
                weights["bb_squeeze"] = 0.0
        
        # If trend is strongly ranging, squeeze is building
        if trend == "ranging":
            weights["bb_squeeze"] *= 1.2

        # 4. VWAP Reversion
        # Operates best in neutral/ranging days. Dangerous in strong momentum.
        if trend in ["bullish", "bearish"]:
            weights["vwap_reversion"] = 0.0 # Strict disable, trends destroy VWAP reversions
        elif pcr:
            if 0.8 <= pcr <= 1.2:
                weights["vwap_reversion"] *= 1.5 # Neutral PCR supports mean reversion
            else:
                weights["vwap_reversion"] *= 0.5

        # Supercharge Mean Reversion if Max Pain is pulling the price back heavily
        if max_pain and max_pain.get("distance_pct", 0):
            if abs(max_pain.get("distance_pct")) > 1.0:
                weights["vwap_reversion"] = max(1.5, weights["vwap_reversion"] * 1.5)

        # 5. IV Expansion Ride — real IV data when available
        # Thrives in low-IV, high-momentum environments (buy cheap options before move)
        iv_edge = context.get("iv_edge", {})
        if iv_regime in ("low_iv",) or (atm_iv is not None and atm_iv < 0.15):
            # IV is historically cheap -> great time to buy options for expansion
            if trend in ("bullish", "bearish"):
                weights["iv_expansion_ride"] *= 1.5
        elif iv_regime == "extreme_iv" or (atm_iv is not None and atm_iv > 0.35):
            # IV is extremely expensive -> buying options is too costly
            weights["iv_expansion_ride"] = 0.0
        elif iv_edge.get("vrp_ratio", 1.0) > 1.2:
            weights["iv_expansion_ride"] = 0.0
        elif iv_edge.get("is_cheap", False):
            weights["iv_expansion_ride"] *= 1.3

        # Expiry pin risk: near expiry (DTE ≤ 1) options have violent gamma; be cautious
        if dte is not None and dte <= 1 and iv_regime not in ("low_iv",):
            weights["iv_expansion_ride"] *= 0.5

        # 6. OI Confirmed Breakout
        # Acts as secondary breakout confirmation; strengthened by real OI buildup data
        oi_flow = context.get("oi_flow", {})
        flow_sig = oi_flow.get("flow_signal", "NEUTRAL")
        buildup_direction = (oi_buildup or {}).get("direction", "NEUTRAL")
        if flow_sig != "NEUTRAL" or buildup_direction != "NEUTRAL":
            weights["oi_confirmed_breakout"] *= 1.3
        elif trend == "ranging":
            weights["oi_confirmed_breakout"] *= 0.5

        # 7. Delta Scalp — best near expiry with strong gamma
        greeks = context.get("greeks_momentum", {})
        if greeks.get("signal") == "GAMMA_SWEET_SPOT":
            weights["delta_scalp"] *= 1.5
        elif dte is not None and dte <= 2 and trend in ("bullish", "bearish"):
            # Near expiry + trending = gamma explosive, good for scalps
            weights["delta_scalp"] *= 1.3
        elif not greeks.get("is_favorable", True):
            weights["delta_scalp"] = 0.0

        # 8. OI Wall Bounce — best in ranging markets at strong OI support/resistance
        if trend == "ranging":
            weights["oi_wall_bounce"] *= 1.5
        elif trend in ("bullish", "bearish"):
            weights["oi_wall_bounce"] *= 0.3

        # OI Wall bonus: if real OI levels show a dominant wall near spot, amplify
        if oi_levels and oi_levels.get("nearest_resistance") and oi_levels.get("nearest_support"):
            weights["oi_wall_bounce"] = min(2.0, weights["oi_wall_bounce"] * 1.2)

        # Cap weights at 2.0 and floor at 0.0
        for k in weights:
            weights[k] = max(0.0, min(2.0, round(weights[k], 2)))

        logger.info(f"[Brain] Generated Weights: {weights}")
        return weights

    def generate_morning_thesis(self, context: Dict[str, Any], lookback_5d: pd.DataFrame) -> Dict[str, Any]:
        """
        Wraps contextual data, analyzes 5 days, and computes the active plan for the day.
        """
        trend_data = self.analyze_5_day_trend(lookback_5d)
        weights = self.generate_strategy_weights(context, lookback_5d)
        
        thesis = {
            "regime": trend_data["trend"],
            "momentum_strength": trend_data["consecutive_moves"],
            "recommended_weights": weights,
        }
        
        # Formulate human-readable plan for logging
        atm_iv = context.get("atm_iv")
        iv_regime = context.get("iv_regime", "normal_iv")
        dte = context.get("dte")
        pcr_val = context.get("pcr")
        if isinstance(pcr_val, dict):
            pcr_val = pcr_val.get("pcr")
        max_pain_dist = (context.get("max_pain") or {}).get("distance_pct")

        plan = f"Trend is currently {thesis['regime']}. "
        if pcr_val:
            plan += f"PCR={pcr_val:.2f} ({'bullish' if pcr_val > 1.0 else 'bearish'}). "
        if atm_iv:
            plan += f"ATM IV={atm_iv*100:.1f}% ({iv_regime}). "
        if dte:
            plan += f"DTE={dte:.0f}. "
        if max_pain_dist and abs(max_pain_dist) > 0.5:
            plan += f"MaxPain pull: {max_pain_dist:+.1f}%. "
        if weights.get("vwap_reversion", 0) == 0.0:
            plan += "VWAP Reversion disabled due to strong trend. "
        if weights.get("first_hour_verdict", 0) > 1.0:
            plan += "Favored: First Hour Continuation. "
        if weights.get("bb_squeeze", 0) > 1.0:
            plan += "VIX supports BB Squeeze breakout. "
        if weights.get("iv_expansion_ride", 0) > 1.0:
            plan += "IV cheap — prioritizing Expansion ride entries. "
        if weights.get("iv_expansion_ride", 0) == 0.0:
            plan += "IV too expensive — Expansion Ride blocked. "
        if weights.get("oi_wall_bounce", 0) > 1.0:
            plan += "Ranging market — prioritizing OI Wall bounces. "
            
        thesis["plan"] = plan.strip()
        
        return thesis
