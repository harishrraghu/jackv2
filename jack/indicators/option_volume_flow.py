"""
Option Volume Flow Analysis — Delta-weighted volume flows.
"""

import logging
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)

METADATA = {
    "name": "option_volume_flow",
    "display_name": "Delta-Weighted Option Volume",
    "params": {},
    "output_columns": ["VolumeFlowSignal"],
    "timeframes": ["1d"],
}

def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    return df

class OptionVolumeAnalyzer:

    def analyze(self, chain: pd.DataFrame) -> dict:
        if chain is None or chain.empty:
            return {"vol_pcr": 1.0, "net_delta_vol": 0, "signal": "NEUTRAL"}
            
        required = ["ce_volume", "pe_volume", "ce_delta", "pe_delta"]
        if not all(col in chain.columns for col in required):
            return {"vol_pcr": 1.0, "net_delta_vol": 0, "signal": "NEUTRAL"}
            
        ce_vol = chain["ce_volume"].sum()
        pe_vol = chain["pe_volume"].sum()
        
        vol_pcr = pe_vol / ce_vol if ce_vol > 0 else 1.0
        
        net_delta_vol = (chain["ce_volume"] * chain["ce_delta"]).sum() + (chain["pe_volume"] * chain["pe_delta"]).sum()
        
        signal = "NEUTRAL"
        if vol_pcr > 1.3:
            signal = "VOLUME_PCR_BULLISH"
        elif vol_pcr < 0.7:
            signal = "VOLUME_PCR_BEARISH"
            
        if net_delta_vol > (ce_vol + pe_vol) * 0.1:
            signal = "VOLUME_DELTA_BULLISH"
        elif net_delta_vol < -(ce_vol + pe_vol) * 0.1:
            signal = "VOLUME_DELTA_BEARISH"

        # Find smart strike
        chain['ce_smart'] = chain['ce_volume'] * chain['ce_oi']
        chain['pe_smart'] = chain['pe_volume'] * chain['pe_oi']
        
        smart_ce_strike = chain.loc[chain['ce_smart'].idxmax()]['strike'] if not chain.empty and chain['ce_smart'].max() > 0 else 0
        smart_pe_strike = chain.loc[chain['pe_smart'].idxmax()]['strike'] if not chain.empty and chain['pe_smart'].max() > 0 else 0

        return {
            "vol_pcr": round(vol_pcr, 3),
            "net_delta_vol": int(net_delta_vol),
            "signal": signal,
            "smart_ce_strike": float(smart_ce_strike),
            "smart_pe_strike": float(smart_pe_strike)
        }
