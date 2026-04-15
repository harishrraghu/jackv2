"""
Journal Analyzer — reads past journal entries and extracts patterns.
Runs weekly (or on-demand) to compute:
- Conditional win rates by regime, day, ATR bucket, RSI range
- Confidence calibration (predicted vs actual)
- Degrading pattern detection
- Weekly improvement memo
"""

import json
import os
import glob
from collections import defaultdict
import numpy as np


class JournalAnalyzer:
    """Analyze journal entries to extract patterns and suggest improvements."""

    def __init__(self, journal_dir: str = "journal/logs/"):
        self.journal_dir = journal_dir

    def load_entries(self, n_days: int = None) -> list[dict]:
        """Load journal entries, optionally limited to last N days."""
        files = sorted(glob.glob(os.path.join(self.journal_dir, "2*.json")))
        if n_days:
            files = files[-n_days:]

        entries = []
        for f in files:
            try:
                with open(f) as fh:
                    entries.append(json.load(fh))
            except Exception:
                continue
        return entries

    def compute_conditional_win_rates(self, entries: list[dict]) -> dict:
        """
        Compute win rates broken down by:
        - Day of week
        - Regime
        - ATR bucket (low/medium/high)
        - RSI bucket (oversold/neutral/overbought)
        - Confidence bucket (low/medium/high)
        """
        buckets = {
            "by_day": defaultdict(lambda: {"wins": 0, "total": 0, "pnls": []}),
            "by_regime": defaultdict(lambda: {"wins": 0, "total": 0, "pnls": []}),
            "by_atr_bucket": defaultdict(lambda: {"wins": 0, "total": 0, "pnls": []}),
            "by_rsi_bucket": defaultdict(lambda: {"wins": 0, "total": 0, "pnls": []}),
            "by_confidence": defaultdict(lambda: {"wins": 0, "total": 0, "pnls": []}),
        }

        for entry in entries:
            day = entry.get("day_of_week", "Unknown")
            regime = entry.get("morning_scan", {}).get("regime", "normal")
            atr = entry.get("morning_scan", {}).get("atr")
            rsi = entry.get("morning_scan", {}).get("rsi_daily")

            # Classify ATR bucket
            if atr is not None:
                if atr < 200:
                    atr_bucket = "low"
                elif atr < 500:
                    atr_bucket = "medium"
                else:
                    atr_bucket = "high"
            else:
                atr_bucket = "unknown"

            # Classify RSI bucket
            if rsi is not None:
                if rsi < 30:
                    rsi_bucket = "oversold"
                elif rsi > 70:
                    rsi_bucket = "overbought"
                else:
                    rsi_bucket = "neutral"
            else:
                rsi_bucket = "unknown"

            for trade in entry.get("trades", []):
                pnl = trade.get("net_pnl", 0)
                is_win = pnl > 0

                for bucket_name, key in [
                    ("by_day", day),
                    ("by_regime", regime),
                    ("by_atr_bucket", atr_bucket),
                    ("by_rsi_bucket", rsi_bucket),
                ]:
                    buckets[bucket_name][key]["total"] += 1
                    buckets[bucket_name][key]["pnls"].append(pnl)
                    if is_win:
                        buckets[bucket_name][key]["wins"] += 1

        # Compute win rates
        result = {}
        for bucket_type, data in buckets.items():
            result[bucket_type] = {}
            for key, vals in data.items():
                total = vals["total"]
                result[bucket_type][key] = {
                    "trades": total,
                    "win_rate": round(vals["wins"] / total * 100, 1) if total > 0 else 0,
                    "avg_pnl": round(np.mean(vals["pnls"]), 2) if vals["pnls"] else 0,
                    "total_pnl": round(sum(vals["pnls"]), 2),
                }

        return result

    def calibrate_confidence(self, entries: list[dict]) -> dict:
        """
        Check if confidence scores predict actual win rates.

        Buckets: 0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8-1.0
        """
        conf_buckets = defaultdict(lambda: {"wins": 0, "total": 0})

        for entry in entries:
            for trade in entry.get("trades", []):
                conf = trade.get("confidence", 0.5)
                pnl = trade.get("net_pnl", 0)

                if conf < 0.6:
                    bucket = "0.50-0.60"
                elif conf < 0.7:
                    bucket = "0.60-0.70"
                elif conf < 0.8:
                    bucket = "0.70-0.80"
                else:
                    bucket = "0.80-1.00"

                conf_buckets[bucket]["total"] += 1
                if pnl > 0:
                    conf_buckets[bucket]["wins"] += 1

        result = {}
        for bucket, data in sorted(conf_buckets.items()):
            total = data["total"]
            actual_wr = data["wins"] / total * 100 if total > 0 else 0
            # Expected WR is the midpoint of the confidence range
            midpoints = {
                "0.50-0.60": 55,
                "0.60-0.70": 65,
                "0.70-0.80": 75,
                "0.80-1.00": 90,
            }
            expected = midpoints.get(bucket, 50)

            result[bucket] = {
                "trades": total,
                "actual_win_rate": round(actual_wr, 1),
                "expected_win_rate": expected,
                "calibration_error": round(actual_wr - expected, 1),
                "well_calibrated": abs(actual_wr - expected) < 10,
            }

        return result

    def detect_degrading_patterns(self, entries: list[dict], window: int = 20) -> list[str]:
        """
        Detect patterns where recent performance is degrading.

        Compares last `window` entries to the full history.
        """
        if len(entries) < window * 2:
            return ["Insufficient data for degradation analysis"]

        recent = entries[-window:]
        older = entries[:-window]

        warnings = []

        # Compare overall win rates
        recent_trades = [t for e in recent for t in e.get("trades", [])]
        older_trades = [t for e in older for t in e.get("trades", [])]

        if recent_trades and older_trades:
            recent_wr = (
                sum(1 for t in recent_trades if t.get("net_pnl", 0) > 0)
                / len(recent_trades) * 100
            )
            older_wr = (
                sum(1 for t in older_trades if t.get("net_pnl", 0) > 0)
                / len(older_trades) * 100
            )

            if recent_wr < older_wr - 10:
                warnings.append(
                    f"WIN RATE DEGRADING: Recent {window}d win rate {recent_wr:.0f}% "
                    f"vs historical {older_wr:.0f}% "
                    f"(drop of {older_wr - recent_wr:.0f} percentage points)"
                )

        # Check if average P&L is declining
        if recent_trades and older_trades:
            recent_avg = np.mean([t.get("net_pnl", 0) for t in recent_trades])
            older_avg = np.mean([t.get("net_pnl", 0) for t in older_trades])

            if recent_avg < older_avg * 0.5:
                warnings.append(
                    f"AVG P&L DEGRADING: Recent avg Rs{recent_avg:,.0f} "
                    f"vs historical avg Rs{older_avg:,.0f}"
                )

        if not warnings:
            warnings.append(
                "No degradation detected — system performing within historical norms"
            )

        return warnings

    def generate_weekly_memo(self, n_days: int = 5) -> dict:
        """
        Generate a weekly improvement memo.

        Returns structured insights and recommendations.
        """
        entries = self.load_entries(n_days=n_days)
        all_entries = self.load_entries()

        if not entries:
            return {"error": "no_entries"}

        conditional = self.compute_conditional_win_rates(all_entries)
        calibration = self.calibrate_confidence(all_entries)
        degradation = self.detect_degrading_patterns(all_entries)

        # Generate recommendations
        recommendations = []

        # Check day-of-week performance
        for day, stats in conditional.get("by_day", {}).items():
            if stats["trades"] >= 10 and stats["win_rate"] < 40:
                recommendations.append(
                    f"Consider reducing exposure on {day}s — "
                    f"win rate is only {stats['win_rate']}% across {stats['trades']} trades"
                )

        # Check regime performance
        for regime, stats in conditional.get("by_regime", {}).items():
            if stats["trades"] >= 5 and stats["avg_pnl"] < -5000:
                recommendations.append(
                    f"The '{regime}' regime is losing money "
                    f"(avg Rs{stats['avg_pnl']:,.0f}/trade). "
                    f"Consider blocking trades in this regime."
                )

        # Confidence calibration
        for bucket, cal in calibration.items():
            if not cal["well_calibrated"] and cal["trades"] >= 10:
                if cal["calibration_error"] < -15:
                    recommendations.append(
                        f"Confidence {bucket} is OVERCONFIDENT: "
                        f"predicted ~{cal['expected_win_rate']}% WR "
                        f"but actual is {cal['actual_win_rate']}%. "
                        f"Reduce confidence scores for this bucket."
                    )

        memo = {
            "period": f"Last {n_days} trading days",
            "entries_analyzed": len(entries),
            "trades_this_period": sum(len(e.get("trades", [])) for e in entries),
            "conditional_win_rates": conditional,
            "confidence_calibration": calibration,
            "degradation_warnings": degradation,
            "recommendations": (
                recommendations if recommendations
                else ["No specific recommendations — continue current approach"]
            ),
        }

        # Write memo
        memo_path = os.path.join(self.journal_dir, "weekly_memo.json")
        os.makedirs(os.path.dirname(memo_path), exist_ok=True)
        with open(memo_path, "w") as f:
            json.dump(memo, f, indent=2, default=str)

        return memo
