"""
5-minute candle re-evaluator.

Called every 5 minutes during market hours (09:15-15:30).
Asks the AI whether to hold, enter, exit, or manage the current position.

Anti-hallucination validation is done AFTER the AI responds,
in engine/loop.py (not here).

Batch cache:
    If a batch decision cache is loaded (via load_batch_cache), every call to
    evaluate() reads from that cache instead of making a live API call.
    This is used by the historical simulator to avoid per-candle API calls.
    Cache is keyed by (date_str, time_str) — date set via set_trade_date().
"""
import json
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from brain.ai_client import AIClient


class Evaluator:
    """Evaluates each 5-minute candle with AI to decide on trading action."""

    def __init__(self, ai_client: "AIClient"):
        self.ai = ai_client
        # Batch cache: { "YYYY-MM-DD": { "HH:MM": {decision} } }
        # Set by load_batch_cache(). When populated, evaluate() reads from here.
        self._batch_cache: dict = {}
        self._current_date: str = ""  # Set by the sim loop before each day

    def load_batch_cache(self, cache: dict) -> None:
        """Load a pre-computed batch decision cache. Disables live AI calls."""
        self._batch_cache = cache
        total = sum(len(v) for v in cache.values())
        print(f"[Evaluator] Batch cache loaded: {len(cache)} days, {total} decisions")

    def clear_batch_cache(self) -> None:
        """Clear the batch cache — reverts to live AI calls."""
        self._batch_cache = {}
        self._current_date = ""

    def set_trade_date(self, date_str: str) -> None:
        """Tell the evaluator which date is being simulated (for cache lookups)."""
        self._current_date = str(date_str)

    def evaluate(
        self,
        thesis: dict,
        current_candle: dict,
        option_chain_summary: dict,
        open_position: Optional[dict],
        indicators: dict,
        time: str,
        daily_pnl: float,
        ticks_below_vwap: int = 0,
    ) -> dict:
        """
        Get AI decision for the current 5-minute tick.

        If a batch cache is loaded, returns the cached decision for this
        (date, time) pair — no API call is made.

        Returns:
            {
              "thesis_update": str,
              "confidence": float,
              "action": str,        # "HOLD"|"ENTER_LONG"|"ENTER_SHORT"|"EXIT"|"TIGHTEN_SL"|"WAIT"
              "entry_price": float|None,
              "stop_loss": float|None,
              "target": float|None,
              "reasoning": str,
            }
        """
        # ── Batch cache lookup (no API call) ──────────────────────────
        if self._batch_cache and self._current_date:
            day_cache = self._batch_cache.get(self._current_date, {})
            if day_cache:
                cached = day_cache.get(time)
                if cached:
                    return cached
                # If this exact time isn't in cache, return HOLD silently
                return self._safe_hold(f"time {time} not in batch cache")

        # ── Live API call ──────────────────────────────────────────────
        from brain.prompts import five_min_evaluation_prompt, INTRADAY_SYSTEM_PROMPT

        prompt = five_min_evaluation_prompt(
            thesis=thesis,
            current_candle=current_candle,
            option_chain_summary=option_chain_summary,
            open_position=open_position,
            indicators=indicators,
            time=time,
            daily_pnl=daily_pnl,
            ticks_below_vwap=ticks_below_vwap,
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

            decision = {
                "thesis_update": content.get("thesis_update", "NEUTRAL"),
                "confidence": float(content.get("confidence", 0.5)),
                "action": content.get("action", "HOLD"),
                "entry_price": _safe_float(content.get("entry_price")),
                "stop_loss": _safe_float(content.get("stop_loss")),
                "target": _safe_float(content.get("target")),
                "reasoning": str(content.get("reasoning", ""))[:200],
            }

            # Validate action is known
            valid_actions = {"HOLD", "ENTER_LONG", "ENTER_SHORT", "EXIT", "TIGHTEN_SL", "WAIT"}
            if decision["action"] not in valid_actions:
                print(f"[Evaluator] Unknown action '{decision['action']}' -- defaulting to HOLD")
                decision["action"] = "HOLD"

            return decision

        except Exception as e:
            print(f"[Evaluator] AI evaluation failed at {time}: {e}")
            return self._safe_hold(str(e))

    def _safe_hold(self, reason: str = "") -> dict:
        """Return a safe HOLD decision when AI fails."""
        return {
            "thesis_update": "NEUTRAL",
            "confidence": 0.0,
            "action": "HOLD",
            "entry_price": None,
            "stop_loss": None,
            "target": None,
            "reasoning": f"AI unavailable: {reason[:100]}",
        }


def _safe_float(value) -> Optional[float]:
    """Safely convert a value to float, returning None if not possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
