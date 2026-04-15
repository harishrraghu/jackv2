"""
Alerts System.

Manages sending notifications (Discord/Telegram) based on trading system events.
"""

import sys

class AlertManager:
    """Manages system alerts."""

    def __init__(self, platform: str, webhook_url: str = None):
        self.platform = platform
        self.webhook_url = webhook_url

    def _send(self, title: str, message: str):
        """Mock sender. Replace with requests.post for real usage."""
        print(f"\n[ALERT - {self.platform}] {title}")
        print(f"{message}\n", file=sys.stderr)

    def trigger_signal(self, strategy_name: str, direction: str, price: float):
        self._send(
            "Signal Generated",
            f"{strategy_name} triggered {direction} at {price:.2f}"
        )

    def trigger_trade_entered(self, strategy_name: str, direction: str, price: float, qty: int, stop_loss: float):
        self._send(
            "Trade Entered",
            f"{direction} {qty} units in {strategy_name} @ {price:.2f}. SL: {stop_loss:.2f}"
        )

    def trigger_trade_exited(self, strategy_name: str, direction: str, exit_price: float, pnl: float, reason: str):
        sign = "+" if pnl > 0 else ""
        self._send(
            "Trade Exited",
            f"Closed {direction} from {strategy_name} @ {exit_price:.2f}\n"
            f"Reason: {reason}\n"
            f"Net P&L: Rs{sign}{pnl:.2f}"
        )

    def trigger_daily_pnl_threshold(self, daily_pnl: float):
        sign = "+" if daily_pnl > 0 else ""
        if abs(daily_pnl) >= 10000:
            self._send(
                "Daily P&L Milestone",
                f"Current Daily P&L has crossed +-10k threshold: Rs{sign}{daily_pnl:.2f}"
            )

    def trigger_drawdown_warning(self, dd_pct: float):
        if dd_pct > 1.5:
            self._send(
                "Drawdown Warning",
                f"Current drawdown is {dd_pct:.2f}% (exceeds 1.5% threshold)."
            )

    def trigger_weekly_memo(self, summary_text: str):
        self._send("Weekly Memo Generated", summary_text)
