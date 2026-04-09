"""
Structured trade journal logger.

Writes JSON files for each trading day and summary files.
"""

import json
import os
from typing import Optional

import pandas as pd


class JournalLogger:
    """
    Structured trade journal.

    Writes daily JSON logs and summary files to journal/logs/.
    """

    def __init__(self, output_dir: str = "journal/logs/"):
        """
        Initialize the journal logger.

        Args:
            output_dir: Directory to write log files.
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def log_day(
        self,
        date,
        briefing: dict,
        trade_events: list[dict],
        decision_log: list[dict],
        capital_state: dict,
    ) -> None:
        """
        Write a JSON file for each trading day.

        Args:
            date: Trading date.
            briefing: Morning briefing dict.
            trade_events: List of trade result dicts.
            decision_log: Scorer decision log.
            capital_state: Risk manager state.
        """
        date_str = (date.strftime("%Y-%m-%d")
                    if hasattr(date, 'strftime') else str(date))

        log_entry = {
            "date": date_str,
            "day_of_week": briefing.get("day_of_week", ""),
            "capital_start": briefing.get("capital", 0),
            "capital_end": capital_state.get("current_capital", 0),
            "morning_scan": {
                "gap_type": briefing.get("gap", {}).get("Gap_Type", "flat"),
                "gap_pct": briefing.get("gap", {}).get("Gap_Pct"),
                "regime": briefing.get("regime", "normal"),
                "atr": briefing.get("daily_indicators", {}).get("ATR"),
                "rsi_daily": briefing.get("daily_indicators", {}).get("RSI"),
                "streak": briefing.get("streak", {}),
                "filter_verdict": {
                    "combined_long_mult": briefing.get("filters", {}).get(
                        "combined_long_multiplier"),
                    "combined_short_mult": briefing.get("filters", {}).get(
                        "combined_short_multiplier"),
                },
            },
            "first_hour": briefing.get("first_hour", {}),
            "strategies_evaluated": decision_log,
            "trades": self._format_trades(trade_events),
            "drawdown": capital_state.get("drawdown", {}),
        }

        filepath = os.path.join(self.output_dir, f"{date_str}.json")
        try:
            with open(filepath, "w") as f:
                json.dump(log_entry, f, indent=2, default=str)
        except Exception as e:
            print(f"[journal] Failed to write {filepath}: {e}")

    def _format_trades(self, trade_events: list[dict]) -> list[dict]:
        """Format trade events for JSON serialization."""
        formatted = []
        for trade in trade_events:
            formatted.append({
                "strategy": trade.get("strategy", ""),
                "direction": trade.get("direction", ""),
                "entry_time": trade.get("entry_time", ""),
                "entry_price": trade.get("entry_price", 0),
                "exit_time": trade.get("exit_time", ""),
                "exit_price": trade.get("exit_price", 0),
                "stop_loss": trade.get("stop_loss", 0),
                "target": trade.get("target", 0),
                "quantity": trade.get("quantity", 0),
                "gross_pnl": trade.get("gross_pnl", 0),
                "costs": trade.get("costs", {}).get("total_costs", 0),
                "net_pnl": trade.get("net_pnl", 0),
                "exit_reason": trade.get("exit_reason", ""),
            })
        return formatted

    def log_summary(self, split: str, results: dict) -> None:
        """
        Write a summary JSON file.

        Args:
            split: "train", "test", or "holdout".
            results: Simulation results dict.
        """
        # Remove non-serializable items
        summary = {k: v for k, v in results.items()
                    if k not in ("trade_log",)}

        filepath = os.path.join(self.output_dir, f"summary_{split}.json")
        try:
            with open(filepath, "w") as f:
                json.dump(summary, f, indent=2, default=str)
        except Exception as e:
            print(f"[journal] Failed to write summary: {e}")

    def get_recent_entries(self, n: int = 3) -> list[dict]:
        """
        Read the last N journal entries.

        Args:
            n: Number of recent entries to return.

        Returns:
            List of journal entry dicts, most recent first.
        """
        files = sorted([
            f for f in os.listdir(self.output_dir)
            if f.endswith(".json") and not f.startswith("summary_")
        ], reverse=True)

        entries = []
        for filename in files[:n]:
            filepath = os.path.join(self.output_dir, filename)
            try:
                with open(filepath, "r") as f:
                    entries.append(json.load(f))
            except Exception:
                continue

        return entries
