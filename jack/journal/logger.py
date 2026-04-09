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
        missed_opportunities: list[dict] = None,
        post_mortems: dict = None,
        day_type: str = None,
        cumulative_stats: dict = None,
    ) -> None:
        """
        Write a JSON file for each trading day.

        Args:
            date: Trading date.
            briefing: Morning briefing dict.
            trade_events: List of trade result dicts.
            decision_log: Scorer decision log.
            capital_state: Risk manager state.
            missed_opportunities: List of missed/blocked trade hypotheticals.
            post_mortems: Dict mapping trade index to post-mortem dict.
            day_type: Classified type of day.
            cumulative_stats: Running system statistics.
        """
        date_str = (date.strftime("%Y-%m-%d")
                    if hasattr(date, 'strftime') else str(date))

        # Add post mortem to trades if provided
        trades = self._format_trades(trade_events)
        if post_mortems:
            for i, trade in enumerate(trades):
                if i in post_mortems:
                    trade["post_mortem"] = post_mortems[i]

        log_entry = {
            "date": date_str,
            "day_of_week": briefing.get("day_of_week", ""),
            "day_type": day_type or "unclassified",

            "pre_market": {
                "gap": briefing.get("gap", {}),
                "regime": briefing.get("regime", "normal"),
                "atr": briefing.get("daily_indicators", {}).get("ATR"),
                "rsi": briefing.get("daily_indicators", {}).get("RSI"),
            },

            "morning_scan": {
                "filter_verdict": {
                    "combined_long": briefing.get("filters", {}).get("combined_long_multiplier"),
                    "combined_short": briefing.get("filters", {}).get("combined_short_multiplier"),
                    "blocked": briefing.get("filters", {}).get("trade_blocked", False),
                },
                "key_levels": {
                    "vwap": briefing.get("vwap"),
                    "pivot": briefing.get("daily_indicators", {}).get("PP"),
                    "r1": briefing.get("daily_indicators", {}).get("R1"),
                    "s1": briefing.get("daily_indicators", {}).get("S1"),
                },
                "streak": briefing.get("streak", {}),
            },

            "first_hour": briefing.get("first_hour", {}),
            "5m_indicators": briefing.get("5m_indicators", {}),
            "strategies_evaluated": decision_log,
            "missed_opportunities": missed_opportunities or [],
            "trades": trades,

            "daily_review": {
                "day_type": day_type,
                "total_pnl": sum(t.get("net_pnl", 0) for t in trade_events),
                "trades_taken": len(trade_events),
            },

            "capital": {
                "start": briefing.get("capital", 0),
                "end": capital_state.get("current_capital", 0),
                "drawdown": capital_state.get("drawdown", {}),
            },

            "cumulative_stats": cumulative_stats or {},
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
                "post_mortem": trade.get("post_mortem", {}),
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
