"""
Position Monitor — tracks open positions against live prices.

Handles:
- Periodic price updates
- SL/target tracking
- Trailing stop logic
- Time-based exits (market close)
- P&L reporting

Usage:
    from engine.position_monitor import PositionMonitor
    monitor = PositionMonitor(paper_engine)
    monitor.check_and_report()
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class PositionMonitor:
    """
    Monitors open positions and manages exits based on live prices.
    """

    def __init__(self, paper_engine=None, 
                 trail_trigger_pct: float = 30.0,
                 trail_distance_pct: float = 15.0,
                 market_close_time: str = "15:25"):
        """
        Args:
            paper_engine: PaperTradingEngine instance.
            trail_trigger_pct: % profit to activate trailing stop.
            trail_distance_pct: % from peak to trail at.
            market_close_time: Time to force-close all positions.
        """
        self.engine = paper_engine
        self.trail_trigger_pct = trail_trigger_pct
        self.trail_distance_pct = trail_distance_pct
        self.market_close_time = market_close_time
        self._trail_peaks = {}  # position_id -> max premium seen

    def check_positions(self, current_prices: dict = None,
                         current_time: str = None) -> dict:
        """
        Check all open positions and handle exits.
        
        Args:
            current_prices: Dict mapping symbol -> current premium.
            current_time: Current time "HH:MM". If None, uses system time.
            
        Returns:
            Dict with position statuses and any exits triggered.
        """
        if self.engine is None:
            return {"error": "No paper engine configured"}
        
        if current_time is None:
            current_time = datetime.now().strftime("%H:%M")
        
        # Time-based force close
        if current_time >= self.market_close_time:
            closed = self.engine.close_all(current_prices, reason="market_close")
            return {
                "action": "market_close",
                "closed_count": len(closed),
                "closed": closed,
                "time": current_time,
            }
        
        # Update prices and check SL/target
        exits = []
        if current_prices:
            exits = self.engine.update_prices(current_prices)
        
        # Check trailing stops on remaining positions
        trail_exits = self._check_trailing_stops(current_prices)
        exits.extend(trail_exits)
        
        # Build status report
        positions = []
        for pos in self.engine.open_positions:
            entry = pos.entry_premium
            current = pos.current_premium
            
            if pos.direction == "BUY":
                pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0
            else:
                pnl_pct = ((entry - current) / entry * 100) if entry > 0 else 0
            
            status = {
                "id": pos.id,
                "symbol": f"{int(pos.strike)}{pos.option_type}",
                "direction": pos.direction,
                "entry": pos.entry_premium,
                "current": pos.current_premium,
                "sl": pos.stop_loss,
                "target": pos.target,
                "pnl": round(pos.unrealized_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "max_seen": pos.max_premium,
                "min_seen": pos.min_premium,
                "status": "HOLDING",
            }
            
            # Distance to SL and target
            if pos.direction == "BUY":
                status["sl_distance_pct"] = round(
                    (current - pos.stop_loss) / current * 100, 1
                ) if current > 0 else 0
                status["target_distance_pct"] = round(
                    (pos.target - current) / current * 100, 1
                ) if current > 0 else 0
            
            positions.append(status)
        
        return {
            "time": current_time,
            "open_count": len(self.engine.open_positions),
            "positions": positions,
            "exits_triggered": exits,
            "daily_pnl": round(self.engine.daily_pnl, 2),
            "unrealized_pnl": round(
                sum(p.unrealized_pnl for p in self.engine.open_positions), 2
            ),
        }

    def _check_trailing_stops(self, current_prices: dict = None) -> list:
        """
        Check and execute trailing stop exits.
        
        Trailing stop activates when profit exceeds trail_trigger_pct,
        then trails at trail_distance_pct from peak.
        """
        exits = []
        
        for pos in list(self.engine.open_positions):
            if pos.entry_premium <= 0:
                continue
            
            # Track peak premium
            if pos.id not in self._trail_peaks:
                self._trail_peaks[pos.id] = pos.entry_premium
            
            if pos.direction == "BUY":
                if pos.current_premium > self._trail_peaks.get(pos.id, 0):
                    self._trail_peaks[pos.id] = pos.current_premium
                
                peak = self._trail_peaks[pos.id]
                profit_pct = (peak - pos.entry_premium) / pos.entry_premium * 100
                
                if profit_pct >= self.trail_trigger_pct:
                    trail_level = peak * (1 - self.trail_distance_pct / 100)
                    
                    if pos.current_premium <= trail_level:
                        result = self.engine._close_position(
                            pos, pos.current_premium, "trailing_stop"
                        )
                        exits.append(result)
                        logger.info(
                            f"Trail stop hit: {pos.id} | "
                            f"Peak: Rs{peak:.2f} -> Current: Rs{pos.current_premium:.2f}"
                        )
        
        return exits

    def get_position_report(self) -> str:
        """Generate human-readable position report."""
        if not self.engine or not self.engine.open_positions:
            return "No open positions."
        
        lines = [
            f"📊 PAPER PORTFOLIO — {datetime.now().strftime('%H:%M')}",
            f"{'='*50}",
        ]
        
        total_unrealized = 0
        
        for pos in self.engine.open_positions:
            pnl = pos.unrealized_pnl
            total_unrealized += pnl
            
            emoji = "🟢" if pnl >= 0 else "🔴"
            
            lines.append(
                f"{emoji} {pos.direction} {int(pos.strike)}{pos.option_type} "
                f"({pos.lots}L)\n"
                f"   Entry: Rs{pos.entry_premium:.2f} -> "
                f"Current: Rs{pos.current_premium:.2f} "
                f"[P&L: Rs{pnl:,.2f}]\n"
                f"   SL: Rs{pos.stop_loss:.2f} | "
                f"Target: Rs{pos.target:.2f}"
            )
        
        lines.append(f"{'='*50}")
        lines.append(f"Unrealized: Rs{total_unrealized:,.2f}")
        lines.append(f"Day Realized: Rs{self.engine.daily_pnl:,.2f}")
        lines.append(f"Capital: Rs{self.engine.current_capital:,.2f}")
        
        return "\n".join(lines)
