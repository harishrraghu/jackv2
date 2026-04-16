"""
Strategy backtester for Jack v3.

Runs a single strategy against historical 5-minute candle data
to measure effectiveness: win rate, avg P&L, Sharpe, max drawdown.

Used by:
  - lab/ranker.py (nightly rankings)
  - scripts/run_backtest.py (manual testing)
  - lab/discoverer.py (validating proposed strategies)
"""
import math
from typing import Optional

import pandas as pd
import numpy as np


def backtest_strategy(
    strategy_name: str,
    candle_data: pd.DataFrame,
    daily_data: pd.DataFrame,
    config: dict,
    params_override: dict = None,
) -> dict:
    """
    Backtest a single strategy against historical data.

    Args:
        strategy_name: Name matching a file in strategies/ (e.g., "first_hour_verdict").
        candle_data: 5-minute intraday candles. Columns: datetime, open, high, low, close, volume.
        daily_data: Daily candles for indicator computation. Columns: date, open, high, low, close, volume.
        config: Full settings.yaml config dict.
        params_override: Optional dict to override strategy parameters.

    Returns:
        {
          "strategy": str,
          "win_rate": float,            # % of trades that were profitable
          "total_trades": int,
          "avg_pnl": float,             # Average net P&L per trade in rupees
          "total_pnl": float,
          "max_drawdown_pct": float,    # Maximum peak-to-trough drawdown
          "sharpe": float,              # Simplified Sharpe (daily P&L / std)
          "trades_log": list[dict],     # Full trade log
          "lookback_days": int,
        }
    """
    from indicators.registry import IndicatorRegistry
    from engine.risk import RiskManager

    # Load strategy
    strategy = _load_strategy(strategy_name, params_override)
    if strategy is None:
        return {"strategy": strategy_name, "error": "Strategy not found", "total_trades": 0}

    indicator_registry = IndicatorRegistry("indicators/")
    risk = RiskManager(config={
        **config.get("trading", {}),
        "lot_size": config.get("market", {}).get("lot_size", 15),
    })

    # Group candles by date
    candle_data = candle_data.copy()
    if "datetime" in candle_data.columns:
        candle_data["datetime"] = pd.to_datetime(candle_data["datetime"])
        candle_data["date"] = candle_data["datetime"].dt.date
    elif "Datetime" in candle_data.columns:
        candle_data["Datetime"] = pd.to_datetime(candle_data["Datetime"])
        candle_data["date"] = candle_data["Datetime"].dt.date

    trade_log = []
    daily_pnls = []

    trading_dates = sorted(candle_data["date"].unique())
    lookback_days = config.get("lab", {}).get("backtest_lookback_days", 20)
    trading_dates = trading_dates[-lookback_days:]

    for trade_date in trading_dates:
        risk.reset_daily()
        day_candles = candle_data[candle_data["date"] == trade_date].copy()

        if len(day_candles) < 5:
            continue

        # Compute indicators on day's candles
        try:
            df_std = _standardize_columns(day_candles)
            df_with_ind = indicator_registry.compute_all(
                df_std,
                ["ema", "rsi", "atr", "vwap", "bbands", "adx"],
                params_override={"ema": {"period": 20}, "rsi": {"period": 14}, "atr": {"period": 14}},
            )
        except Exception:
            df_with_ind = day_candles

        # Compute daily indicators for context
        daily_indicators = _compute_daily_indicators(daily_data, trade_date, indicator_registry)

        day_data_context = {
            "date": str(trade_date),
            "daily": daily_indicators,
            "open_price": float(day_candles.iloc[0].get("open", day_candles.iloc[0].get("Open", 0))),
        }

        filters = {"combined_long_multiplier": 1.0, "combined_short_multiplier": 1.0}

        # Walk through 5-min candles
        open_position = None
        for i, row in df_with_ind.iterrows():
            time_str = _extract_time(row)
            current_price = float(row.get("close", row.get("Close", 0)))

            # Check exit if position open
            if open_position is not None:
                from strategies.base import ExitSignal
                exit_signal = strategy.check_exit(open_position, day_data_context, time_str, current_price)
                if exit_signal.should_exit:
                    result = _close_trade(open_position, exit_signal.exit_price, exit_signal.reason, time_str, risk)
                    trade_log.append(result)
                    open_position = None
                    continue

                # Hard stop / target check
                sl = open_position["stop_loss"]
                tgt = open_position["target"]
                direction = open_position["direction"]
                low = float(row.get("low", row.get("Low", current_price)))
                high = float(row.get("high", row.get("High", current_price)))

                if direction == "LONG":
                    if low <= sl:
                        result = _close_trade(open_position, sl, "stop_hit", time_str, risk)
                        trade_log.append(result)
                        open_position = None
                        continue
                    if high >= tgt:
                        result = _close_trade(open_position, tgt, "target_hit", time_str, risk)
                        trade_log.append(result)
                        open_position = None
                        continue
                else:
                    if high >= sl:
                        result = _close_trade(open_position, sl, "stop_hit", time_str, risk)
                        trade_log.append(result)
                        open_position = None
                        continue
                    if low <= tgt:
                        result = _close_trade(open_position, tgt, "target_hit", time_str, risk)
                        trade_log.append(result)
                        open_position = None
                        continue

            # Try entry if no position
            if open_position is None and risk.can_trade()[0]:
                indicators_dict = row.to_dict() if hasattr(row, "to_dict") else {}
                try:
                    signal = strategy.check_entry(
                        day_data=day_data_context,
                        lookback={},
                        indicators=indicators_dict,
                        current_time=time_str,
                        filters=filters,
                    )
                    if signal is not None:
                        qty = risk.calculate_position_size(signal.entry_price, signal.stop_loss)
                        if qty > 0:
                            open_position = {
                                "strategy": strategy_name,
                                "direction": signal.direction,
                                "entry_price": signal.entry_price,
                                "stop_loss": signal.stop_loss,
                                "target": signal.target,
                                "quantity": qty,
                                "entry_time": time_str,
                                "entry_date": str(trade_date),
                            }
                except Exception:
                    pass

        # Force close at end of day
        if open_position is not None:
            close_price = float(df_with_ind.iloc[-1].get("close", df_with_ind.iloc[-1].get("Close", 0)))
            result = _close_trade(open_position, close_price, "time_exit", "15:15", risk)
            trade_log.append(result)

        daily_pnls.append(risk.daily_pnl)

    # Aggregate stats
    if not trade_log:
        return {
            "strategy": strategy_name,
            "win_rate": 0.0,
            "total_trades": 0,
            "avg_pnl": 0.0,
            "total_pnl": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "trades_log": [],
            "lookback_days": lookback_days,
        }

    winning_trades = [t for t in trade_log if t.get("net_pnl", 0) > 0]
    pnls = [t.get("net_pnl", 0) for t in trade_log]
    total_pnl = sum(pnls)
    win_rate = len(winning_trades) / len(trade_log) * 100

    # Sharpe (simplified: mean daily P&L / std daily P&L * sqrt(252))
    if len(daily_pnls) > 1 and np.std(daily_pnls) > 0:
        sharpe = (np.mean(daily_pnls) / np.std(daily_pnls)) * math.sqrt(252)
    else:
        sharpe = 0.0

    # Max drawdown
    max_dd = _compute_max_drawdown(daily_pnls, config.get("trading", {}).get("initial_capital", 1000000))

    return {
        "strategy": strategy_name,
        "win_rate": round(win_rate, 2),
        "total_trades": len(trade_log),
        "avg_pnl": round(total_pnl / len(trade_log), 2),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown_pct": round(max_dd, 4),
        "sharpe": round(sharpe, 3),
        "trades_log": trade_log,
        "lookback_days": lookback_days,
    }


# ─────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────

def _load_strategy(strategy_name: str, params_override: dict = None):
    """Dynamically load a strategy by name."""
    strategy_map = {
        "first_hour_verdict": ("strategies.first_hour_verdict", "FirstHourVerdict"),
        "gap_fill": ("strategies.gap_fill", "GapFill"),
        "gap_up_fade": ("strategies.gap_up_fade", "GapUpFade"),
        "streak_fade": ("strategies.streak_fade", "StreakFade"),
        "bb_squeeze": ("strategies.bb_squeeze", "BBSqueezeBreakout"),
        "vwap_reversion": ("strategies.vwap_reversion", "VWAPReversion"),
        "theta_harvest": ("strategies.theta_harvest", "ThetaHarvest"),
        "afternoon_breakout": ("strategies.afternoon_breakout", "AfternoonBreakout"),
    }

    if strategy_name not in strategy_map:
        print(f"[Backtester] Unknown strategy: {strategy_name}")
        return None

    module_path, class_name = strategy_map[strategy_name]
    try:
        import importlib
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        params = params_override or {}
        return cls(params)
    except Exception as e:
        print(f"[Backtester] Failed to load {strategy_name}: {e}")
        return None


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to lowercase."""
    rename = {
        "Datetime": "date", "Date": "date", "datetime": "date",
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
    }
    return df.rename(columns={k: v for k, v in rename.items() if k in df.columns})


def _extract_time(row) -> str:
    """Extract HH:MM time string from a candle row."""
    for key in ("datetime", "Datetime", "date", "Date"):
        val = row.get(key)
        if val is not None:
            try:
                return pd.Timestamp(val).strftime("%H:%M")
            except Exception:
                pass
    return "09:15"


def _compute_daily_indicators(daily_data: pd.DataFrame, target_date, registry) -> dict:
    """Compute daily indicators up to target_date."""
    try:
        if daily_data is None or len(daily_data) == 0:
            return {}
        df = daily_data[daily_data.index <= str(target_date)].tail(30)
        if len(df) < 5:
            return {}
        df_std = _standardize_columns(df.reset_index() if df.index.name else df)
        result = registry.compute_all(df_std, ["ema", "rsi", "atr", "adx"])
        return result.iloc[-1].to_dict()
    except Exception:
        return {}


def _close_trade(position: dict, exit_price: float, reason: str, time_str: str, risk) -> dict:
    """Close a position and compute P&L via the risk manager."""
    from strategies.base import ExitSignal

    # Sync position to risk manager — execute_entry() was not called, so we set it directly.
    # This ensures execute_exit() can read position details and update peak_capital correctly.
    risk.open_position = {
        "strategy": position.get("strategy", "unknown"),
        "direction": position.get("direction", "LONG"),
        "entry_price": position.get("entry_price", exit_price),
        "original_entry": position.get("entry_price", exit_price),
        "stop_loss": position.get("stop_loss", 0),
        "target": position.get("target", 0),
        "quantity": position.get("quantity", 0),
        "entry_time": position.get("entry_time"),
        "entry_date": position.get("entry_date"),
        "confidence": 0.5,
        "reason": "",
        "metadata": {},
    }

    exit_sig = ExitSignal(should_exit=True, exit_price=exit_price, reason=reason)
    result = risk.execute_exit(exit_sig, exit_price)

    if "error" in result:
        # Fallback: compute P&L manually if risk manager fails
        direction = position.get("direction", "LONG")
        qty = position.get("quantity", 0)
        entry = position.get("entry_price", exit_price)
        if direction == "LONG":
            gross = (exit_price - entry) * qty
        else:
            gross = (entry - exit_price) * qty
        costs = risk.calculate_costs(entry, exit_price, qty, direction)
        net = gross - costs["total_costs"]
        risk.current_capital += net
        risk.daily_pnl += net
        result = {
            **position,
            "exit_price": exit_price,
            "exit_reason": reason,
            "gross_pnl": round(gross, 2),
            "costs": costs,
            "net_pnl": round(net, 2),
        }

    result["exit_time"] = time_str
    return result


def _compute_max_drawdown(daily_pnls: list, initial_capital: float) -> float:
    """Compute maximum peak-to-trough drawdown as a percentage."""
    if not daily_pnls:
        return 0.0
    equity = initial_capital
    peak = initial_capital
    max_dd = 0.0
    for pnl in daily_pnls:
        equity += pnl
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)
    return max_dd
