"""
Regime Classifier (Composite) indicator.

Classifies the current market regime based on ATR, ADX, and Bollinger Band Width.
Requires ATR, ADX, and BB_Width columns to already exist in the DataFrame.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "regime",
    "display_name": "Regime Classifier",
    "params": {},
    "output_columns": ["Regime", "Regime_Score"],
    "timeframes": ["1d"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Classify market regime based on prerequisite indicators.

    Regimes:
    - "trending_strong": ADX > 30 AND ATR_Pct > 75th percentile (60-row window)
    - "trending_weak": ADX > 25 AND ATR_Pct > median
    - "ranging": ADX < 20 AND BB_Width < median
    - "squeeze": ADX < 20 AND BB_Width < 25th percentile
    - "volatile": ATR_Pct > 90th percentile regardless of ADX
    - "normal": everything else

    Regime_Score: 1-5 (5 = strong trend, 1 = tight range).

    Args:
        df: DataFrame that MUST have ATR_Pct, ADX, and BB_Width columns.

    Returns:
        Copy of DataFrame with Regime and Regime_Score columns.

    Raises:
        ValueError: If prerequisite indicator columns are missing.
    """
    df = df.copy()

    # Check prerequisites
    required = ["ATR_Pct", "ADX", "BB_Width"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            f"Regime classifier requires these columns to be pre-computed: {missing}. "
            f"Run the following indicators first: atr (for ATR_Pct), adx (for ADX), "
            f"bbands (for BB_Width)."
        )

    if len(df) == 0:
        df["Regime"] = pd.Series(dtype=str)
        df["Regime_Score"] = pd.Series(dtype=int)
        return df

    window = 60
    regimes = []
    scores = []

    for i in range(len(df)):
        # Get rolling window (up to last 60 rows)
        start_idx = max(0, i - window + 1)
        window_data = df.iloc[start_idx:i + 1]

        atr_pct = df.iloc[i]["ATR_Pct"]
        adx = df.iloc[i]["ADX"]
        bb_width = df.iloc[i]["BB_Width"]

        # Handle NaN values
        if pd.isna(atr_pct) or pd.isna(adx) or pd.isna(bb_width):
            regimes.append("normal")
            scores.append(3)
            continue

        # Compute percentiles from window
        atr_series = window_data["ATR_Pct"].dropna()
        bb_series = window_data["BB_Width"].dropna()

        if len(atr_series) < 5 or len(bb_series) < 5:
            regimes.append("normal")
            scores.append(3)
            continue

        atr_p75 = np.percentile(atr_series, 75)
        atr_p90 = np.percentile(atr_series, 90)
        atr_median = np.median(atr_series)
        bb_median = np.median(bb_series)
        bb_p25 = np.percentile(bb_series, 25)

        # Classification (check in priority order)
        if atr_pct > atr_p90:
            regimes.append("volatile")
            scores.append(4)
        elif adx > 30 and atr_pct > atr_p75:
            regimes.append("trending_strong")
            scores.append(5)
        elif adx > 25 and atr_pct > atr_median:
            regimes.append("trending_weak")
            scores.append(4)
        elif adx < 20 and bb_width < bb_p25:
            regimes.append("squeeze")
            scores.append(1)
        elif adx < 20 and bb_width < bb_median:
            regimes.append("ranging")
            scores.append(2)
        else:
            regimes.append("normal")
            scores.append(3)

    df["Regime"] = regimes
    df["Regime_Score"] = scores

    return df
