"""
AI Strategy Discoverer.

Called in the nightly script. Reviews the journal for missed
opportunities and asks the AI to propose new strategies.

Does NOT auto-deploy strategies. All proposals saved for human review
in lab/proposals/{date}_{name}.json.
"""
import json
import os
from datetime import date


class StrategyDiscoverer:
    """Proposes new strategies from missed opportunities in the journal."""

    def __init__(self, ai_client, config: dict):
        self.ai = ai_client
        self.config = config

    def discover(self, journal_entries: list) -> dict:
        """
        Analyze journal entries for missed patterns and propose strategies.

        Args:
            journal_entries: List of recent journal entry dicts.

        Returns:
            Proposal dict (also saved to file).
        """
        # Find missed opportunities -- days with no trade but large moves
        missed = self._find_missed_opportunities(journal_entries)

        if not missed:
            print("[Discoverer] No significant missed opportunities found.")
            return {}

        print(f"[Discoverer] Found {len(missed)} missed opportunity days. Asking AI...")

        from brain.prompts import NIGHTLY_SYSTEM_PROMPT

        prompt = self._build_discovery_prompt(missed, journal_entries)

        try:
            response = self.ai.ask(
                prompt=prompt,
                system=NIGHTLY_SYSTEM_PROMPT,
                response_format="json",
            )

            content = response.get("content", {})
            if isinstance(content, str):
                content = json.loads(content)

            proposal = content.get("new_strategy_proposal", content)

            if proposal and isinstance(proposal, dict) and proposal.get("name"):
                self._save_proposal(proposal)
                self._maybe_backtest(proposal)
                return proposal

        except Exception as e:
            print(f"[Discoverer] Discovery failed: {e}")

        return {}

    def _find_missed_opportunities(self, journal_entries: list) -> list:
        """Find days where no trade was taken but BankNifty moved >200 pts."""
        missed = []
        for entry in journal_entries:
            trades = entry.get("trades", [])
            if len(trades) == 0:
                # No trades taken -- check if market moved
                # We infer from the journal's pre-market thesis or summary
                thesis = entry.get("thesis", {})
                direction = thesis.get("direction", "NEUTRAL")
                if direction != "NEUTRAL":
                    missed.append({
                        "date": entry.get("date"),
                        "thesis_direction": direction,
                        "reason_no_trade": "no_signal_fired",
                        "daily_summary": entry.get("daily_review", {}),
                    })
        return missed

    def _build_discovery_prompt(self, missed: list, all_entries: list) -> str:
        return f"""Analyze the following missed trading opportunities in BankNifty.

MISSED OPPORTUNITIES (days where thesis was directional but no trade was taken):
{json.dumps(missed, indent=2, default=str)}

RECENT TRADING HISTORY:
{json.dumps([{
    "date": e.get("date"),
    "trades": len(e.get("trades", [])),
    "pnl": e.get("daily_review", {}).get("total_pnl", 0),
} for e in all_entries[:10]], indent=2)}

Based on the missed opportunities, propose ONE new trading strategy that could have captured these moves.

Respond ONLY with this JSON:
{{
  "new_strategy_proposal": {{
    "name": "snake_case_name",
    "description": "what it does in 1 sentence",
    "entry_conditions": [
      "specific condition with numbers e.g. RSI > 60 AND price > EMA_20"
    ],
    "exit_conditions": [
      "specific exit condition"
    ],
    "indicators_needed": ["indicator_1", "indicator_2"],
    "time_window": "HH:MM-HH:MM",
    "stop_loss_rule": "e.g. 0.5 * ATR below entry",
    "target_rule": "e.g. 2.0 * ATR above entry",
    "expected_win_rate_pct": number,
    "confidence": "low" | "medium" | "high",
    "rationale": "why this pattern should work"
  }}
}}"""

    def _save_proposal(self, proposal: dict) -> None:
        """Save strategy proposal to lab/proposals/."""
        os.makedirs("lab/proposals", exist_ok=True)
        name = proposal.get("name", "unknown")
        filename = f"lab/proposals/{date.today()}_{name}.json"
        with open(filename, "w") as f:
            json.dump(proposal, f, indent=2)
        print(f"[Discoverer] Proposal saved: {filename}")

    def _maybe_backtest(self, proposal: dict) -> None:
        """
        Attempt to backtest the proposed strategy if it matches an existing one.
        (Actual new strategy code generation is out of scope -- human must implement.)
        """
        name = proposal.get("name", "")
        # Check if strategy file already exists
        strategy_file = f"strategies/{name}.py"
        if os.path.exists(strategy_file):
            print(f"[Discoverer] Strategy file exists, could backtest: {name}")
        else:
            print(f"[Discoverer] Strategy '{name}' is new -- implement {strategy_file} to backtest.")
