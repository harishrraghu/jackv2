"""
Entry Checklist — 8 Boolean Gates that ALL Must Pass Before Entry.

This is the final safety net before any trade is placed.
Every gate must return True for a trade to proceed.
If ANY gate fails, the trade is rejected with a reason.

Gates:
    1. Confluence direction matches trade direction
    2. Confluence conviction above minimum threshold
    3. RSI not at dangerous extremes
    4. Time window is valid (not too early, not too late)
    5. Risk budget available (daily drawdown not hit)
    6. No blocking events today
    7. Volatility not extreme (ATR filter)
    8. OI confirms direction (if data available)

Usage:
    from engine.entry_checklist import EntryChecklist
    checklist = EntryChecklist()
    result = checklist.evaluate(direction="LONG", context=market_context)
    if result["all_passed"]:
        # Execute trade
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Default thresholds
DEFAULT_THRESHOLDS = {
    "min_conviction": 0.15,          # Minimum confluence conviction score
    "rsi_extreme_high": 85,          # Block LONG above this RSI
    "rsi_extreme_low": 15,           # Block SHORT below this RSI
    "earliest_entry": "09:30",       # Don't enter before this
    "latest_entry": "14:30",         # Don't enter after this
    "max_daily_drawdown_pct": 2.0,   # Daily loss limit
    "max_event_impact": 4,           # Block trading at impact >= this
    "max_atr_ratio": 3.0,            # Block if ATR > 3x avg
}


class EntryChecklist:
    """
    8-gate entry validation system.
    
    All gates must pass for a trade to be allowed.
    Each gate returns (pass: bool, reason: str).
    """

    def __init__(self, thresholds: dict = None):
        """
        Args:
            thresholds: Override default gate thresholds.
        """
        self.thresholds = DEFAULT_THRESHOLDS.copy()
        if thresholds:
            self.thresholds.update(thresholds)

    def evaluate(self, direction: str, context: dict) -> dict:
        """
        Run all 8 gates and return pass/fail for each.
        
        Args:
            direction: "LONG" or "SHORT"
            context: Market context dict with:
                - confluence: dict with direction, conviction
                - rsi: float
                - current_time: str "HH:MM"
                - daily_pnl: float (current day P&L)
                - capital: float (current capital)
                - event: dict from EventCalendar
                - atr: float (current ATR)
                - atr_avg_60d: float (60-day average ATR)
                - oi_buildup: dict from OI analyzer (optional)
                
        Returns:
            Dict with:
                all_passed: bool
                passed_count: int (out of 8)
                gates: list of {name, passed, reason}
                direction: str
                can_trade: bool (alias for all_passed)
        """
        gates = []
        
        # Gate 1: Confluence direction matches
        gates.append(self._gate_confluence_direction(direction, context))
        
        # Gate 2: Conviction threshold
        gates.append(self._gate_conviction(context))
        
        # Gate 3: RSI safety
        gates.append(self._gate_rsi(direction, context))
        
        # Gate 4: Time window
        gates.append(self._gate_time_window(context))
        
        # Gate 5: Risk budget
        gates.append(self._gate_risk_budget(context))
        
        # Gate 6: Event safety
        gates.append(self._gate_event(context))
        
        # Gate 7: Volatility
        gates.append(self._gate_volatility(context))
        
        # Gate 8: OI confirmation
        gates.append(self._gate_oi_confirmation(direction, context))
        
        # Gate 9: Greeks Favorability
        gates.append(self._gate_greeks_favorability(context))
        
        # Gate 10: IV Environment
        gates.append(self._gate_iv_environment(direction, context))
        
        passed_count = sum(1 for g in gates if g["passed"])
        all_passed = all(g["passed"] for g in gates)
        
        return {
            "all_passed": all_passed,
            "can_trade": all_passed,
            "passed_count": passed_count,
            "total_gates": len(gates),
            "gates": gates,
            "direction": direction,
            "failed_gates": [g["name"] for g in gates if not g["passed"]],
        }

    # =========================================================================
    # Gate Implementations
    # =========================================================================

    def _gate_confluence_direction(self, direction: str, ctx: dict) -> dict:
        """Gate 1: Trade direction must match confluence direction."""
        confluence = ctx.get("confluence", {})
        conf_direction = confluence.get("direction", "NEUTRAL")
        
        passed = (conf_direction == direction or conf_direction == "NEUTRAL")
        reason = (
            f"Confluence says {conf_direction}, trade is {direction}"
            if not passed else "Direction aligned"
        )
        
        return {"name": "confluence_direction", "passed": passed, "reason": reason}

    def _gate_conviction(self, ctx: dict) -> dict:
        """Gate 2: Confluence conviction must be above minimum."""
        confluence = ctx.get("confluence", {})
        conviction = confluence.get("conviction", 0)
        threshold = self.thresholds["min_conviction"]
        
        passed = conviction >= threshold
        reason = (
            f"Conviction {conviction:.3f} below threshold {threshold}"
            if not passed else f"Conviction {conviction:.3f} OK"
        )
        
        return {"name": "conviction_threshold", "passed": passed, "reason": reason}

    def _gate_rsi(self, direction: str, ctx: dict) -> dict:
        """Gate 3: RSI not at dangerous extremes for the direction."""
        rsi = ctx.get("rsi")
        
        if rsi is None:
            return {"name": "rsi_extreme", "passed": True, 
                    "reason": "No RSI data — passing by default"}
        
        high = self.thresholds["rsi_extreme_high"]
        low = self.thresholds["rsi_extreme_low"]
        
        if direction == "LONG" and rsi > high:
            return {"name": "rsi_extreme", "passed": False,
                    "reason": f"RSI {rsi:.1f} too high for LONG (max {high})"}
        
        if direction == "SHORT" and rsi < low:
            return {"name": "rsi_extreme", "passed": False,
                    "reason": f"RSI {rsi:.1f} too low for SHORT (min {low})"}
        
        return {"name": "rsi_extreme", "passed": True,
                "reason": f"RSI {rsi:.1f} OK for {direction}"}

    def _gate_time_window(self, ctx: dict) -> dict:
        """Gate 4: Current time must be within entry window."""
        current_time = ctx.get("current_time", "10:15")
        earliest = self.thresholds["earliest_entry"]
        latest = self.thresholds["latest_entry"]
        
        if current_time < earliest:
            return {"name": "time_window", "passed": False,
                    "reason": f"Too early ({current_time} < {earliest})"}
        
        if current_time > latest:
            return {"name": "time_window", "passed": False,
                    "reason": f"Too late ({current_time} > {latest})"}
        
        return {"name": "time_window", "passed": True,
                "reason": f"Time {current_time} within window"}

    def _gate_risk_budget(self, ctx: dict) -> dict:
        """Gate 5: Daily drawdown limit not hit."""
        daily_pnl = ctx.get("daily_pnl", 0)
        capital = ctx.get("capital", 1000000)
        max_dd_pct = self.thresholds["max_daily_drawdown_pct"]
        
        if capital <= 0:
            return {"name": "risk_budget", "passed": False,
                    "reason": "No capital"}
        
        current_dd_pct = abs(min(daily_pnl, 0)) / capital * 100
        
        if current_dd_pct >= max_dd_pct:
            return {"name": "risk_budget", "passed": False,
                    "reason": f"Daily DD {current_dd_pct:.2f}% >= limit {max_dd_pct}%"}
        
        return {"name": "risk_budget", "passed": True,
                "reason": f"Risk budget available (DD: {current_dd_pct:.2f}%)"}

    def _gate_event(self, ctx: dict) -> dict:
        """Gate 6: No high-impact events blocking trading."""
        event = ctx.get("event", {})
        if not isinstance(event, dict):
            return {"name": "event_safety", "passed": True,
                    "reason": "No event data"}
        
        impact = event.get("impact", 1)
        max_impact = self.thresholds["max_event_impact"]
        
        if impact >= max_impact:
            return {"name": "event_safety", "passed": False,
                    "reason": f"{event.get('name', 'Event')} (impact={impact}) blocks trading"}
        
        return {"name": "event_safety", "passed": True,
                "reason": f"No blocking events (impact={impact})"}

    def _gate_volatility(self, ctx: dict) -> dict:
        """Gate 7: ATR not extreme (black swan filter)."""
        atr = ctx.get("atr")
        atr_avg = ctx.get("atr_avg_60d")
        max_ratio = self.thresholds["max_atr_ratio"]
        
        if atr is None or atr_avg is None or atr_avg <= 0:
            return {"name": "volatility_filter", "passed": True,
                    "reason": "No ATR data — passing by default"}
        
        ratio = atr / atr_avg
        
        if ratio > max_ratio:
            return {"name": "volatility_filter", "passed": False,
                    "reason": f"ATR {atr:.0f} is {ratio:.1f}x avg {atr_avg:.0f} (max {max_ratio}x)"}
        
        return {"name": "volatility_filter", "passed": True,
                "reason": f"ATR ratio {ratio:.1f}x OK"}

    def _gate_oi_confirmation(self, direction: str, ctx: dict) -> dict:
        """
        Gate 8: OI buildup confirms trade direction (soft gate).
        
        This gate passes if:
        - OI data confirms direction, OR
        - OI data is neutral, OR
        - No OI data available (pass by default)
        
        Only blocks if OI clearly contradicts the trade direction.
        """
        buildup = ctx.get("oi_buildup", ctx.get("buildup", {}))
        if not isinstance(buildup, dict):
            return {"name": "oi_confirmation", "passed": True,
                    "reason": "No OI data — passing by default"}
        
        classification = buildup.get("classification", "")
        
        if not classification or classification in ("no_data", "insufficient_data"):
            return {"name": "oi_confirmation", "passed": True,
                    "reason": "No OI data — passing by default"}
        
        # Only block on strong contradictions
        contradiction = (
            (direction == "LONG" and classification == "short_buildup") or
            (direction == "SHORT" and classification == "long_buildup")
        )
        
        if contradiction:
            confidence = buildup.get("confidence", 0)
            # Only block if high confidence contradiction
            if confidence > 0.5:
                return {"name": "oi_confirmation", "passed": False,
                        "reason": f"OI shows {classification} vs {direction} trade "
                                  f"(confidence={confidence:.2f})"}
        
        return {"name": "oi_confirmation", "passed": True,
                "reason": f"OI: {classification} — compatible with {direction}"}

    def _gate_greeks_favorability(self, ctx: dict) -> dict:
        """Gate 9: Greeks environment must not be hostile (Theta cliff or low Gamma)."""
        greeks = ctx.get("greeks_momentum", {})
        if not greeks:
            return {"name": "greeks_favorability", "passed": True, "reason": "No Greeks data"}
            
        is_favorable = greeks.get("is_favorable", True)
        signal = greeks.get("signal", "NEUTRAL")
        
        if not is_favorable:
            return {"name": "greeks_favorability", "passed": False, "reason": f"Hostile Greeks: {signal}"}
            
        return {"name": "greeks_favorability", "passed": True, "reason": f"Greeks OK: {signal}"}

    def _gate_iv_environment(self, direction: str, ctx: dict) -> dict:
        """Gate 10: IV environment must not be highly overpriced for buying."""
        iv = ctx.get("iv_edge", {})
        if not iv:
            return {"name": "iv_environment", "passed": True, "reason": "No IV data"}
            
        is_expensive = iv.get("is_expensive", False)
        if is_expensive:
            return {"name": "iv_environment", "passed": False, "reason": "IV/RV ratio too high (Expensive Options)"}
            
        return {"name": "iv_environment", "passed": True, "reason": "IV pricing acceptable"}


if __name__ == "__main__":
    """Example entry checklist evaluation."""
    checklist = EntryChecklist()
    
    context = {
        "confluence": {"direction": "LONG", "conviction": 0.45},
        "rsi": 55,
        "current_time": "10:30",
        "daily_pnl": -3000,
        "capital": 1000000,
        "event": {"name": "Normal", "impact": 1},
        "atr": 350,
        "atr_avg_60d": 300,
        "oi_buildup": {"classification": "long_buildup", "confidence": 0.7},
    }
    
    result = checklist.evaluate("LONG", context)
    
    print(f"Direction: {result['direction']}")
    print(f"All Passed: {result['all_passed']} ({result['passed_count']}/{result['total_gates']})")
    print()
    for gate in result["gates"]:
        status = "[OK]" if gate["passed"] else "[ERR]"
        print(f"  {status} {gate['name']}: {gate['reason']}")
