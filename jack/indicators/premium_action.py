"""
Option Premium Price Action Analysis.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)

METADATA = {
    "name": "premium_action",
    "display_name": "Option Premium Price Action",
    "params": {},
    "output_columns": [],
    "timeframes": ["5m", "15m"],
}

def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """Takes OPTION premium OHLC dataframe."""
    df = df.copy()
    if df.empty or 'Close' not in df.columns:
        return df
        
    # Standard indicators on the option premium itself
    # VWAP Proxy
    df['_TP'] = (df['High'] + df['Low'] + df['Close']) / 3
    if 'Volume' in df.columns:
        df['Premium_VWAP'] = (df['_TP'] * df['Volume']).cumsum() / df['Volume'].cumsum()
    else:
        df['Premium_VWAP'] = df['_TP'].expanding().mean()
        
    df.drop(columns=['_TP'], inplace=True, errors='ignore')
    return df

class PremiumActionAnalyzer:
    def analyze(self, opt_df: pd.DataFrame) -> dict:
        if opt_df is None or opt_df.empty or "Premium_VWAP" not in opt_df.columns:
            return {"signal": "NEUTRAL", "divergence": False}
            
        recent = opt_df.iloc[-1]
        price = recent.get("Close", 0)
        vwap = recent.get("Premium_VWAP", 0)
        
        signal = "NEUTRAL"
        if price > vwap * 1.05:
            signal = "PREMIUM_BREAKOUT"
        elif price < vwap * 0.95:
            signal = "PREMIUM_BREAKDOWN"
            
        return {
            "signal": signal,
            "premium_vwap": float(vwap),
            "divergence": False # Stub for real divergence calc against index
        }
