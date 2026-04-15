"""
OI Flow Analysis — Real-time rate of change of Open Interest.
"""

import logging
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

METADATA = {
    "name": "oi_flow",
    "display_name": "OI Rate of Change Flow",
    "params": {},
    "output_columns": ["OIFlowSignal"],
    "timeframes": ["1d"],
}

def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """No-op for registry."""
    return df

class OIFlowAnalyzer:
    """Analyze OI ticks and flow."""

    def __init__(self):
        self.past_oi_snapshots = [] # Would hold time-series snapshots in live mode

    def analyze_flow(self, chain: pd.DataFrame, spot: float) -> dict:
        """
        Analyze current chain for OI flow signals based on change_oi columns.
        """
        if chain is None or chain.empty:
            return {"flow_signal": "NEUTRAL", "dealer_delta": 0}
            
        required = ["ce_change_oi", "pe_change_oi", "ce_delta", "pe_delta"]
        if not all(col in chain.columns for col in required):
            return {"flow_signal": "NEUTRAL", "dealer_delta": 0}
            
        ce_change = chain["ce_change_oi"].sum()
        pe_change = chain["pe_change_oi"].sum()
        
        # Estimate Dealer Delta Flow
        # If market buys Call, dealer is short call -> dealer has negative delta -> dealer buys stock to hedge
        # We assume positive OI change means customer buying and dealer selling mostly
        # Roughly: Net Delta Flow = Sum(Change_OI * Delta)
        
        chain['ce_delta_flow'] = chain["ce_change_oi"] * chain["ce_delta"]
        chain['pe_delta_flow'] = chain["pe_change_oi"] * chain["pe_delta"]
        
        dealer_delta_hedge_qty = chain['ce_delta_flow'].sum() + chain['pe_delta_flow'].sum()
        
        flow_signal = "NEUTRAL"
        if pe_change > ce_change * 1.5 and pe_change > 0:
            flow_signal = "OI_SURGE_PUT" # Support building
        elif ce_change > pe_change * 1.5 and ce_change > 0:
            flow_signal = "OI_SURGE_CALL" # Resistance building
            
        # Support crumbling
        if pe_change < 0 and ce_change > 0:
            flow_signal = "OI_UNWIND_PUTS"
        # Resistance crumbling
        elif ce_change < 0 and pe_change > 0:
            flow_signal = "OI_UNWIND_CALLS"

        return {
            "flow_signal": flow_signal,
            "dealer_delta_exposure": int(dealer_delta_hedge_qty),
            "ce_net_change": int(ce_change),
            "pe_net_change": int(pe_change)
        }
