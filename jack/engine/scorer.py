"""
Strategy Scorer / Arbitration.

Resolves conflicts when multiple strategies trigger simultaneously.
Applies filter multipliers and confluence bonuses/penalties.
"""

from typing import Optional

from strategies.base import TradeSignal, Strategy


class StrategyScorer:
    """
    Scores and selects the best trade signal when multiple strategies trigger.

    Applies:
    - Strategy-specific scoring
    - Filter multipliers (day-of-week, RSI, etc.)
    - Confluence bonuses (multiple signals same direction)
    - Confluence penalties (conflicting signals)
    """

    def __init__(self, strategies: dict[str, Strategy],
                 min_score_threshold: float = 0.5):
        """
        Initialize scorer.

        Args:
            strategies: Dict mapping strategy name to Strategy instance.
            min_score_threshold: Minimum score to accept a signal.
        """
        self.strategies = strategies
        self.min_score_threshold = min_score_threshold
        self._decision_log: list[dict] = []

    def score_signals(
        self,
        signals: list[TradeSignal],
        filters: dict,
    ) -> list[tuple[TradeSignal, float]]:
        """
        Score all trade signals and return sorted by score descending.

        Applies:
        1. Strategy-specific scoring
        2. Filter direction multipliers
        3. Confluence adjustments

        Args:
            signals: List of TradeSignal objects.
            filters: Filter stack output dict.

        Returns:
            List of (signal, final_score) sorted descending.
        """
        if not signals:
            return []

        scored = []

        for signal in signals:
            strategy = self.strategies.get(signal.strategy_name)
            if strategy is None:
                continue

            # Base score from strategy
            base_score = strategy.score(signal, filters)

            # Apply filter multipliers based on direction
            if signal.direction == "LONG":
                filter_mult = filters.get("combined_long_multiplier", 1.0)
            else:
                filter_mult = filters.get("combined_short_multiplier", 1.0)

            scored.append((signal, base_score, filter_mult))

        # Check for confluence
        directions = [s.direction for s in signals]
        long_count = directions.count("LONG")
        short_count = directions.count("SHORT")
        has_agreement = long_count >= 2 or short_count >= 2
        has_conflict = long_count > 0 and short_count > 0

        result = []
        for signal, base_score, filter_mult in scored:
            adjusted = base_score * filter_mult

            # Confluence adjustment
            if has_agreement:
                # 2+ signals agree on direction
                if ((signal.direction == "LONG" and long_count >= 2) or
                        (signal.direction == "SHORT" and short_count >= 2)):
                    adjusted += 0.15

            if has_conflict:
                adjusted -= 0.1

            # Cap between 0.0 and 2.0
            final = max(0.0, min(2.0, adjusted))
            result.append((signal, final))

        # Sort by score descending
        result.sort(key=lambda x: x[1], reverse=True)
        return result

    def select_trade(
        self,
        signals: list[TradeSignal],
        filters: dict,
    ) -> Optional[TradeSignal]:
        """
        Select the best trade from scored signals.

        Args:
            signals: List of TradeSignal objects.
            filters: Filter stack output.

        Returns:
            Best TradeSignal or None if all below threshold.
        """
        if not signals:
            self._decision_log.append({
                "signals_considered": 0,
                "selected": None,
                "reason": "no_signals",
            })
            return None

        scored = self.score_signals(signals, filters)

        # Filter out below threshold
        passing = [(s, score) for s, score in scored if score >= self.min_score_threshold]

        log_entry = {
            "signals_considered": len(signals),
            "all_scores": [
                {"strategy": s.strategy_name, "direction": s.direction,
                 "score": round(score, 4)}
                for s, score in scored
            ],
            "passing": len(passing),
            "filtered_out": [
                {"strategy": s.strategy_name, "score": round(score, 4)}
                for s, score in scored if score < self.min_score_threshold
            ],
        }

        if not passing:
            log_entry["selected"] = None
            log_entry["reason"] = "all_below_threshold"
            self._decision_log.append(log_entry)
            return None

        # Select highest scored
        selected_signal, selected_score = passing[0]
        log_entry["selected"] = {
            "strategy": selected_signal.strategy_name,
            "direction": selected_signal.direction,
            "score": round(selected_score, 4),
        }
        log_entry["reason"] = "highest_score"

        self._decision_log.append(log_entry)
        return selected_signal

    def get_decision_log(self) -> list[dict]:
        """Return the log of all scoring decisions for journaling."""
        return self._decision_log

    def clear_log(self) -> None:
        """Clear the decision log."""
        self._decision_log = []
