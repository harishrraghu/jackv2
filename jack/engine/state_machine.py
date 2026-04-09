"""
Time-of-day state machine.

Enforces which strategies can act at which time during the trading day.
The market day is divided into 7 phases, each with specific allowed
actions and eligible strategies.
"""


class TradingPhase:
    """A single time-of-day trading phase."""

    def __init__(self, name: str, start: str, end: str,
                 allowed_actions: list[str], eligible_strategies: list[str]):
        """
        Initialize a trading phase.

        Args:
            name: Phase identifier.
            start: Start time "HH:MM".
            end: End time "HH:MM".
            allowed_actions: List of "observe", "enter", "exit", "manage".
            eligible_strategies: List of strategy names or ["ALL"].
        """
        self.name = name
        self.start = start
        self.end = end
        self.allowed_actions = allowed_actions
        self.eligible_strategies = eligible_strategies

    def __repr__(self) -> str:
        return f"TradingPhase({self.name}, {self.start}-{self.end})"


class StateMachine:
    """
    Market time-of-day state machine.

    Phases:
    1. pre_market (09:00-09:15): Observe only
    2. opening_observation (09:15-09:30): Record ORB, no trading
    3. morning_setups (09:30-10:15): Gap-based and streak strategies
    4. first_hour_execution (10:15-11:15): First hour verdict
    5. dead_zone (11:15-13:15): BB squeeze only, manage positions
    6. afternoon_push (13:15-15:00): Continuation trades
    7. closing (15:00-15:30): Close all positions, no new entries
    """

    def __init__(self):
        self.phases = [
            TradingPhase(
                name="pre_market",
                start="09:00",
                end="09:15",
                allowed_actions=["observe"],
                eligible_strategies=[],
            ),
            TradingPhase(
                name="opening_observation",
                start="09:15",
                end="09:30",
                allowed_actions=["observe"],
                eligible_strategies=[],
            ),
            TradingPhase(
                name="morning_setups",
                start="09:30",
                end="10:15",
                allowed_actions=["enter", "exit", "manage"],
                eligible_strategies=["gap_fill", "gap_up_fade", "streak_fade", "theta_harvest"],
            ),
            TradingPhase(
                name="first_hour_execution",
                start="10:15",
                end="11:15",
                allowed_actions=["enter", "exit", "manage"],
                eligible_strategies=["first_hour_verdict"],
            ),
            TradingPhase(
                name="dead_zone",
                start="11:15",
                end="13:15",
                allowed_actions=["exit", "manage", "enter"],
                eligible_strategies=["bb_squeeze", "vwap_reversion"],
            ),
            TradingPhase(
                name="afternoon_push",
                start="13:15",
                end="15:00",
                allowed_actions=["enter", "exit", "manage"],
                eligible_strategies=["first_hour_verdict", "bb_squeeze", "vwap_reversion"],
            ),
            TradingPhase(
                name="closing",
                start="15:00",
                end="15:30",
                allowed_actions=["exit"],
                eligible_strategies=[],
            ),
        ]

    def _time_to_minutes(self, time_str: str) -> int:
        """Convert "HH:MM" to minutes since midnight."""
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def get_current_phase(self, time: str) -> TradingPhase:
        """
        Get the trading phase for a given time.

        Args:
            time: Time string "HH:MM".

        Returns:
            The matching TradingPhase.

        Raises:
            ValueError: If time is outside market hours.
        """
        t = self._time_to_minutes(time)

        for phase in self.phases:
            start = self._time_to_minutes(phase.start)
            end = self._time_to_minutes(phase.end)

            if start <= t < end:
                return phase

        # If exactly at 15:30, it's closing
        if t == self._time_to_minutes("15:30"):
            return self.phases[-1]  # closing

        raise ValueError(
            f"Time {time} is outside market hours (09:00-15:30)"
        )

    def can_enter(self, time: str, strategy_name: str) -> bool:
        """
        Check if a strategy can enter a trade at the given time.

        Args:
            time: Current time "HH:MM".
            strategy_name: Name of the strategy.

        Returns:
            True if entry is allowed.
        """
        try:
            phase = self.get_current_phase(time)
        except ValueError:
            return False

        return (
            "enter" in phase.allowed_actions
            and (strategy_name in phase.eligible_strategies
                 or "ALL" in phase.eligible_strategies)
        )

    def can_exit(self, time: str) -> bool:
        """Check if exits are allowed at the given time."""
        try:
            phase = self.get_current_phase(time)
        except ValueError:
            return False
        return "exit" in phase.allowed_actions

    def must_exit_all(self, time: str) -> bool:
        """Return True if we're in the closing phase (must close all)."""
        try:
            phase = self.get_current_phase(time)
        except ValueError:
            return True  # If outside hours, force exit
        return phase.name == "closing"

    def get_eligible_strategies(self, time: str) -> list[str]:
        """
        Return list of strategy names that can enter in the current phase.

        Args:
            time: Current time "HH:MM".

        Returns:
            List of eligible strategy names.
        """
        try:
            phase = self.get_current_phase(time)
        except ValueError:
            return []

        if "enter" not in phase.allowed_actions:
            return []

        return phase.eligible_strategies
