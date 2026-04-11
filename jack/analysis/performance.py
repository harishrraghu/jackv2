"""
Performance analytics — comprehensive backtest metrics.

Computes returns, risk metrics, Sharpe/Sortino ratios, drawdown analysis,
per-strategy breakdowns, day-of-week analysis, and monthly heatmap data.
"""

import math
from typing import Optional
from collections import defaultdict

import numpy as np
from tabulate import tabulate


class PerformanceAnalyzer:
    """Comprehensive performance analysis of backtest results."""

    def __init__(self, trade_log: list[dict], initial_capital: float):
        self.trades = trade_log
        self.initial_capital = initial_capital
        self._results = None

    def compute_all(self) -> dict:
        """Compute all performance metrics."""
        if not self.trades:
            return self._empty_results()

        pnls = [t.get("net_pnl", 0) for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_trades = len(self.trades)
        win_count = len(wins)
        loss_count = len(losses)
        net_pnl = sum(pnls)

        win_rate = win_count / total_trades if total_trades > 0 else 0
        avg_win = float(np.mean(wins)) if wins else 0
        avg_loss = float(np.mean(losses)) if losses else 0
        sum_wins = sum(wins) if wins else 0
        sum_losses = abs(sum(losses)) if losses else 0

        # Equity curve
        equity = [self.initial_capital]
        for pnl in pnls:
            equity.append(equity[-1] + pnl)

        # Drawdown
        peak = self.initial_capital
        max_dd_abs = 0
        max_dd_pct = 0
        dd_start = 0
        max_dd_duration = 0
        current_dd_start = 0
        in_drawdown = False
        drawdowns_sq = []

        for i, eq in enumerate(equity):
            if eq > peak:
                peak = eq
                if in_drawdown:
                    duration = i - current_dd_start
                    max_dd_duration = max(max_dd_duration, duration)
                    in_drawdown = False
            else:
                dd = peak - eq
                dd_pct = dd / peak * 100 if peak > 0 else 0
                drawdowns_sq.append(dd_pct ** 2)
                if dd > max_dd_abs:
                    max_dd_abs = dd
                    max_dd_pct = dd_pct
                if not in_drawdown:
                    current_dd_start = i
                    in_drawdown = True

        # Trading days estimation
        dates = set()
        for t in self.trades:
            d = t.get("entry_date") or t.get("exit_date")
            if d:
                dates.add(str(d))
        trading_days = max(len(dates), 1)

        # Annualized return
        years = trading_days / 252
        total_return_pct = net_pnl / self.initial_capital * 100
        ann_return = ((1 + net_pnl / self.initial_capital) ** (1 / max(years, 0.01)) - 1) * 100

        # Daily returns for Sharpe
        daily_returns = self._compute_daily_returns()
        risk_free_daily = 0.065 / 252

        # sharpe_monthly (true Sharpe)
        monthly_returns = self._compute_monthly_returns()
        risk_free_monthly = 0.065 / 12
        if len(monthly_returns) > 1:
            mean_m_ret = np.mean(monthly_returns)
            std_m_ret = np.std(monthly_returns, ddof=1)
            sharpe_monthly = ((mean_m_ret - risk_free_monthly) / std_m_ret * math.sqrt(12)
                              if std_m_ret > 0 else 0)
                              
            downside_m = [r for r in monthly_returns if r < risk_free_monthly]
            dd_std_m = np.std(downside_m, ddof=1) if len(downside_m) > 1 else np.std(monthly_returns, ddof=1)
            sortino_monthly = ((mean_m_ret - risk_free_monthly) / dd_std_m * math.sqrt(12)
                               if dd_std_m > 0 else 0)
        else:
            sharpe_monthly = 0
            sortino_monthly = 0

        # sharpe_trade_days
        daily_trade_returns = [r for r in daily_returns if r != 0]
        if len(daily_trade_returns) > 1:
            mean_trade = np.mean(daily_trade_returns)
            std_trade = np.std(daily_trade_returns, ddof=1)
            sharpe_trade_days = ((mean_trade - risk_free_daily) / std_trade * math.sqrt(252)
                                 if std_trade > 0 else 0)
        else:
            sharpe_trade_days = 0

        # sharpe_inflated_DO_NOT_USE
        if len(daily_returns) > 1:
            mean_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns, ddof=1)
            sharpe_inflated = ((mean_ret - risk_free_daily) / std_ret * math.sqrt(252)
                               if std_ret > 0 else 0)
        else:
            sharpe_inflated = 0

        # Ulcer index
        ulcer = math.sqrt(np.mean(drawdowns_sq)) if drawdowns_sq else 0

        # Calmar
        calmar = ann_return / max_dd_pct if max_dd_pct > 0 else 0
        
        # Recovery Factor
        recovery_factor = net_pnl / max_dd_abs if max_dd_abs > 0 else 0

        # Trade durations (placeholder — needs time parsing)
        avg_duration = 0

        # By strategy
        by_strategy = self._compute_by_strategy()
        by_day = self._compute_by_day()
        by_month = self._compute_by_month()

        self._results = {
            # Returns
            "total_return_pct": round(total_return_pct, 2),
            "total_return_abs": round(net_pnl, 2),
            "annualized_return_pct": round(ann_return, 2),
            # Win/Loss
            "total_trades": total_trades,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate_pct": round(win_rate * 100, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "largest_win": round(max(pnls), 2) if pnls else 0,
            "largest_loss": round(min(pnls), 2) if pnls else 0,
            "avg_win_loss_ratio": round(abs(avg_win / avg_loss), 3) if avg_loss != 0 else float('inf'),
            "profit_factor": round(sum_wins / sum_losses, 3) if sum_losses > 0 else float('inf'),
            "expectancy": round(win_rate * avg_win + (1 - win_rate) * avg_loss, 2),
            # Risk
            "max_drawdown_pct": round(max_dd_pct, 2),
            "max_drawdown_abs": round(max_dd_abs, 2),
            "max_drawdown_duration_days": max_dd_duration,
            "calmar_ratio": round(calmar, 3),
            "recovery_factor": round(recovery_factor, 3),
            "ulcer_index": round(ulcer, 3),
            # Risk-adjusted
            "sharpe_monthly": round(sharpe_monthly, 3),
            "sortino_monthly": round(sortino_monthly, 3),
            "sharpe_trade_days": round(sharpe_trade_days, 3),
            "sharpe_inflated_DO_NOT_USE": round(sharpe_inflated, 3),
            "sharpe_ratio": round(sharpe_monthly, 3),  # Point to monthly as default
            # Time
            "avg_trade_duration_minutes": avg_duration,
            "trades_per_day": round(total_trades / trading_days, 2),
            # Breakdowns
            "by_strategy": by_strategy,
            "by_day": by_day,
            "by_month": by_month,
            # Curves
            "equity_curve": list(zip(range(len(equity)), equity)),
            "daily_returns": daily_returns,
        }

        return self._results

    def _compute_daily_returns(self) -> list[float]:
        """Compute daily return percentages."""
        daily_pnl = defaultdict(float)
        for t in self.trades:
            d = t.get("exit_date") or t.get("entry_date") or "unknown"
            daily_pnl[str(d)] += t.get("net_pnl", 0)

        capital = self.initial_capital
        returns = []
        for d in sorted(daily_pnl.keys()):
            ret = daily_pnl[d] / capital if capital > 0 else 0
            returns.append(ret)
            capital += daily_pnl[d]

        return returns

    def _compute_monthly_returns(self) -> list[float]:
        """Compute monthly return percentages."""
        monthly_pnl = defaultdict(float)
        dates = []
        for t in self.trades:
            d = t.get("exit_date") or t.get("entry_date")
            if d:
                dates.append(str(d))
                monthly_pnl[str(d)[:7]] += t.get("net_pnl", 0)

        if not dates:
            return []

        import pandas as pd
        start_month = min(dates)[:7]
        end_month = max(dates)[:7]
        
        all_months = pd.date_range(start=f"{start_month}-01", end=f"{end_month}-01", freq='MS')
        month_keys = [d.strftime('%Y-%m') for d in all_months]
        
        capital = self.initial_capital
        returns = []
        for m in month_keys:
            pnl = monthly_pnl.get(m, 0.0)
            ret = pnl / capital if capital > 0 else 0
            returns.append(ret)
            capital += pnl

        return returns

    def _compute_by_strategy(self) -> dict:
        """Compute per-strategy breakdown."""
        by_strat = defaultdict(lambda: {"trades": 0, "wins": 0, "pnls": []})
        for t in self.trades:
            s = t.get("strategy", "unknown")
            by_strat[s]["trades"] += 1
            pnl = t.get("net_pnl", 0)
            by_strat[s]["pnls"].append(pnl)
            if pnl > 0:
                by_strat[s]["wins"] += 1

        result = {}
        for s, data in by_strat.items():
            n = data["trades"]
            pnls = data["pnls"]
            result[s] = {
                "trades": n,
                "wins": data["wins"],
                "win_rate_pct": round(data["wins"] / n * 100, 1) if n > 0 else 0,
                "net_pnl": round(sum(pnls), 2),
                "avg_pnl": round(np.mean(pnls), 2) if pnls else 0,
                "profit_factor": self._calc_pf(pnls),
            }
        return result

    def _compute_by_day(self) -> dict:
        """Compute per-day-of-week breakdown."""
        by_day = defaultdict(lambda: {"trades": 0, "wins": 0, "pnls": []})
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

        for t in self.trades:
            d = t.get("entry_date")
            if d:
                try:
                    import pandas as pd
                    ts = pd.Timestamp(d)
                    day = ts.day_name()
                except Exception:
                    day = "Unknown"
            else:
                day = "Unknown"

            by_day[day]["trades"] += 1
            pnl = t.get("net_pnl", 0)
            by_day[day]["pnls"].append(pnl)
            if pnl > 0:
                by_day[day]["wins"] += 1

        result = {}
        for day in day_names:
            if day in by_day:
                n = by_day[day]["trades"]
                pnls = by_day[day]["pnls"]
                result[day] = {
                    "trade_count": n,
                    "win_rate": round(by_day[day]["wins"] / n * 100, 1) if n > 0 else 0,
                    "avg_pnl": round(np.mean(pnls), 2) if pnls else 0,
                    "net_pnl": round(sum(pnls), 2),
                }
        return result

    def _compute_by_month(self) -> dict:
        """Compute per-month breakdown."""
        by_month = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
        for t in self.trades:
            d = t.get("exit_date") or t.get("entry_date")
            if d:
                month_key = str(d)[:7]  # "YYYY-MM"
            else:
                month_key = "unknown"
            by_month[month_key]["trades"] += 1
            pnl = t.get("net_pnl", 0)
            by_month[month_key]["pnl"] += pnl
            if pnl > 0:
                by_month[month_key]["wins"] += 1

        result = {}
        for m in sorted(by_month.keys()):
            data = by_month[m]
            result[m] = {
                "net_pnl": round(data["pnl"], 2),
                "trade_count": data["trades"],
                "win_rate": round(data["wins"] / data["trades"] * 100, 1) if data["trades"] > 0 else 0,
            }
        return result

    def _calc_pf(self, pnls: list) -> float:
        """Calculate profit factor from list of P&Ls."""
        wins = sum(p for p in pnls if p > 0)
        losses = abs(sum(p for p in pnls if p <= 0))
        return round(wins / losses, 3) if losses > 0 else float('inf')

    def _empty_results(self) -> dict:
        """Return zeroed results when no trades exist."""
        return {
            "total_return_pct": 0, "total_return_abs": 0, "total_trades": 0,
            "win_rate_pct": 0, "sharpe_ratio": 0, "max_drawdown_pct": 0,
            "profit_factor": 0, "equity_curve": [], "by_strategy": {},
            "by_day": {}, "by_month": {},
        }

    def print_report(self) -> None:
        """Print a clean formatted report to stdout."""
        if self._results is None:
            self._results = self.compute_all()

        r = self._results
        print(f"\n{'='*60}")
        print("  PERFORMANCE REPORT")
        print(f"{'='*60}")

        print(f"\n  Total Trades: {r['total_trades']}")
        print(f"  Win Rate: {r['win_rate_pct']}%")
        print(f"  Net P&L: ₹{r['total_return_abs']:,.2f}")
        print(f"  Return: {r['total_return_pct']}%")
        print(f"  Sharpe (Monthly - Use This): {r['sharpe_monthly']}")
        print(f"  Sharpe (Trade Days Only): {r['sharpe_trade_days']}")
        print(f"  Sharpe (Inflated - DO NOT USE): {r['sharpe_inflated_DO_NOT_USE']}")
        print(f"  Sortino (Monthly): {r.get('sortino_monthly', 0)}")
        print(f"  Calmar Ratio: {r.get('calmar_ratio', 0)}")
        print(f"  Recovery Factor: {r.get('recovery_factor', 0)}")
        print(f"  Max DD: {r['max_drawdown_pct']}%")
        print(f"  Profit Factor: {r['profit_factor']}")
        print(f"  Expectancy: ₹{r['expectancy']:,.2f}")

        # Strategy breakdown
        if r.get("by_strategy"):
            print(f"\n  {'Strategy Breakdown':}")
            rows = []
            for s, data in r["by_strategy"].items():
                rows.append([
                    s, data["trades"], f"{data['win_rate_pct']}%",
                    f"₹{data['net_pnl']:,.0f}", data.get("profit_factor", "N/A"),
                ])
            print(tabulate(rows,
                           headers=["Strategy", "Trades", "Win%", "Net P&L", "PF"],
                           tablefmt="simple"))

        # Day of week
        if r.get("by_day"):
            print(f"\n  Day of Week:")
            rows = []
            for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
                if day in r["by_day"]:
                    d = r["by_day"][day]
                    rows.append([day, d["trade_count"], f"{d['win_rate']}%",
                                 f"₹{d['net_pnl']:,.0f}"])
            print(tabulate(rows,
                           headers=["Day", "Trades", "Win%", "Net P&L"],
                           tablefmt="simple"))

        print(f"\n{'='*60}")

    def export_json(self, path: str) -> None:
        """Export full results as JSON."""
        import json
        if self._results is None:
            self._results = self.compute_all()

        with open(path, "w") as f:
            json.dump(self._results, f, indent=2, default=str)


class BenchmarkComparison:
    """Compare Jack's performance against benchmarks."""

    def __init__(self, equity_curve: list, daily_data, initial_capital: float):
        self.equity_curve = equity_curve
        self.daily_data = daily_data
        self.initial_capital = initial_capital

    def buy_and_hold(self) -> dict:
        """Simulate buy-and-hold BANKNIFTY."""
        if self.daily_data is None or self.daily_data.empty:
            return {"total_return_pct": 0, "sharpe_ratio": 0, "max_drawdown_pct": 0}

        first_open = self.daily_data.iloc[0]["Open"]
        last_close = self.daily_data.iloc[-1]["Close"]
        ret = (last_close - first_open) / first_open * 100

        # Simple equity curve
        closes = self.daily_data["Close"].values
        eq = self.initial_capital * closes / first_open
        peak = eq[0]
        max_dd = 0
        for e in eq:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100
            max_dd = max(max_dd, dd)

        returns = np.diff(closes) / closes[:-1]
        sharpe = 0
        if len(returns) > 1:
            excess = returns - 0.065 / 252
            std = np.std(returns, ddof=1)
            if std > 0:
                sharpe = np.mean(excess) / std * math.sqrt(252)

        return {
            "total_return_pct": round(ret, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 3),
        }

    def compare_all(self) -> dict:
        """Run all benchmarks and compare."""
        bh = self.buy_and_hold()
        jack_final = self.equity_curve[-1][1] if self.equity_curve else self.initial_capital
        jack_ret = (jack_final - self.initial_capital) / self.initial_capital * 100

        return {
            "jack": {"return_pct": round(jack_ret, 2)},
            "buy_hold": bh,
        }

    def print_comparison(self) -> None:
        """Print formatted comparison."""
        comp = self.compare_all()
        print(f"\n{'='*60}")
        print("  BENCHMARK COMPARISON")
        print(f"{'='*60}")
        for name, metrics in comp.items():
            print(f"\n  {name.upper()}:")
            for k, v in metrics.items():
                print(f"    {k}: {v}")
