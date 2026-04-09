"""
Pre-trade filter stack.

A set of filters that run every morning before strategies are evaluated.
Each filter returns a multiplier (0.0 to 1.0) applied to strategy scores.
Combined multiplier < 0.3 blocks the trade entirely.
"""

import pandas as pd
import numpy as np


def day_of_week_filter(date: pd.Timestamp) -> dict:
    """
    Day-of-week bias filter based on statistical findings.

    Tuesday is the strongest bearish day (37.5% win rate).
    Friday is the only bullish day (53.1% win rate).

    Returns:
        Dict with name, day, long_multiplier, short_multiplier.
    """
    day_name = date.day_name()

    multipliers = {
        "Monday":    {"long": 1.0, "short": 1.0},
        "Tuesday":   {"long": 0.6, "short": 1.3},
        "Wednesday": {"long": 0.7, "short": 1.2},
        "Thursday":  {"long": 0.9, "short": 1.1},
        "Friday":    {"long": 1.3, "short": 0.7},
    }

    m = multipliers.get(day_name, {"long": 1.0, "short": 1.0})

    return {
        "name": "day_of_week",
        "day": day_name,
        "long_multiplier": m["long"],
        "short_multiplier": m["short"],
    }


def rsi_extreme_filter(daily_rsi: float, hourly_rsi: float) -> dict:
    """
    RSI extreme filter — discourages trades against RSI extremes.

    Daily RSI > 75 AND Hourly RSI > 70: discourage longs
    Daily RSI < 25 AND Hourly RSI < 30: discourage shorts

    Returns:
        Dict with multipliers.
    """
    if daily_rsi is None or hourly_rsi is None:
        return {
            "name": "rsi_extreme",
            "daily_rsi": daily_rsi,
            "hourly_rsi": hourly_rsi,
            "long_multiplier": 1.0,
            "short_multiplier": 1.0,
        }

    if daily_rsi > 75 and hourly_rsi > 70:
        long_mult = 0.5
        short_mult = 1.3
    elif daily_rsi < 25 and hourly_rsi < 30:
        long_mult = 1.3
        short_mult = 0.5
    else:
        long_mult = 1.0
        short_mult = 1.0

    return {
        "name": "rsi_extreme",
        "daily_rsi": daily_rsi,
        "hourly_rsi": hourly_rsi,
        "long_multiplier": long_mult,
        "short_multiplier": short_mult,
    }


def volatility_filter(current_atr: float, avg_atr_60d: float) -> dict:
    """
    Volatility regime filter.

    atr_ratio < 0.7 → "contracting", smaller positions
    atr_ratio > 1.3 → "expanding", wider stops eat risk budget
    else → "normal"

    Returns:
        Dict with regime classification and multiplier.
    """
    if avg_atr_60d is None or avg_atr_60d <= 0 or current_atr is None:
        return {
            "name": "volatility",
            "atr_ratio": 1.0,
            "regime": "normal",
            "multiplier": 1.0,
        }

    atr_ratio = current_atr / avg_atr_60d

    if atr_ratio < 0.7:
        regime = "contracting"
        multiplier = 0.8
    elif atr_ratio > 1.3:
        regime = "expanding"
        multiplier = 0.9
    else:
        regime = "normal"
        multiplier = 1.0

    return {
        "name": "volatility",
        "atr_ratio": round(atr_ratio, 3),
        "regime": regime,
        "multiplier": multiplier,
    }


def streak_filter(bull_streak: int, bear_streak: int) -> dict:
    """
    Streak filter — encourages mean reversion after extended streaks.

    3+ bull streak: discourage longs, encourage shorts
    3+ bear streak: encourage longs, discourage shorts

    Returns:
        Dict with multipliers.
    """
    if bull_streak >= 3:
        return {
            "name": "streak",
            "bull_streak": bull_streak,
            "bear_streak": bear_streak,
            "long_multiplier": 0.4,
            "short_multiplier": 1.3,
        }
    elif bear_streak >= 3:
        return {
            "name": "streak",
            "bull_streak": bull_streak,
            "bear_streak": bear_streak,
            "long_multiplier": 1.2,
            "short_multiplier": 0.5,
        }
    else:
        return {
            "name": "streak",
            "bull_streak": bull_streak,
            "bear_streak": bear_streak,
            "long_multiplier": 1.0,
            "short_multiplier": 1.0,
        }


def expiry_filter(date: pd.Timestamp) -> dict:
    """
    Expiry day filter — reduce size on expiry days.

    Wednesday or Thursday: multiplier=0.8 (Bank Nifty weekly expiry)
    Otherwise: multiplier=1.0

    Returns:
        Dict with is_expiry flag and multiplier.
    """
    day_name = date.day_name()
    is_expiry = day_name in ("Wednesday", "Thursday")

    return {
        "name": "expiry",
        "is_expiry": is_expiry,
        "multiplier": 0.8 if is_expiry else 1.0,
    }


def run_filter_stack(
    date: pd.Timestamp,
    lookback_daily: dict,
    indicators: dict,
) -> dict:
    """
    Run all 5 filters and return combined result.

    Args:
        date: Current trading date.
        lookback_daily: Dict with lookback daily indicator values.
        indicators: Dict with current indicator values.

    Returns:
        Combined dict with all filter results and combined multipliers.
    """
    # Extract needed values
    daily_rsi = indicators.get("RSI", None)
    hourly_rsi = indicators.get("hourly_RSI", None)
    current_atr = indicators.get("ATR", None)
    avg_atr_60d = lookback_daily.get("avg_ATR_60d", None)
    bull_streak = lookback_daily.get("Bull_Streak", 0)
    bear_streak = lookback_daily.get("Bear_Streak", 0)

    # Run all filters
    dow = day_of_week_filter(date)
    rsi = rsi_extreme_filter(daily_rsi, hourly_rsi)
    vol = volatility_filter(current_atr, avg_atr_60d)
    streak = streak_filter(bull_streak, bear_streak)
    expiry = expiry_filter(date)

    # Compute combined multipliers
    combined_long = (
        dow["long_multiplier"]
        * rsi["long_multiplier"]
        * vol["multiplier"]
        * streak["long_multiplier"]
        * expiry["multiplier"]
    )

    combined_short = (
        dow["short_multiplier"]
        * rsi["short_multiplier"]
        * vol["multiplier"]
        * streak["short_multiplier"]
        * expiry["multiplier"]
    )

    # Trade blocked if combined multiplier too low
    trade_blocked = combined_long < 0.3 and combined_short < 0.3

    return {
        "day_of_week": dow["day"],
        "filters": {
            "day_of_week": dow,
            "rsi_extreme": rsi,
            "volatility": vol,
            "streak": streak,
            "expiry": expiry,
        },
        "combined_long_multiplier": round(combined_long, 4),
        "combined_short_multiplier": round(combined_short, 4),
        "trade_blocked": trade_blocked,
        # Convenience fields
        "daily_rsi": daily_rsi,
        "bull_streak": bull_streak,
        "bear_streak": bear_streak,
        "regime": indicators.get("Regime", "normal"),
    }
