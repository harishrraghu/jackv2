"""
Market Context Builder — combines ALL data sources into a single context dict.

This is the central data aggregator that feeds into:
- Confluence Scorer
- Entry Checklist
- Similarity Search
- Strategy Router
- The Brain (AI narration)

Sources:
    1. Dhan API (spot price, option chain, Greeks)
    2. Existing indicators (RSI, EMA, ATR, VWAP, etc.)
    3. OI Analysis (PCR, Max Pain, buildup)
    4. IV Analysis (IV rank, skew, regime)
    5. Event Calendar
    6. Global data (VIX, S&P500, crude)
    7. First Hour data (from existing indicator)

Usage:
    from brain.market_context import MarketContextBuilder
    builder = MarketContextBuilder()
    context = builder.build_context(date="2026-04-15", time="10:15")
"""

import os
import json
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)

# Base directory
_HERE = os.path.dirname(os.path.abspath(__file__))
CONTEXT_DIR = os.path.join(_HERE, "..", "data", "cache")


class MarketContextBuilder:
    """
    Aggregates all available data into a unified market context dict.
    
    Can work in two modes:
    1. Live mode: Fetches real-time data from Dhan API
    2. Backtest mode: Uses pre-computed indicators from simulation
    """

    def __init__(self, mode: str = "backtest"):
        """
        Args:
            mode: "live" for real-time Dhan data, "backtest" for pre-computed.
        """
        self.mode = mode
        self._event_calendar = None
        self._oi_analyzer = None
        self._iv_analyzer = None
        self._confluence_scorer = None

    @property
    def event_calendar(self):
        if self._event_calendar is None:
            from data.event_calendar import EventCalendar
            self._event_calendar = EventCalendar()
        return self._event_calendar

    @property
    def oi_analyzer(self):
        if self._oi_analyzer is None:
            from indicators.oi_analysis import OIAnalyzer
            self._oi_analyzer = OIAnalyzer()
        return self._oi_analyzer

    @property
    def iv_analyzer(self):
        if self._iv_analyzer is None:
            from indicators.iv_analysis import IVAnalyzer
            self._iv_analyzer = IVAnalyzer()
        return self._iv_analyzer

    @property
    def confluence_scorer(self):
        if self._confluence_scorer is None:
            from engine.confluence import ConfluenceScorer
            self._confluence_scorer = ConfluenceScorer()
        return self._confluence_scorer

    # =========================================================================
    # Backtest Mode — from pre-computed data
    # =========================================================================

    def build_from_backtest(self, 
                             date_val,
                             indicators: dict,
                             first_hour: dict = None,
                             global_context: dict = None,
                             filters: dict = None,
                             day_data: dict = None) -> dict:
        """
        Build market context from backtesting environment data.
        
        This is the primary interface during simulation/backtesting.
        
        Args:
            date_val: Trading date (str or datetime).
            indicators: Computed indicator values (RSI, EMA, ATR, etc.).
            first_hour: First hour verdict data.
            global_context: Global data (VIX, S&P, etc.).
            filters: Filter stack output.
            day_data: Raw candle data dict.
            
        Returns:
            Complete market context dict.
        """
        if isinstance(date_val, str):
            date_str = date_val
            day_name = datetime.strptime(date_val, "%Y-%m-%d").strftime("%A")
        elif hasattr(date_val, 'strftime'):
            date_str = date_val.strftime("%Y-%m-%d")
            day_name = date_val.strftime("%A")
        else:
            date_str = str(date_val)
            day_name = ""

        daily = indicators.get("daily", indicators)
        
        context = {
            # Identity
            "date": date_str,
            "day_of_week": filters.get("day_of_week", day_name) if filters else day_name,
            "current_time": "10:15",  # Default for backtest
            
            # Price & Indicators
            "spot": indicators.get("current_price", 0),
            "rsi": daily.get("RSI"),
            "ema_9": daily.get("EMA_9"),
            "ema_21": daily.get("EMA_21"),
            "atr": daily.get("ATR"),
            "atr_avg_60d": indicators.get("avg_ATR_60d"),
            "vwap": indicators.get("vwap"),
            "regime": daily.get("Regime", indicators.get("Regime", "normal")),
            
            # Gap
            "gap_pct": indicators.get("gap_pct", daily.get("Gap_Pct", 0)),
            "gap_type": indicators.get("gap_type", ""),
            
            # First Hour
            "first_hour": first_hour or {},
            "fh_return_pct": (first_hour or {}).get("FH_Return"),
            "fh_direction": (first_hour or {}).get("FH_Direction", 0),
            "fh_strong": (first_hour or {}).get("FH_Strong", False),
            
            # Global
            "india_vix": (global_context or {}).get("india_vix"),
            "vix": (global_context or {}).get("india_vix"),
            "sp500_chg": (global_context or {}).get("sp500_pct_chg"),
            "us_sentiment": (global_context or {}).get("us_sentiment"),
            "vix_regime": (global_context or {}).get("vix_regime"),
            
            # Event
            "event": self.event_calendar.get_event_for_date(date_str),
            "event_multiplier": self.event_calendar.get_impact_multiplier(date_str),
            
            # Capital state (filled by caller)
            "capital": 0,
            "daily_pnl": 0,
            
            # OI / IV data — populated from historical options parquet when available
            "pcr": indicators.get("pcr", {}),
            "max_pain": indicators.get("max_pain", {}),
            "oi_buildup": indicators.get("oi_buildup", {}),
            "oi_levels": indicators.get("oi_levels", {}),
            "iv_data": indicators.get("iv_data", {}),
            "atm_iv": indicators.get("atm_iv"),
            "iv_regime": indicators.get("iv_regime", "normal_iv"),
            "days_to_expiry": indicators.get("days_to_expiry"),
            "option_chain": indicators.get("option_chain"),
        }
        
        # Compute confluence score
        context["confluence"] = self.confluence_scorer.score(context)
        
        return context

    # =========================================================================
    # Live Mode — from Dhan API
    # =========================================================================

    def build_live(self, symbol: str = "BANKNIFTY",
                    indicators: dict = None,
                    capital: float = 1000000,
                    daily_pnl: float = 0) -> dict:
        """
        Build market context from live Dhan data.
        
        Fetches real-time:
        - Spot price
        - Option chain (OI, Greeks, IV)
        - Expiry data
        
        Combines with:
        - Event calendar
        - Computed OI analysis
        - IV analysis
        
        Args:
            symbol: Underlying symbol.
            indicators: Pre-computed indicators (if available from historical data).
            capital: Current trading capital.
            daily_pnl: Today's P&L so far.
            
        Returns:
            Complete market context dict.
        """
        from data.dhan_fetcher import DhanFetcher
        
        fetcher = DhanFetcher(symbol=symbol)
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        day_name = now.strftime("%A")
        
        # Fetch spot price
        spot = fetcher.get_spot_price()
        spot_ohlc = fetcher.get_spot_ohlc()
        
        # Fetch option chain
        expiry = fetcher.get_nearest_expiry()
        chain = None
        if expiry:
            chain = fetcher.get_option_chain_df(expiry=expiry)
        
        dte = fetcher.get_days_to_expiry(expiry) if expiry else 1.0
        
        # Compute OI analysis
        oi_result = {}
        if chain is not None and spot:
            oi_result = self.oi_analyzer.full_analysis(chain, spot)
        
        # Compute IV analysis
        iv_result = {}
        if chain is not None and spot:
            vix_val = None
            if indicators:
                vix_val = indicators.get("india_vix")
            iv_result = self.iv_analyzer.full_analysis(chain, spot, vix=vix_val)
        
        # Build indicator context (merge live and pre-computed)
        ind = indicators or {}
        
        context = {
            # Identity
            "date": date_str,
            "day_of_week": day_name,
            "current_time": current_time,
            "mode": "live",
            
            # Price
            "spot": spot,
            "spot_ohlc": spot_ohlc or {},
            
            # Indicators (from pre-computed or live)
            "rsi": ind.get("RSI"),
            "ema_9": ind.get("EMA_9"),
            "ema_21": ind.get("EMA_21"),
            "atr": ind.get("ATR"),
            "atr_avg_60d": ind.get("avg_ATR_60d"),
            "vwap": ind.get("vwap"),
            "regime": ind.get("Regime", "normal"),
            
            # Gap (from OHLC)
            "gap_pct": self._compute_gap(spot_ohlc, ind) if spot_ohlc else 0,
            
            # First Hour (if time > 10:15)
            "first_hour": ind.get("first_hour", {}),
            
            # Global
            "india_vix": ind.get("india_vix"),
            "vix": ind.get("india_vix"),
            "sp500_chg": ind.get("sp500_pct_chg"),
            "us_sentiment": ind.get("us_sentiment"),
            "vix_regime": ind.get("vix_regime"),
            
            # Event
            "event": self.event_calendar.get_event_for_date(date_str),
            "event_multiplier": self.event_calendar.get_impact_multiplier(date_str),
            
            # OI Data (live from chain)
            "pcr": oi_result.get("pcr_oi", {}),
            "max_pain": oi_result.get("max_pain", {}),
            "oi_buildup": oi_result.get("buildup", {}),
            "oi_levels": oi_result.get("oi_levels", {}),
            "oi_overall_signal": oi_result.get("overall_signal", "NEUTRAL"),
            "trap": oi_result.get("trap", {}),
            
            # IV Data (live from chain)
            "iv_data": iv_result,
            "atm_iv": iv_result.get("atm", {}).get("atm_iv"),
            "iv_regime": iv_result.get("iv_regime", {}).get("iv_regime", "normal_iv"),
            
            # Options
            "expiry": expiry,
            "days_to_expiry": dte,
            "option_chain": chain,  # Full DataFrame for strike selection
            
            # Capital
            "capital": capital,
            "daily_pnl": daily_pnl,
        }
        
        # Compute confluence score
        context["confluence"] = self.confluence_scorer.score(context)
        
        return context

    # =========================================================================
    # Helpers
    # =========================================================================

    def _compute_gap(self, ohlc: dict, indicators: dict) -> float:
        """Compute gap percentage from OHLC and previous close."""
        today_open = ohlc.get("open", 0) if ohlc else 0
        prev_close = indicators.get("prev_close", 0) 
        
        if prev_close and prev_close > 0 and today_open > 0:
            return round((today_open - prev_close) / prev_close * 100, 3)
        return 0.0

    def save_context(self, context: dict, filename: str = None) -> str:
        """
        Save market context to cache as JSON.
        
        Excludes non-serializable objects like DataFrames.
        """
        os.makedirs(CONTEXT_DIR, exist_ok=True)
        
        if filename is None:
            date_str = context.get("date", datetime.now().strftime("%Y-%m-%d"))
            time_str = context.get("current_time", "").replace(":", "")
            filename = f"market_context_{date_str}_{time_str}.json"
        
        filepath = os.path.join(CONTEXT_DIR, filename)
        
        # Filter out non-serializable values
        serializable = {}
        for k, v in context.items():
            if k == "option_chain":
                continue  # Skip DataFrame
            try:
                json.dumps(v, default=str)
                serializable[k] = v
            except (TypeError, ValueError):
                serializable[k] = str(v)
        
        with open(filepath, "w") as f:
            json.dump(serializable, f, indent=2, default=str)
        
        logger.info(f"Saved market context to {filepath}")
        return filepath

    def load_context(self, filepath: str) -> dict:
        """Load a saved market context."""
        with open(filepath, "r") as f:
            return json.load(f)
