import json
import os
from typing import Optional

class AgentState:
    """Persists the agent's state between single-day executions."""
    
    STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

    def __init__(self, current_date: str, capital: float, peak_capital: float, 
                 open_position: Optional[dict] = None, drawdown: dict = None):
        self.current_date = current_date
        self.capital = capital
        self.peak_capital = peak_capital
        self.open_position = open_position
        self.drawdown = drawdown or {"current_drawdown_pct": 0.0, "daily_drawdown_pct": 0.0}

    @classmethod
    def init_state(cls, start_date: str, initial_capital: float):
        """Initialize and write a fresh state."""
        state = cls(start_date, initial_capital, initial_capital)
        state.save()
        return state

    @classmethod
    def load(cls) -> 'AgentState':
        """Load state from file."""
        if not os.path.exists(cls.STATE_FILE):
            raise FileNotFoundError("Agent state not initialized. Run init first.")
            
        with open(cls.STATE_FILE, 'r') as f:
            data = json.load(f)
            
        return cls(
            current_date=data["current_date"],
            capital=data["capital"],
            peak_capital=data["peak_capital"],
            open_position=data.get("open_position"),
            drawdown=data.get("drawdown")
        )

    def save(self):
        """Save current state to file."""
        data = {
            "current_date": self.current_date,
            "capital": self.capital,
            "peak_capital": self.peak_capital,
            "open_position": self.open_position,
            "drawdown": self.drawdown
        }
        with open(self.STATE_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
