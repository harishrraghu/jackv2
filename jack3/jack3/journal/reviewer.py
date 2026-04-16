"""
Post-trade AI reviewer.

Called at 15:35 after market close. Uses the AI to generate a structured
journal entry for each trade: what worked, what failed, lessons learned.

The "lesson" field is the key self-improvement mechanism -- it feeds back
into the brain's thesis generation the next morning.
"""
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brain.ai_client import AIClient
    from journal.logger import JournalLogger


class PostTradeReviewer:
    """Reviews completed trades and generates AI-powered journal entries."""

    def __init__(self, ai_client: "AIClient", journal: "JournalLogger"):
        self.ai = ai_client
        self.journal = journal

    def review_today(
        self,
        trades: list,
        thesis: dict,
        decisions: list,
    ) -> list:
        """
        Generate AI journal entries for each trade from today.

        Args:
            trades: List of completed trade result dicts.
            thesis: Pre-market thesis dict.
            decisions: All 5-min tick decisions for context.

        Returns:
            List of AI review dicts (one per trade).
        """
        if not trades:
            print("[Reviewer] No trades today -- skipping AI review.")
            return []

        reviews = []
        for i, trade in enumerate(trades):
            print(f"[Reviewer] Reviewing trade {i+1}/{len(trades)}...")
            try:
                review = self._review_trade(trade, thesis, decisions)
                trade["ai_review"] = review
                reviews.append(review)

                lesson = review.get("lesson", "")
                if lesson:
                    print(f"[Reviewer] Lesson: {lesson}")

            except Exception as e:
                print(f"[Reviewer] Review failed for trade {i+1}: {e}")
                reviews.append({"error": str(e)})

        return reviews

    def _review_trade(self, trade: dict, thesis: dict, decisions: list) -> dict:
        """Generate AI review for a single trade."""
        from brain.prompts import journal_entry_prompt, NIGHTLY_SYSTEM_PROMPT

        # Build market context from decisions around entry/exit time
        entry_time = trade.get("entry_time", "")
        relevant_decisions = [
            d for d in decisions
            if d.get("tick_time", "") >= entry_time
        ][:10]

        market_context = {
            "thesis": thesis,
            "decisions_near_entry": relevant_decisions[:3],
            "exit_reason": trade.get("exit_reason"),
            "pnl": trade.get("net_pnl"),
            "direction_matched_thesis": (
                (thesis.get("direction") == "BULLISH" and trade.get("direction") == "LONG") or
                (thesis.get("direction") == "BEARISH" and trade.get("direction") == "SHORT")
            ),
        }

        prompt = journal_entry_prompt(trade, market_context)

        response = self.ai.ask(
            prompt=prompt,
            system=NIGHTLY_SYSTEM_PROMPT,
            response_format="json",
        )

        content = response.get("content", {})
        if isinstance(content, str):
            content = json.loads(content)

        return {
            "summary": content.get("summary", ""),
            "entry_quality": content.get("entry_quality", "fair"),
            "exit_quality": content.get("exit_quality", "fair"),
            "what_worked": content.get("what_worked", ""),
            "what_failed": content.get("what_failed", ""),
            "lesson": content.get("lesson", ""),
            "strategy_note": content.get("strategy_note", ""),
            "market_read_accuracy": content.get("market_read_accuracy", "partial"),
        }
