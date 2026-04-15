"""
Confluence Scorer — the master signal aggregator.

Takes ALL available data points and produces a single direction + conviction score.
This replaces subjective "AI judgment" with a deterministic, weighted scoring system.

Factors considered:
    1. First Hour Verdict direction
    2. RSI position (overbought/oversold)
    3. EMA crossover trend
    4. Gap analysis
    5. PCR (Put-Call Ratio) signal
    6. Max Pain pull direction
    7. OI buildup classification
    8. VIX regime
    9. US market overnight sentiment
    10. Event calendar impact
    11. Day-of-week historical bias
    12. Regime classification (trending/ranging/squeeze)

Output: direction ("LONG" / "SHORT" / "NEUTRAL") + conviction (0.0 to 1.0)

Usage:
    from engine.confluence import ConfluenceScorer
    scorer = ConfluenceScorer()
    result = scorer.score(market_context)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Factor weights — how much each input contributes to the final score
# =============================================================================

DEFAULT_WEIGHTS = {
    "first_hour":         0.18,   # ↓ from 0.25 (still important but shared)
    "pcr":                0.08,   # ↓ from 0.12 (supplemented by oi_flow)
    "oi_buildup":         0.06,   # ↓ from 0.10 (supplemented by oi_flow)
    "max_pain":           0.06,   # ↓ from 0.08
    "rsi":                0.06,   # ↓ from 0.08
    "ema_trend":          0.06,   # ≈ same
    "gap":                0.05,   # ≈ same
    "vix_regime":         0.05,   # ≈ same
    "us_sentiment":       0.04,   # ≈ same
    "regime":             0.04,   # ≈ same
    "day_of_week":        0.03,   # ≈ same
    "event":              0.03,   # ≈ same
    # NEW factors
    "iv_edge":            0.10,   # ★ High weight — core options edge
    "oi_flow":            0.08,   # ★ Real-time institutional positioning
    "greeks_momentum":    0.05,   # Favorable Greek environment
    "option_volume_flow": 0.03,   # Volume-delta signal
}


class ConfluenceScorer:
    """
    Deterministic confluence scoring engine.
    
    Aggregates all available market signals into a single
    direction + conviction output.
    """

    def __init__(self, weights: dict = None):
        """
        Args:
            weights: Factor weight overrides. Must sum to ~1.0.
        """
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Weights sum to {total:.3f}, normalizing to 1.0")
            for k in self.weights:
                self.weights[k] /= total

    def score(self, context: dict) -> dict:
        """
        Compute confluence score from market context.
        
        Args:
            context: Dict with all available market signals. Keys:
                - first_hour: dict with FH_Direction, FH_Return, FH_Strong
                - pcr: dict from OI analyzer (pcr, signal)
                - oi_buildup: dict from OI analyzer (classification, signal)
                - max_pain: dict from OI analyzer (pull_direction)
                - rsi: float (daily RSI)
                - ema_9: float, ema_21: float
                - gap_pct: float
                - vix: float or vix_regime: str
                - us_sentiment: str
                - regime: str
                - day_of_week: str
                - event: dict from EventCalendar
                
        Returns:
            Dict with:
                direction: "LONG" / "SHORT" / "NEUTRAL"
                conviction: 0.0 to 1.0
                raw_score: -1.0 to +1.0 (negative = SHORT, positive = LONG)
                factor_scores: dict of individual factor contributions
                factors_used: list of factors that had data
                factors_missing: list of factors without data
        """
        factor_scores = {}
        factors_used = []
        factors_missing = []
        
        # --- Factor 1: First Hour Verdict ---
        score, used = self._score_first_hour(context)
        factor_scores["first_hour"] = score
        (factors_used if used else factors_missing).append("first_hour")
        
        # --- Factor 2: PCR ---
        score, used = self._score_pcr(context)
        factor_scores["pcr"] = score
        (factors_used if used else factors_missing).append("pcr")
        
        # --- Factor 3: OI Buildup ---
        score, used = self._score_oi_buildup(context)
        factor_scores["oi_buildup"] = score
        (factors_used if used else factors_missing).append("oi_buildup")
        
        # --- Factor 4: Max Pain ---
        score, used = self._score_max_pain(context)
        factor_scores["max_pain"] = score
        (factors_used if used else factors_missing).append("max_pain")
        
        # --- Factor 5: RSI ---
        score, used = self._score_rsi(context)
        factor_scores["rsi"] = score
        (factors_used if used else factors_missing).append("rsi")
        
        # --- Factor 6: EMA Trend ---
        score, used = self._score_ema_trend(context)
        factor_scores["ema_trend"] = score
        (factors_used if used else factors_missing).append("ema_trend")
        
        # --- Factor 7: Gap ---
        score, used = self._score_gap(context)
        factor_scores["gap"] = score
        (factors_used if used else factors_missing).append("gap")
        
        # --- Factor 8: VIX Regime ---
        score, used = self._score_vix(context)
        factor_scores["vix_regime"] = score
        (factors_used if used else factors_missing).append("vix_regime")
        
        # --- Factor 9: US Sentiment ---
        score, used = self._score_us_sentiment(context)
        factor_scores["us_sentiment"] = score
        (factors_used if used else factors_missing).append("us_sentiment")
        
        # --- Factor 10: Regime ---
        score, used = self._score_regime(context)
        factor_scores["regime"] = score
        (factors_used if used else factors_missing).append("regime")
        
        # --- Factor 11: Day of Week ---
        score, used = self._score_day_of_week(context)
        factor_scores["day_of_week"] = score
        (factors_used if used else factors_missing).append("day_of_week")
        
        # --- Factor 12: Event ---
        score, used = self._score_event(context)
        factor_scores["event"] = score
        (factors_used if used else factors_missing).append("event")

        # --- Factor 13: IV Edge ---
        score, used = self._score_iv_edge(context)
        factor_scores["iv_edge"] = score
        (factors_used if used else factors_missing).append("iv_edge")

        # --- Factor 14: OI Flow ---
        score, used = self._score_oi_flow(context)
        factor_scores["oi_flow"] = score
        (factors_used if used else factors_missing).append("oi_flow")

        # --- Factor 15: Greeks Momentum ---
        score, used = self._score_greeks_momentum(context)
        factor_scores["greeks_momentum"] = score
        (factors_used if used else factors_missing).append("greeks_momentum")

        # --- Factor 16: Option Volume Flow ---
        score, used = self._score_option_volume_flow(context)
        factor_scores["option_volume_flow"] = score
        (factors_used if used else factors_missing).append("option_volume_flow")
        
        # --- Weighted aggregation ---
        raw_score = 0.0
        active_weight_sum = 0.0
        
        for factor, value in factor_scores.items():
            if value is not None:
                weight = self.weights.get(factor, 0)
                raw_score += value * weight
                active_weight_sum += weight
        
        # Normalize by active weights (so missing factors don't dilute)
        if active_weight_sum > 0:
            raw_score = raw_score / active_weight_sum
        
        # Convert to direction + conviction
        if raw_score > 0.05:
            direction = "LONG"
        elif raw_score < -0.05:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"
        
        conviction = min(abs(raw_score), 1.0)
        
        # Classify conviction level
        if conviction >= 0.6:
            conviction_level = "HIGH"
        elif conviction >= 0.35:
            conviction_level = "MEDIUM"
        elif conviction >= 0.15:
            conviction_level = "LOW"
        else:
            conviction_level = "NONE"
        
        return {
            "direction": direction,
            "conviction": round(conviction, 3),
            "conviction_level": conviction_level,
            "raw_score": round(raw_score, 4),
            "factor_scores": {k: round(v, 3) if v is not None else None 
                              for k, v in factor_scores.items()},
            "factors_used": factors_used,
            "factors_missing": factors_missing,
            "factors_available": len(factors_used),
            "factors_total": len(factor_scores),
        }

    # =========================================================================
    # Individual Factor Scoring (-1.0 to +1.0)
    # Positive = bullish, Negative = bearish, None = no data
    # =========================================================================

    def _score_first_hour(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score first hour verdict."""
        fh = ctx.get("first_hour", {})
        if isinstance(fh, dict):
            fh_dir = fh.get("FH_Direction", fh.get("fh_direction", 0))
            fh_return = fh.get("FH_Return", fh.get("fh_return", 0))
            fh_strong = fh.get("FH_Strong", fh.get("fh_strong", False))
        else:
            return None, False
        
        if fh_dir == 0 or not fh_return:
            return None, False
        
        # Strong first hour is a powerful signal
        if fh_strong or (isinstance(fh_strong, str) and fh_strong == "True"):
            magnitude = min(abs(fh_return) / 1.0, 1.0)  # Scale: 1% move = full conviction
            return fh_dir * magnitude, True
        else:
            # Weak first hour: reduced signal
            magnitude = min(abs(fh_return) / 1.0, 0.5)
            return fh_dir * magnitude * 0.5, True

    def _score_pcr(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score PCR."""
        pcr_data = ctx.get("pcr", {})
        if isinstance(pcr_data, dict):
            pcr = pcr_data.get("pcr")
        elif isinstance(pcr_data, (int, float)):
            pcr = pcr_data
        else:
            return None, False
        
        if pcr is None:
            return None, False
        
        # PCR > 1.2 = bullish (put selling = support)
        # PCR < 0.8 = bearish (call selling = resistance)
        if pcr > 1.5:
            return 0.8, True
        elif pcr > 1.2:
            return 0.5, True
        elif pcr > 0.8:
            return 0.0, True
        elif pcr > 0.5:
            return -0.5, True
        else:
            return -0.8, True

    def _score_oi_buildup(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score OI buildup classification."""
        buildup = ctx.get("oi_buildup", ctx.get("buildup", {}))
        if not isinstance(buildup, dict):
            return None, False
        
        classification = buildup.get("classification", "")
        confidence = buildup.get("confidence", 0.5)
        
        mapping = {
            "long_buildup": 0.8,
            "short_buildup": -0.8,
            "mixed_bullish": 0.3,
            "mixed_bearish": -0.3,
            "unwinding": 0.0,
            "short_covering": 0.4,   # Mildly bullish (shorts closing)
            "long_unwinding": -0.4,  # Mildly bearish (longs closing)
        }
        
        base = mapping.get(classification, 0.0)
        if base == 0.0 and classification not in mapping:
            return None, False
        
        return base * confidence, True

    def _score_max_pain(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score max pain pull direction."""
        max_pain_data = ctx.get("max_pain", {})
        if not isinstance(max_pain_data, dict):
            return None, False
        
        pull = max_pain_data.get("pull_direction")
        distance_pct = abs(max_pain_data.get("distance_pct", 0))
        
        if pull is None:
            return None, False
        
        # Max pain pull is strongest on expiry day and when close to max pain
        magnitude = min(distance_pct / 1.0, 1.0) * 0.5  # Cap at 0.5
        
        if pull == "UP":
            return magnitude, True
        elif pull == "DOWN":
            return -magnitude, True
        else:
            return 0.0, True

    def _score_rsi(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score RSI."""
        rsi = ctx.get("rsi")
        if rsi is None:
            return None, False
        
        # RSI > 70 = overbought -> bearish signal
        # RSI < 30 = oversold -> bullish signal
        # Center at 50 = neutral
        if rsi > 80:
            return -0.8, True
        elif rsi > 70:
            return -0.4, True
        elif rsi > 55:
            return 0.1, True  # Mild bullish momentum
        elif rsi > 45:
            return 0.0, True  # Neutral
        elif rsi > 30:
            return -0.1, True  # Mild bearish momentum  
        elif rsi > 20:
            return 0.4, True   # Oversold bounce
        else:
            return 0.8, True   # Deep oversold bounce

    def _score_ema_trend(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score EMA crossover trend."""
        ema_9 = ctx.get("ema_9", ctx.get("EMA_9"))
        ema_21 = ctx.get("ema_21", ctx.get("EMA_21"))
        
        if ema_9 is None or ema_21 is None:
            return None, False
        
        if ema_21 == 0:
            return None, False
        
        spread_pct = (ema_9 - ema_21) / ema_21 * 100
        
        if spread_pct > 0.5:
            return 0.7, True   # Strong uptrend
        elif spread_pct > 0.1:
            return 0.3, True   # Mild uptrend
        elif spread_pct > -0.1:
            return 0.0, True   # Flat
        elif spread_pct > -0.5:
            return -0.3, True  # Mild downtrend
        else:
            return -0.7, True  # Strong downtrend

    def _score_gap(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score gap direction."""
        gap_pct = ctx.get("gap_pct")
        if gap_pct is None:
            return None, False
        
        # Moderate gaps tend to fill; extreme gaps tend to continue
        if abs(gap_pct) < 0.2:
            return 0.0, True  # No significant gap
        elif gap_pct > 0.75:
            return 0.3, True  # Large gap up — momentum
        elif gap_pct > 0.2:
            return -0.2, True  # Moderate gap up — mean reversion
        elif gap_pct < -0.75:
            return -0.3, True  # Large gap down — momentum
        elif gap_pct < -0.2:
            return 0.2, True  # Moderate gap down — mean reversion
        
        return 0.0, True

    def _score_vix(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score VIX regime."""
        vix = ctx.get("vix", ctx.get("india_vix"))
        vix_regime = ctx.get("vix_regime")
        
        if vix is not None:
            if vix > 25:
                return -0.3, True  # High fear — cautious
            elif vix > 18:
                return -0.1, True  # Elevated
            elif vix < 12:
                return 0.2, True   # Complacent — breakout possible
            else:
                return 0.0, True   # Normal
        
        if vix_regime:
            mapping = {
                "high_fear": -0.3,
                "complacent": 0.2,
                "normal": 0.0,
            }
            return mapping.get(vix_regime, 0.0), True
        
        return None, False

    def _score_us_sentiment(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score US overnight sentiment."""
        sentiment = ctx.get("us_sentiment")
        sp500_chg = ctx.get("sp500_chg", ctx.get("sp500_pct_chg"))
        
        if sp500_chg is not None:
            # S&P 500 overnight change as direct signal
            capped = max(min(sp500_chg / 2.0, 1.0), -1.0)
            return capped * 0.5, True
        
        if sentiment:
            mapping = {"bullish": 0.5, "bearish": -0.5, "neutral": 0.0}
            return mapping.get(sentiment, 0.0), True
        
        return None, False

    def _score_regime(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score market regime."""
        regime = ctx.get("regime")
        if not regime:
            return None, False
        
        mapping = {
            "trending_strong": 0.3,  # Trend continuation likely
            "trending_weak": 0.1,
            "normal": 0.0,
            "squeeze": 0.0,  # Neutral — direction unknown
            "choppy": -0.2,  # Avoid
        }
        
        return mapping.get(regime, 0.0), True

    def _score_day_of_week(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score day-of-week bias."""
        day = ctx.get("day_of_week")
        if not day:
            return None, False
        
        # Based on BankNifty historical analysis
        mapping = {
            "Monday": 0.0,
            "Tuesday": -0.3,   # Historically bearish
            "Wednesday": -0.1,
            "Thursday": 0.0,
            "Friday": 0.3,     # Historically bullish
        }
        
        return mapping.get(day, 0.0), True

    def _score_event(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score event calendar."""
        event = ctx.get("event", {})
        if not isinstance(event, dict):
            return None, False
        
        impact = event.get("impact", 1)
        bias = event.get("bias", "neutral")
        
        if impact <= 1:
            return 0.0, True
        
        # High-impact events -> reduce conviction (go neutral)
        if impact >= 4:
            return 0.0, True
        
        # Event bias
        if bias == "bullish":
            return 0.3, True
        elif bias == "bearish":
            return -0.3, True
        
        return 0.0, True

    def _score_iv_edge(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score IV Edge."""
        iv_edge = ctx.get("iv_edge", {})
        if not iv_edge: return None, False
        
        sig = iv_edge.get("vrp_signal", "NEUTRAL")
        if sig == "IV_CHEAP": return 0.5, True
        if sig == "IV_EXPENSIVE": return -0.5, True
        return 0.0, True

    def _score_oi_flow(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score OI Flow."""
        oi_flow = ctx.get("oi_flow", {})
        if not oi_flow: return None, False
        
        sig = oi_flow.get("flow_signal", "NEUTRAL")
        if sig in ["OI_SURGE_PUT", "OI_UNWIND_CALLS"]: return 0.6, True
        if sig in ["OI_SURGE_CALL", "OI_UNWIND_PUTS"]: return -0.6, True
        return 0.0, True

    def _score_greeks_momentum(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score Greeks Momentum."""
        greeks = ctx.get("greeks_momentum", {})
        if not greeks: return None, False
        
        sig = greeks.get("signal", "NEUTRAL")
        if sig == "GAMMA_SWEET_SPOT": return 0.4, True
        return 0.0, True

    def _score_option_volume_flow(self, ctx: dict) -> tuple[Optional[float], bool]:
        """Score Option Volume Flow."""
        vol = ctx.get("option_volume_flow", {})
        if not vol: return None, False
        
        sig = vol.get("signal", "NEUTRAL")
        if sig in ["VOLUME_PCR_BULLISH", "VOLUME_DELTA_BULLISH"]: return 0.3, True
        if sig in ["VOLUME_PCR_BEARISH", "VOLUME_DELTA_BEARISH"]: return -0.3, True
        return 0.0, True
