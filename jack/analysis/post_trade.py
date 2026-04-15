"""
Post-trade analysis engine.
After each trade, computes:
- Edge captured: what % of the available move did we capture?
- Optimal exit: if we held to close, what would P&L be?
- What worked / what failed analysis
- Day type classification
"""

import pandas as pd
import numpy as np


class PostTradeAnalyzer:
    """Analyze completed trades to extract learning insights."""

    def analyze_trade(self, trade: dict, day_data: dict, indicators: dict) -> dict:
        """
        Analyze a single completed trade.

        Returns dict with post-mortem insights.
        """
        direction = trade.get("direction", "LONG")
        entry_price = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        entry_time = trade.get("entry_time", "10:15")
        exit_time = trade.get("exit_time", "15:00")
        net_pnl = trade.get("net_pnl", 0)
        quantity = trade.get("quantity", 0)

        # Get day's full range after entry
        day_15m = day_data.get("15m", pd.DataFrame())
        day_5m = day_data.get("5m", pd.DataFrame())

        # Compute available range after entry
        after_entry = pd.DataFrame()
        if not day_5m.empty:
            after_entry = day_5m[day_5m["Time"].str.strip() >= entry_time]
        elif not day_15m.empty:
            after_entry = day_15m[day_15m["Time"].str.strip() >= entry_time]

        if after_entry.empty:
            return {"error": "no_intraday_data"}

        day_high_after = after_entry["High"].max()
        day_low_after = after_entry["Low"].min()
        close_price = after_entry.iloc[-1]["Close"]

        # Compute available move
        if direction == "LONG":
            max_favorable = day_high_after - entry_price
            max_adverse = entry_price - day_low_after
            if_held_to_close_pnl = (close_price - entry_price) * quantity
            actual_move = exit_price - entry_price
        else:
            max_favorable = entry_price - day_low_after
            max_adverse = day_high_after - entry_price
            if_held_to_close_pnl = (entry_price - close_price) * quantity
            actual_move = entry_price - exit_price

        edge_captured_pct = (actual_move / max_favorable * 100) if max_favorable > 0 else 0

        # Find optimal exit time (max favorable excursion)
        optimal_exit_time = entry_time
        optimal_exit_price = entry_price
        best_pnl = 0

        for _, candle in after_entry.iterrows():
            if direction == "LONG":
                potential = candle["High"] - entry_price
                if potential > best_pnl:
                    best_pnl = potential
                    optimal_exit_price = candle["High"]
                    optimal_exit_time = str(candle["Time"]).strip()[:5]
            else:
                potential = entry_price - candle["Low"]
                if potential > best_pnl:
                    best_pnl = potential
                    optimal_exit_price = candle["Low"]
                    optimal_exit_time = str(candle["Time"]).strip()[:5]

        # Determine what worked / what failed
        what_worked = []
        what_failed = []

        if net_pnl > 0:
            what_worked.append("Direction was correct")
            if edge_captured_pct < 40:
                what_failed.append(
                    f"Only captured {edge_captured_pct:.0f}% of available move "
                    f"— exit too early or target too conservative"
                )
            if edge_captured_pct > 70:
                what_worked.append(f"Excellent edge capture at {edge_captured_pct:.0f}%")
        else:
            what_failed.append("Direction was wrong or entry timing was poor")
            if max_favorable > abs(actual_move):
                what_failed.append(
                    f"Trade went {max_favorable:.0f}pts in favor before reversing "
                    f"— trailing stop would have helped"
                )

        exit_reason = trade.get("exit_reason", "")
        if exit_reason == "time_exit":
            held_to_close_better = if_held_to_close_pnl > net_pnl
            if not held_to_close_better:
                what_worked.append("Time exit was optimal — price deteriorated after exit")
            else:
                what_failed.append(
                    f"Time exit left Rs{if_held_to_close_pnl - net_pnl:,.0f} on the table"
                )

        if exit_reason == "stop_hit":
            what_failed.append("Stop was hit — consider wider stop or later entry")

        return {
            "outcome": "win" if net_pnl > 0 else "loss",
            "edge_captured_pct": round(edge_captured_pct, 1),
            "max_favorable_excursion": round(max_favorable, 1),
            "max_adverse_excursion": round(max_adverse, 1),
            "if_held_to_close_pnl": round(if_held_to_close_pnl, 2),
            "optimal_exit_time": optimal_exit_time,
            "optimal_exit_price": round(optimal_exit_price, 1),
            "optimal_pnl": round(best_pnl * quantity, 2),
            "what_worked": what_worked,
            "what_failed": what_failed,
        }

    def classify_day_type(self, day_data: dict, indicators: dict) -> str:
        """
        Classify the trading day type.

        Returns: "trend_up", "trend_down", "range", "reversal_up",
                 "reversal_down", "gap_and_go", "expansion"
        """
        day_15m = day_data.get("15m", pd.DataFrame())
        if day_15m.empty:
            return "unknown"

        open_price = day_15m.iloc[0]["Open"]
        close_price = day_15m.iloc[-1]["Close"]
        high = day_15m["High"].max()
        low = day_15m["Low"].min()

        day_range = high - low
        body = abs(close_price - open_price)
        body_pct = body / day_range if day_range > 0 else 0

        fh_return = indicators.get("first_hour", {}).get("FH_Return", 0)

        if body_pct > 0.6:
            # Strong body = trend day
            if close_price > open_price:
                return "trend_up"
            else:
                return "trend_down"
        elif body_pct < 0.25:
            # Small body, large range = range/indecision
            return "range"
        else:
            # Medium body — check if first hour reversed
            if fh_return and fh_return != 0:
                fh_bullish = fh_return > 0
                day_bullish = close_price > open_price
                if fh_bullish != day_bullish:
                    return "reversal_down" if fh_bullish else "reversal_up"
            return "range"

    def analyze_missed_trade(self, signal, filter_reason: str, day_data: dict) -> dict:
        """
        Analyze a signal that was blocked — what would have happened?
        """
        day_15m = day_data.get("15m", pd.DataFrame())
        if day_15m.empty:
            return {"hypothetical_pnl": 0, "verdict": "unknown"}

        # Simulate: entry at signal price, exit at 15:00
        close_price = day_15m.iloc[-1]["Close"]

        if signal.direction == "LONG":
            hyp_pnl = (close_price - signal.entry_price) * 75  # Assume 5 lots
            stopped = close_price < signal.stop_loss
        else:
            hyp_pnl = (signal.entry_price - close_price) * 75
            stopped = close_price > signal.stop_loss

        if stopped:
            hyp_pnl = -abs(signal.entry_price - signal.stop_loss) * 75

        filter_correct = (hyp_pnl <= 0)  # Filter was right if trade would have lost

        return {
            "strategy": signal.strategy_name,
            "direction": signal.direction,
            "blocked_by": filter_reason,
            "hypothetical_pnl": round(hyp_pnl, 2),
            "would_have_been_stopped": stopped,
            "verdict": "filter_correct" if filter_correct else "filter_wrong",
        }
