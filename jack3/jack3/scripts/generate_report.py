"""
Jack v3 — Simulation Report Generator.

Reads sim_results/simulation_results.json and prints a complete
human-readable report: per-day breakdown, trade log, and summary stats.

Usage:
  python scripts/generate_report.py
  python scripts/generate_report.py --json sim_results/simulation_results.json
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pct(n, d):
    return f"{n/d*100:.1f}%" if d else "N/A"


def sign(v):
    return f"+{v:,.0f}" if v >= 0 else f"{v:,.0f}"


def bar(v, max_v, width=20, fill="+", empty="-"):
    if max_v == 0:
        return empty * width
    filled = min(width, int(abs(v) / max_v * width))
    return (fill * filled).ljust(width, empty)


def generate_report(results: list) -> str:
    lines = []

    def h1(t): lines.append("\n" + "=" * 70); lines.append(f"  {t}"); lines.append("=" * 70)
    def h2(t): lines.append(f"\n--- {t} ---")
    def row(*cols): lines.append("  ".join(str(c).ljust(w) for c, w in cols))

    # ── HEADER ──
    h1("JACK v3  |  BankNifty AI Paper Trading  |  1-Month Simulation Report")

    if not results:
        lines.append("No results found.")
        return "\n".join(lines)

    dates = [r["date"] for r in results]
    lines.append(f"  Period : {dates[0]}  to  {dates[-1]}")
    lines.append(f"  Days   : {len(results)} trading days")
    lines.append(f"  Model  : gemini-3-flash via local proxy")
    lines.append(f"  Mode   : Paper (no real orders placed)")

    # ── AGGREGATE STATS ──
    total_pnl     = sum(r["daily_pnl"] for r in results)
    total_trades  = sum(r["num_trades"] for r in results)
    total_wins    = sum(r["wins"] for r in results)
    total_losses  = total_trades - total_wins
    days_profit   = sum(1 for r in results if r["daily_pnl"] > 0)
    days_loss     = sum(1 for r in results if r["daily_pnl"] < 0)
    days_flat     = sum(1 for r in results if r["daily_pnl"] == 0 and r["num_trades"] == 0)
    win_rate      = total_wins / total_trades * 100 if total_trades else 0

    all_trades = [t for r in results for t in r.get("trades", [])]
    winning_trades = [t for t in all_trades if t.get("net_pnl", 0) > 0]
    losing_trades  = [t for t in all_trades if t.get("net_pnl", 0) <= 0]
    avg_win  = sum(t["net_pnl"] for t in winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(t["net_pnl"] for t in losing_trades) / len(losing_trades) if losing_trades else 0
    best_day  = max(results, key=lambda r: r["daily_pnl"])
    worst_day = min(results, key=lambda r: r["daily_pnl"])

    # Max drawdown
    peak = 0
    max_dd = 0
    running = 0
    for r in results:
        running += r["daily_pnl"]
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # Profit factor
    gross_profit = sum(t["net_pnl"] for t in winning_trades)
    gross_loss   = abs(sum(t["net_pnl"] for t in losing_trades))
    pf = gross_profit / gross_loss if gross_loss else float("inf")

    # Thesis accuracy
    thesis_results = []
    for r in results:
        if not r.get("trades"):
            continue
        thesis = r["thesis_direction"]
        move = r["day_move_pts"]
        if (thesis == "BULLISH" and move > 50) or (thesis == "BEARISH" and move < -50):
            thesis_results.append("correct")
        elif (thesis == "BULLISH" and move < -50) or (thesis == "BEARISH" and move > 50):
            thesis_results.append("wrong")
        else:
            thesis_results.append("neutral")
    thesis_acc = thesis_results.count("correct") / len(thesis_results) * 100 if thesis_results else 0

    # Avg trades per active day
    active_days = [r for r in results if r["num_trades"] > 0]
    avg_trades_active = total_trades / len(active_days) if active_days else 0

    h2("PERFORMANCE SUMMARY")
    lines.append(f"  Total P&L          : Rs.{total_pnl:>10,.0f}  {sign(total_pnl)}")
    lines.append(f"  Total Trades       : {total_trades:>10}")
    lines.append(f"  Win Rate           : {win_rate:>9.1f}%  ({total_wins}W / {total_losses}L)")
    lines.append(f"  Avg Win            : Rs.{avg_win:>10,.0f}")
    lines.append(f"  Avg Loss           : Rs.{avg_loss:>10,.0f}")
    lines.append(f"  Profit Factor      : {pf:>10.2f}  (> 1.5 = good)")
    lines.append(f"  Max Drawdown       : Rs.{max_dd:>10,.0f}")
    lines.append(f"  Best Day           : Rs.{best_day['daily_pnl']:>10,.0f}  ({best_day['date']})")
    lines.append(f"  Worst Day          : Rs.{worst_day['daily_pnl']:>10,.0f}  ({worst_day['date']})")
    lines.append(f"  Profitable Days    : {days_profit:>10}  / {len(results)}")
    lines.append(f"  Loss Days          : {days_loss:>10}")
    lines.append(f"  Flat Days (no trade): {days_flat:>9}")
    lines.append(f"  Thesis Accuracy    : {thesis_acc:>9.1f}%  (direction vs actual move)")
    lines.append(f"  Avg Trades/Active  : {avg_trades_active:>9.1f}")

    # ── DAILY BREAKDOWN ──
    h2("DAY-BY-DAY BREAKDOWN")
    header = (
        f"{'Date':<12} {'Thesis':<8} {'Conf':>5} "
        f"{'Tr':>3} {'W':>3} "
        f"{'Day Move':>9} {'P&L':>10} {'Cumulative':>12}  Chart"
    )
    lines.append("  " + header)
    lines.append("  " + "-" * len(header))

    max_abs_pnl = max(abs(r["daily_pnl"]) for r in results) or 1

    for r in results:
        t = r["thesis_direction"][0]  # B/N/E
        conf = f"{r['thesis_confidence']:.0%}"
        move = r["day_move_pts"]
        move_str = f"{move:+.0f}pts"
        pnl = r["daily_pnl"]
        cum = r["cumulative_pnl"]
        chart = bar(pnl, max_abs_pnl, width=15, fill="+" if pnl >= 0 else "-")
        lines.append(
            f"  {r['date']:<12} {t:<8} {conf:>5} "
            f"{r['num_trades']:>3} {r['wins']:>3} "
            f"{move_str:>9} Rs.{pnl:>8,.0f} Rs.{cum:>10,.0f}  [{chart}]"
        )

    # ── TRADE LOG ──
    h2("COMPLETE TRADE LOG")
    if not all_trades:
        lines.append("  No trades executed.")
    else:
        trade_header = (
            f"{'Date':<12} {'Dir':<7} {'Entry':>7} {'Exit':>7} "
            f"{'Move':>7} {'P&L':>9} {'Exit Reason':<22} {'Thesis':<8}"
        )
        lines.append("  " + trade_header)
        lines.append("  " + "-" * len(trade_header))
        for r in results:
            for t in r.get("trades", []):
                ep = t.get("entry_price", 0)
                xp = t.get("exit_price", 0)
                dir_ = t.get("direction", "?")
                move_t = (xp - ep) * (1 if dir_ == "LONG" else -1)
                pnl_t = t.get("net_pnl", 0)
                reason = t.get("exit_reason", "?")[:20]
                thesis_d = r["thesis_direction"][0]
                lines.append(
                    f"  {r['date']:<12} {dir_:<7} {ep:>7.0f} {xp:>7.0f} "
                    f"{move_t:>+6.0f}p Rs.{pnl_t:>7,.0f} {reason:<22} {thesis_d:<8}"
                )

    # ── EXIT REASON BREAKDOWN ──
    h2("EXIT REASON ANALYSIS")
    reasons = {}
    for t in all_trades:
        r = t.get("exit_reason", "unknown")
        reasons.setdefault(r, {"count": 0, "total_pnl": 0, "wins": 0})
        reasons[r]["count"] += 1
        reasons[r]["total_pnl"] += t.get("net_pnl", 0)
        if t.get("net_pnl", 0) > 0:
            reasons[r]["wins"] += 1

    lines.append(f"  {'Reason':<25} {'Count':>6} {'Win%':>6} {'Avg P&L':>10} {'Total P&L':>12}")
    lines.append(f"  {'-'*65}")
    for reason, stats in sorted(reasons.items(), key=lambda x: -x[1]["count"]):
        wr = pct(stats["wins"], stats["count"])
        avg = stats["total_pnl"] / stats["count"]
        lines.append(
            f"  {reason:<25} {stats['count']:>6} {wr:>6}  Rs.{avg:>8,.0f}  Rs.{stats['total_pnl']:>9,.0f}"
        )

    # ── DIRECTION ANALYSIS ──
    h2("LONG vs SHORT ANALYSIS")
    longs  = [t for t in all_trades if t.get("direction") == "LONG"]
    shorts = [t for t in all_trades if t.get("direction") == "SHORT"]

    for label, trades_g in [("LONG ", longs), ("SHORT", shorts)]:
        if not trades_g:
            lines.append(f"  {label}: No trades")
            continue
        w = sum(1 for t in trades_g if t.get("net_pnl", 0) > 0)
        pnl_g = sum(t.get("net_pnl", 0) for t in trades_g)
        avg_g = pnl_g / len(trades_g)
        lines.append(
            f"  {label}: {len(trades_g)} trades | {pct(w, len(trades_g))} WR | "
            f"Avg Rs.{avg_g:,.0f} | Total Rs.{pnl_g:,.0f}"
        )

    # ── THESIS ACCURACY ──
    h2("THESIS vs MARKET REALITY")
    lines.append(f"  {'Date':<12} {'Thesis':<8} {'Actual Move':>12} {'Outcome':<10}")
    lines.append(f"  {'-'*45}")
    for r in results:
        move = r["day_move_pts"]
        t = r["thesis_direction"]
        if t == "BULLISH":
            outcome = "Correct" if move > 50 else ("Wrong" if move < -50 else "Neutral")
        elif t == "BEARISH":
            outcome = "Correct" if move < -50 else ("Wrong" if move > 50 else "Neutral")
        else:
            outcome = "N/A"
        lines.append(f"  {r['date']:<12} {t:<8} {move:>+10.0f}pts  {outcome:<10}")

    # ── AI LESSONS LEARNED ──
    h2("AI LESSONS LEARNED (from nightly reviews)")
    lessons_seen = set()
    lesson_count = 0
    for r in results:
        for t in r.get("trades", []):
            review = t.get("ai_review", {})
            lesson = review.get("lesson", "")
            if lesson and lesson not in lessons_seen:
                lessons_seen.add(lesson)
                lesson_count += 1
                lines.append(f"  {lesson_count:>2}. [{r['date']}] {lesson}")

    if not lessons_seen:
        lines.append("  No AI lessons recorded (post-trade review may have been skipped).")

    # ── EQUITY CURVE ASCII ──
    h2("EQUITY CURVE (cumulative P&L)")
    equity = [0]
    for r in results:
        equity.append(equity[-1] + r["daily_pnl"])

    max_eq = max(equity)
    min_eq = min(equity)
    range_eq = max_eq - min_eq or 1
    height = 10
    width = len(dates)

    # Build grid
    grid = [[" "] * width for _ in range(height)]
    for i, val in enumerate(equity[1:]):
        row_idx = int((max_eq - val) / range_eq * (height - 1))
        row_idx = max(0, min(height - 1, row_idx))
        grid[row_idx][i] = "+" if val >= 0 else "-"

    lines.append(f"  Max: Rs.{max_eq:,.0f}")
    for row in grid:
        lines.append("  |" + "".join(row) + "|")
    lines.append(f"  Min: Rs.{min_eq:,.0f}")
    pad = max(0, width // 2 - len(dates[0]))
    lines.append(f"  {'':3}{dates[0]}{' ' * pad}{dates[-1]}")

    # ── VERDICT ──
    h2("VERDICT")
    if pf >= 1.5 and win_rate >= 50:
        verdict = "PROMISING - Profitable with decent win rate. Needs more data to confirm edge."
    elif total_pnl > 0 and pf >= 1.0:
        verdict = "MARGINAL - Profitable but low profit factor. Strategy needs tuning."
    elif total_pnl <= 0 and total_trades > 0:
        verdict = "UNPROFITABLE - System lost money. Review entry conditions and stop placement."
    elif total_trades == 0:
        verdict = "NO TRADES — System was too conservative. Review entry thresholds."
    else:
        verdict = "MIXED — Review individual trade quality."

    lines.append(f"  {verdict}")
    lines.append(f"")
    lines.append(f"  Total P&L    : Rs.{total_pnl:,.0f} over {len(results)} trading days")
    lines.append(f"  Win Rate     : {win_rate:.1f}%")
    lines.append(f"  Profit Factor: {pf:.2f}")
    lines.append(f"  Max Drawdown : Rs.{max_dd:,.0f}")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="sim_results/simulation_results.json")
    args = parser.parse_args()

    if not os.path.exists(args.json):
        print(f"Results file not found: {args.json}")
        sys.exit(1)

    with open(args.json) as f:
        results = json.load(f)

    report = generate_report(results)
    print(report)

    # Save report
    report_path = args.json.replace(".json", "_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
