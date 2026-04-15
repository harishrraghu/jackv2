"""
Paper Trading Engine v2 — lightweight in-memory paper trade tracker.

Used by scripts/paper_trade.py for manual one-off paper trades.
For the full live loop, use scripts/live_loop.py instead.
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

PAPER_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cache", "paper_state.json"
)

STARTING_CAPITAL = 100_000   # Rs 1 lakh paper capital
LOT_SIZE         = 15        # BankNifty default

SL_PCT     = 0.30   # 30% of premium as default SL
TARGET_PCT = 0.60   # 60% of premium as default target


class PaperTradingEngine:
    """
    Simple paper trading engine.
    Persists state to disk across calls within the same day.
    """

    def __init__(self, starting_capital: float = STARTING_CAPITAL):
        self._state = self._load_state(starting_capital)

    # ── Public API ────────────────────────────────────────────────────────────

    def place_order(self, direction: str, strike: float, option_type: str,
                    premium: float, lots: int = 1,
                    stop_loss: float = None, target: float = None,
                    strategy: str = "") -> dict:
        """
        Place a paper option order.

        Args:
            direction: "BUY" or "SELL"
            strike:    Option strike price
            option_type: "CE" or "PE"
            premium:   Entry premium per unit
            lots:      Number of lots (each lot = LOT_SIZE contracts)
            stop_loss: SL price (defaults to 30% below entry)
            target:    Target price (defaults to 60% above entry)
            strategy:  Strategy name tag

        Returns:
            dict with status and position details.
        """
        if not premium or premium <= 0:
            return {"status": "REJECTED", "reason": "invalid_premium"}

        sl  = stop_loss or round(premium * (1 - SL_PCT), 2)
        tgt = target    or round(premium * (1 + TARGET_PCT), 2)

        qty     = lots * LOT_SIZE
        cost    = premium * qty
        capital = self._state["current_capital"]

        if cost > capital:
            return {"status": "REJECTED",
                    "reason": f"insufficient_capital (need ₹{cost:,.0f}, have ₹{capital:,.0f})"}

        pos_id = str(uuid.uuid4())[:8]
        pos = {
            "id":           pos_id,
            "timestamp":    datetime.now(IST).isoformat(),
            "direction":    direction,
            "strike":       strike,
            "option_type":  option_type,
            "entry_premium": premium,
            "stop_loss":    sl,
            "target":       tgt,
            "lots":         lots,
            "qty":          qty,
            "cost":         cost,
            "strategy":     strategy,
            "status":       "open",
        }

        self._state["positions"].append(pos)
        self._state["current_capital"] -= cost
        self._state["daily_trades"] += 1
        self._save_state()

        return {"status": "PLACED", "position": pos}

    def close_position(self, pos_id: str, exit_premium: float,
                       reason: str = "manual") -> dict:
        """Close an open position."""
        for pos in self._state["positions"]:
            if pos["id"] == pos_id and pos["status"] == "open":
                pnl = (exit_premium - pos["entry_premium"]) * pos["qty"]
                pos["status"]       = "closed"
                pos["exit_premium"] = exit_premium
                pos["exit_time"]    = datetime.now(IST).isoformat()
                pos["exit_reason"]  = reason
                pos["realized_pnl"] = pnl

                self._state["current_capital"] += pos["cost"] + pnl
                self._state["daily_pnl"]       += pnl
                self._save_state()
                return {"status": "CLOSED", "pnl": pnl, "position": pos}

        return {"status": "NOT_FOUND", "pos_id": pos_id}

    def get_summary(self) -> dict:
        open_pos = [p for p in self._state["positions"] if p["status"] == "open"]
        return {
            "current_capital": self._state["current_capital"],
            "daily_pnl":       self._state["daily_pnl"],
            "daily_trades":    self._state["daily_trades"],
            "open_positions":  len(open_pos),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_state(self, starting_capital: float) -> dict:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if os.path.exists(PAPER_STATE_FILE):
            try:
                with open(PAPER_STATE_FILE) as f:
                    state = json.load(f)
                if state.get("date") == today:
                    return state
            except Exception:
                pass
        return {
            "date":             today,
            "starting_capital": starting_capital,
            "current_capital":  starting_capital,
            "daily_pnl":        0.0,
            "daily_trades":     0,
            "positions":        [],
        }

    def _save_state(self):
        os.makedirs(os.path.dirname(PAPER_STATE_FILE), exist_ok=True)
        with open(PAPER_STATE_FILE, "w") as f:
            json.dump(self._state, f, indent=2, default=str)
