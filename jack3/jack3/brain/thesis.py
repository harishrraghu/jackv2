"""
Pre-market thesis generator.

Called at 08:55. Combines dependent data, news research, recent
journal history, and strategy rankings to generate a directional
thesis for the trading day.
"""
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brain.ai_client import AIClient


class ThesisGenerator:
    """Generates the pre-market directional thesis using AI."""

    def __init__(self, ai_client: "AIClient"):
        self.ai = ai_client

    def generate(
        self,
        dependents: dict,
        research: dict,
        recent_journal: list,
        strategy_rankings: list,
    ) -> dict:
        """
        Generate pre-market thesis.

        Falls back to dependent data bias if AI fails.

        Returns:
            {
              "direction": "BULLISH"|"BEARISH"|"NEUTRAL",
              "confidence": float,
              "reasoning": str,
              "key_factors": list,
              "suggested_strategy": str|None,
              "risk_note": str,
              "expected_range_pts": int,
              "bias_entry_after": str,
            }
        """
        from brain.prompts import pre_market_thesis_prompt, INTRADAY_SYSTEM_PROMPT

        prompt = pre_market_thesis_prompt(
            dependents=dependents,
            research=research,
            recent_journal=recent_journal,
            strategy_rankings=strategy_rankings,
        )

        try:
            response = self.ai.ask(
                prompt=prompt,
                system=INTRADAY_SYSTEM_PROMPT,
                response_format="json",
            )

            content = response.get("content", {})
            if isinstance(content, str):
                content = json.loads(content)

            # Validate and fill defaults
            thesis = {
                "direction": content.get("direction", "NEUTRAL"),
                "confidence": float(content.get("confidence", 0.5)),
                "reasoning": content.get("reasoning", ""),
                "key_factors": content.get("key_factors", []),
                "suggested_strategy": content.get("suggested_strategy"),
                "risk_note": content.get("risk_note", ""),
                "expected_range_pts": int(content.get("expected_range_pts", 300)),
                "bias_entry_after": content.get("bias_entry_after", "10:15"),
            }

            # Clamp confidence
            thesis["confidence"] = max(0.0, min(1.0, thesis["confidence"]))

            print(f"[ThesisGenerator] Thesis: {thesis['direction']} | Confidence: {thesis['confidence']:.2f}")
            return thesis

        except Exception as e:
            print(f"[ThesisGenerator] AI failed: {e}. Using fallback.")
            return self._fallback_thesis(dependents)

    def _fallback_thesis(self, dependents: dict) -> dict:
        """Fallback thesis based purely on dependent data weighted bias."""
        bias = dependents.get("weighted_bias", 0)
        bias_dir = dependents.get("bias_direction", "NEUTRAL")

        # Map direction to confidence
        confidence = min(abs(bias) * 2, 0.6)  # Max fallback confidence = 0.6

        return {
            "direction": bias_dir,
            "confidence": round(confidence, 2),
            "reasoning": f"Fallback: AI unavailable. Dependent bias = {bias:.3f}",
            "key_factors": [k for k, v in dependents.items()
                            if isinstance(v, dict) and abs(v.get("signal", 0)) > 0.1],
            "suggested_strategy": None,
            "risk_note": "Low confidence thesis — AI unavailable. Trade smaller.",
            "expected_range_pts": 300,
            "bias_entry_after": "10:15",
        }
