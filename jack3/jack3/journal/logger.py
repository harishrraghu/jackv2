"""
Enhanced trade journal logger for Jack v3.

Writes BOTH:
  - JSON files in journal/notes/json/{date}.json — machine-readable for Lab
  - Markdown files in journal/notes/{date}.md — human-readable, fed to brain

Enhancements over v2:
  - Separate log_entry() and log_exit() for intraday use
  - load_recent_notes() returns structured dicts for brain context
  - thesis tracking (was the direction correct?)
  - decision log for every 5-min tick
"""
import json
import os
from datetime import date as date_cls
from typing import Optional


class JournalLogger:
    """
    Writes daily JSON and markdown journals.

    Usage during trading day:
        logger.log_entry(...)      ← called when position opened
        logger.log_exit(...)       ← called when position closed
        logger.log_day_summary(...) ← called at 15:35

    Usage after day:
        logger.get_recent_entries(n) ← returns last N days for brain context
    """

    def __init__(self, output_dir: str = "journal/notes"):
        self.output_dir = output_dir
        self.json_dir = os.path.join(output_dir, "json")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(self.json_dir, exist_ok=True)

        # Intraday state (accumulates during the day)
        self._today_entries: list = []
        self._today_exits: list = []
        self._today_decisions: list = []

    # ─────────────────────────────────────────────────
    #  Intraday logging
    # ─────────────────────────────────────────────────

    def log_entry(self, tick_time: str, position: dict, thesis: dict, indicators: dict, decision: dict) -> None:
        """Log a trade entry."""
        entry = {
            "type": "entry",
            "time": tick_time,
            "direction": position.get("direction"),
            "entry_price": position.get("entry_price"),
            "stop_loss": position.get("stop_loss"),
            "target": position.get("target"),
            "quantity": position.get("quantity"),
            "strategy": position.get("strategy"),
            "reasoning": decision.get("reasoning", ""),
            "thesis_at_entry": {
                "direction": thesis.get("direction"),
                "confidence": thesis.get("confidence"),
            },
            "indicators": {k: round(float(v), 2) for k, v in indicators.items()
                          if isinstance(v, (int, float)) and not isinstance(v, bool)},
        }
        self._today_entries.append(entry)
        print(f"[Journal] Entry logged: {position.get('direction')} @ {position.get('entry_price')}")

    def log_exit(self, trade_result: dict, thesis: dict) -> None:
        """Log a trade exit with P&L."""
        exit_record = {
            "type": "exit",
            "direction": trade_result.get("direction"),
            "entry_price": trade_result.get("entry_price"),
            "exit_price": trade_result.get("exit_price"),
            "exit_time": trade_result.get("exit_time"),
            "exit_reason": trade_result.get("exit_reason"),
            "gross_pnl": trade_result.get("gross_pnl"),
            "net_pnl": trade_result.get("net_pnl"),
            "costs": trade_result.get("costs", {}).get("total_costs", 0),
            "thesis_direction": thesis.get("direction"),
            "thesis_was_correct": _was_thesis_correct(trade_result, thesis),
        }
        self._today_exits.append(exit_record)
        pnl = trade_result.get("net_pnl", 0)
        print(f"[Journal] Exit logged: P&L Rs.{pnl:.0f} | {trade_result.get('exit_reason')}")

    def log_day_summary(
        self,
        date,
        thesis: dict,
        trades: list,
        decisions: list,
        capital_state: dict,
    ) -> None:
        """Write the full day's journal to JSON and markdown files."""
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)

        total_pnl = sum(t.get("net_pnl", 0) for t in trades)
        wins = sum(1 for t in trades if t.get("net_pnl", 0) > 0)

        # Determine thesis accuracy
        thesis_accuracy = "no_trades"
        if trades:
            correct = sum(1 for t in trades if _was_thesis_correct(t, thesis))
            thesis_accuracy = f"{correct}/{len(trades)}_correct"

        log = {
            "date": date_str,
            "thesis": thesis,
            "thesis_accuracy": thesis_accuracy,
            "trades": trades,
            "tick_decisions_count": len(decisions),
            "daily_summary": {
                "total_pnl": round(total_pnl, 2),
                "trades_taken": len(trades),
                "wins": wins,
                "losses": len(trades) - wins,
                "win_rate": round(wins / len(trades) * 100, 1) if trades else 0,
            },
            "capital": capital_state,
        }

        # Write JSON
        json_path = os.path.join(self.json_dir, f"{date_str}.json")
        with open(json_path, "w") as f:
            json.dump(log, f, indent=2, default=str)

        # Write markdown
        md_path = os.path.join(self.output_dir, f"{date_str}.md")
        self._write_markdown(md_path, log)

        print(f"[Journal] Day summary saved: {date_str} | P&L: Rs.{total_pnl:.0f}")

    # ─────────────────────────────────────────────────
    #  Reading journal for brain context
    # ─────────────────────────────────────────────────

    def get_recent_entries(self, n: int = 10) -> list:
        """
        Return last N days' journal entries as list of dicts.
        Used by brain/thesis.py for pre-market context.
        """
        files = sorted([
            f for f in os.listdir(self.json_dir)
            if f.endswith(".json")
        ], reverse=True)

        entries = []
        for filename in files[:n]:
            filepath = os.path.join(self.json_dir, filename)
            try:
                with open(filepath) as f:
                    entries.append(json.load(f))
            except Exception:
                continue

        return entries

    def get_recent_lessons(self, n: int = 5) -> list:
        """Return the 'lesson' field from recent AI-reviewed journal entries."""
        entries = self.get_recent_entries(n)
        lessons = []
        for entry in entries:
            for trade in entry.get("trades", []):
                lesson = trade.get("ai_review", {}).get("lesson")
                if lesson:
                    lessons.append({"date": entry.get("date"), "lesson": lesson})
        return lessons

    # ─────────────────────────────────────────────────
    #  Markdown generation
    # ─────────────────────────────────────────────────

    def _write_markdown(self, path: str, log: dict) -> None:
        """Write a human-readable markdown journal for the day."""
        thesis = log.get("thesis", {})
        summary = log.get("daily_summary", {})
        trades = log.get("trades", [])
        capital = log.get("capital", {})

        lines = [
            f"# Jack v3 Journal — {log['date']}",
            "",
            "## Pre-Market Thesis",
            f"**Direction:** {thesis.get('direction', 'N/A')} | **Confidence:** {thesis.get('confidence', 0):.0%}",
            f"**Reasoning:** {thesis.get('reasoning', '')}",
            f"**Key Factors:** {', '.join(thesis.get('key_factors', []))}",
            f"**Suggested Strategy:** {thesis.get('suggested_strategy', 'None')}",
            f"**Risk Note:** {thesis.get('risk_note', '')}",
            "",
            "## Daily Summary",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total P&L | Rs.{summary.get('total_pnl', 0):,.0f} |",
            f"| Trades | {summary.get('trades_taken', 0)} |",
            f"| Wins | {summary.get('wins', 0)} |",
            f"| Losses | {summary.get('losses', 0)} |",
            f"| Win Rate | {summary.get('win_rate', 0):.1f}% |",
            f"| Thesis Accuracy | {log.get('thesis_accuracy', 'N/A')} |",
            "",
        ]

        if trades:
            lines += ["## Trades", ""]
            for i, trade in enumerate(trades, 1):
                pnl = trade.get("net_pnl", 0)
                pnl_str = f"+Rs.{pnl:,.0f}" if pnl >= 0 else f"Rs.{pnl:,.0f}"
                lines += [
                    f"### Trade {i}: {trade.get('direction', '')} {trade.get('strategy', '')}",
                    f"- **Entry:** {trade.get('entry_price')} @ {trade.get('entry_time')}",
                    f"- **Exit:** {trade.get('exit_price')} @ {trade.get('exit_time')} ({trade.get('exit_reason')})",
                    f"- **P&L:** {pnl_str}",
                ]
                review = trade.get("ai_review", {})
                if review:
                    lines += [
                        f"- **Entry Quality:** {review.get('entry_quality')}",
                        f"- **Exit Quality:** {review.get('exit_quality')}",
                        f"- **Lesson:** _{review.get('lesson', '')}_",
                    ]
                lines.append("")

        lines += [
            "## Capital State",
            f"- **Current Capital:** Rs.{capital.get('current_capital', 0):,.0f}",
            f"- **Daily P&L:** Rs.{capital.get('daily_pnl', 0):,.0f}",
            f"- **Drawdown:** {capital.get('drawdown', {}).get('daily_drawdown_pct', 0):.2f}%",
        ]

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


# ─────────────────────────────────────────────────
#  Utility
# ─────────────────────────────────────────────────

def _was_thesis_correct(trade: dict, thesis: dict) -> bool:
    """Check if the trade direction matched the thesis direction."""
    trade_dir = trade.get("direction", "")
    thesis_dir = thesis.get("direction", "NEUTRAL")
    if thesis_dir == "BULLISH" and trade_dir == "LONG":
        return trade.get("net_pnl", 0) > 0
    if thesis_dir == "BEARISH" and trade_dir == "SHORT":
        return trade.get("net_pnl", 0) > 0
    return False
