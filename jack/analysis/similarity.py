"""
Similarity Search — find N most similar historical days by feature distance.

Uses the pending_analysis.json historical data to find days with similar
market conditions to today. This helps set realistic expectations and
informs the confluence scorer.

Features compared:
    - gap_pct
    - rsi
    - atr (normalized)
    - fh_return_pct
    - fh_direction
    - regime
    - day_of_week
    - vix (if available)

Usage:
    from analysis.similarity import SimilaritySearch
    search = SimilaritySearch()
    similar = search.find_similar(today_context, top_n=5)
"""

import os
import json
import logging
import math
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Path to pending analysis with all historical day data
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HISTORY_PATH = os.path.join(
    _HERE, "..", "brain", "knowledge", "pending_analysis.json"
)


class SimilaritySearch:
    """
    Find historically similar trading days using feature-based distance.
    """

    def __init__(self, history_path: str = None):
        """
        Args:
            history_path: Path to pending_analysis.json or similar historical data.
        """
        self.history_path = history_path or DEFAULT_HISTORY_PATH
        self._history = None
    
    def _load_history(self) -> list[dict]:
        """Load and cache historical day data."""
        if self._history is not None:
            return self._history
        
        if not os.path.exists(self.history_path):
            logger.warning(f"History file not found: {self.history_path}")
            return []
        
        try:
            with open(self.history_path, "r") as f:
                data = json.load(f)
            
            if isinstance(data, dict) and "days" in data:
                self._history = data["days"]
            elif isinstance(data, list):
                self._history = data
            else:
                self._history = []
            
            logger.info(f"Loaded {len(self._history)} historical days")
            return self._history
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            return []

    def find_similar(self, today: dict, top_n: int = 5,
                      min_data_quality: int = 3) -> list[dict]:
        """
        Find the N most similar historical days to today.
        
        Args:
            today: Dict with today's market context:
                - gap_pct: float
                - rsi: float
                - atr: float
                - fh_return_pct: float (if available)
                - fh_direction: int (-1, 0, 1)
                - regime: str
                - day_of_week: str
                - india_vix: float (optional)
            top_n: Number of similar days to return.
            min_data_quality: Minimum features that must be non-null.
            
        Returns:
            List of dicts, each with:
                - date, distance, all original day data
                - outcome (total_pnl from that day)
        """
        history = self._load_history()
        if not history:
            return []
        
        # Extract today's feature vector
        today_features = self._extract_features(today)
        
        # Compute distance to each historical day
        results = []
        for day in history:
            day_features = self._extract_features(day)
            
            # Skip days with too little data
            non_null = sum(1 for v in day_features.values() if v is not None)
            if non_null < min_data_quality:
                continue
            
            distance = self._compute_distance(today_features, day_features)
            
            if distance is not None:
                results.append({
                    "date": day.get("date", ""),
                    "distance": round(distance, 4),
                    "day_of_week": day.get("day_of_week", ""),
                    "gap_pct": day.get("gap_pct"),
                    "gap_type": day.get("gap_type", ""),
                    "regime": day.get("regime", ""),
                    "atr": day.get("atr"),
                    "rsi": day.get("rsi"),
                    "fh_return_pct": day.get("fh_return_pct"),
                    "fh_direction": day.get("fh_direction"),
                    "fh_strong": day.get("fh_strong"),
                    "total_pnl": day.get("total_pnl", 0),
                    "trades": day.get("trades", []),
                    "trade_count": len(day.get("trades", [])),
                    "india_vix": day.get("india_vix"),
                    "us_sentiment": day.get("us_sentiment"),
                })
        
        # Sort by distance (most similar first)
        results.sort(key=lambda x: x["distance"])
        
        return results[:top_n]

    def find_similar_with_outcome(self, today: dict, 
                                   top_n: int = 5) -> dict:
        """
        Find similar days and summarize their trading outcomes.
        
        Returns:
            Dict with:
                similar_days: list of similar day dicts
                bullish_count: number of bullish outcome days
                bearish_count: number of bearish outcome days
                avg_pnl: average P&L of similar days
                success_rate: % of similar days that were profitable
                recommended_direction: "LONG" / "SHORT" / "NEUTRAL"
        """
        similar = self.find_similar(today, top_n)
        
        if not similar:
            return {
                "similar_days": [],
                "bullish_count": 0,
                "bearish_count": 0,
                "avg_pnl": 0,
                "success_rate": 0,
                "recommended_direction": "NEUTRAL",
            }
        
        # Analyze outcomes
        bullish = 0
        bearish = 0
        total_pnl = 0
        profitable = 0
        
        for day in similar:
            pnl = day.get("total_pnl", 0)
            total_pnl += pnl
            
            if pnl > 0:
                profitable += 1
            
            # Determine if day was bullish/bearish overall
            fh_dir = day.get("fh_direction", 0)
            if fh_dir > 0:
                bullish += 1
            elif fh_dir < 0:
                bearish += 1
        
        n = len(similar)
        avg_pnl = total_pnl / n if n > 0 else 0
        success_rate = profitable / n * 100 if n > 0 else 0
        
        if bullish > bearish and bullish >= 3:
            recommended = "LONG"
        elif bearish > bullish and bearish >= 3:
            recommended = "SHORT"
        else:
            recommended = "NEUTRAL"
        
        return {
            "similar_days": similar,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": n - bullish - bearish,
            "avg_pnl": round(avg_pnl, 2),
            "total_pnl": round(total_pnl, 2),
            "success_rate": round(success_rate, 1),
            "profitable_count": profitable,
            "days_analyzed": n,
            "recommended_direction": recommended,
        }

    # =========================================================================
    # Feature Extraction and Distance
    # =========================================================================

    def _extract_features(self, day: dict) -> dict:
        """
        Extract a normalized feature vector from a day's data.
        
        Returns dict of feature_name -> normalized_value (or None).
        """
        gap = day.get("gap_pct")
        rsi = day.get("rsi")
        atr = day.get("atr")
        fh_ret = day.get("fh_return_pct")
        fh_dir = day.get("fh_direction", 0)
        vix = day.get("india_vix")
        
        # Normalize features to roughly [-1, 1] or [0, 1] range
        features = {
            "gap_pct": self._safe_normalize(gap, -3.0, 3.0),
            "rsi": self._safe_normalize(rsi, 0, 100),
            "atr_norm": self._safe_normalize(atr, 100, 800),  # BankNifty ATR range
            "fh_return": self._safe_normalize(fh_ret, -2.0, 2.0),
            "fh_direction": float(fh_dir) if fh_dir != 0 else None,
            "vix_norm": self._safe_normalize(vix, 8, 40),
        }
        
        # Categorical features encoded as numbers
        regime = day.get("regime", "")
        regime_map = {
            "trending_strong": 1.0,
            "trending_weak": 0.5,
            "normal": 0.0,
            "squeeze": -0.5,
            "choppy": -1.0,
        }
        features["regime_code"] = regime_map.get(regime)
        
        dow = day.get("day_of_week", "")
        dow_map = {
            "Monday": 0.0,
            "Tuesday": -0.3,
            "Wednesday": -0.1,
            "Thursday": 0.0,
            "Friday": 0.3,
        }
        features["dow_code"] = dow_map.get(dow)
        
        return features

    def _compute_distance(self, a: dict, b: dict) -> Optional[float]:
        """
        Compute weighted Euclidean distance between two feature vectors.
        
        Only compares features where both values are available.
        """
        # Feature weights for distance calculation
        weights = {
            "gap_pct": 1.5,
            "rsi": 1.0,
            "atr_norm": 1.0,
            "fh_return": 1.5,
            "fh_direction": 2.0,  # Strong weight on direction match
            "vix_norm": 0.8,
            "regime_code": 1.2,
            "dow_code": 0.5,
        }
        
        total_dist = 0.0
        total_weight = 0.0
        
        for key in weights:
            va = a.get(key)
            vb = b.get(key)
            
            if va is not None and vb is not None:
                w = weights[key]
                total_dist += w * (va - vb) ** 2
                total_weight += w
        
        if total_weight == 0:
            return None
        
        # Normalize by total weight
        return math.sqrt(total_dist / total_weight)

    def _safe_normalize(self, value, low: float, high: float) -> Optional[float]:
        """Normalize value to [0, 1] range, return None if invalid."""
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        
        try:
            v = float(value)
        except (ValueError, TypeError):
            return None
        
        if high == low:
            return 0.5
        
        return max(0, min(1, (v - low) / (high - low)))


if __name__ == "__main__":
    """Test similarity search with a sample day."""
    search = SimilaritySearch()
    
    today = {
        "gap_pct": -0.3,
        "rsi": 45,
        "atr": 350,
        "fh_return_pct": 0.5,
        "fh_direction": 1,
        "regime": "normal",
        "day_of_week": "Wednesday",
        "india_vix": 14,
    }
    
    result = search.find_similar_with_outcome(today, top_n=5)
    
    print(f"Found {result['days_analyzed']} similar days:")
    print(f"  Bullish: {result['bullish_count']}")
    print(f"  Bearish: {result['bearish_count']}")
    print(f"  Avg P&L: Rs{result['avg_pnl']:,.0f}")
    print(f"  Success Rate: {result['success_rate']:.0f}%")
    print(f"  Recommendation: {result['recommended_direction']}")
    
    print("\nTop similar days:")
    for day in result.get("similar_days", [])[:5]:
        print(f"  {day['date']} ({day['day_of_week']}): "
              f"gap={day.get('gap_pct', 'N/A')}, "
              f"fh={day.get('fh_return_pct', 'N/A')}, "
              f"pnl=Rs{day.get('total_pnl', 0):,.0f}, "
              f"dist={day['distance']:.3f}")
