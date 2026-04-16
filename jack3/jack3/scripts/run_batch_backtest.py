"""
Jack v3 - Batch AI Backtest (Fast Mode)
========================================
Zero tick-by-tick simulation. Zero per-candle API calls.

How it works:
  1. Load CSV candle data for the date range
  2. Compute indicators (RSI, EMA, VWAP, ATR) for each candle
  3. For each batch of --batch-size days:
       - Build one giant prompt with all candles + pre-date momentum context
       - Make ONE AI call -> get full day-by-day analysis + trade decisions
  4. Save AI analysis to journal/JSON files
  5. Print a final performance summary

Result: 18 days = 4 API calls (5 days each), runs in ~60 seconds.

Usage:
  python scripts/run_batch_backtest.py --csv data/banknifty_1month.csv
  python scripts/run_batch_backtest.py --csv data/banknifty_1month.csv --from 2026-03-16 --to 2026-04-13
  python scripts/run_batch_backtest.py --csv data/banknifty_1month.csv --batch-size 3
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────
#  System prompt for batch analysis
# ─────────────────────────────────────────────────

BATCH_SYSTEM_PROMPT = """You are Jack, an expert BankNifty intraday trader analyzing historical data.

For each day provided, you will:
1. Analyze all 5-minute candles holistically (not tick-by-tick)
2. Identify the best trade opportunity for that day (if any)
3. Specify exact entry, stop loss, and target based only on the provided numbers
4. Write a journal entry with lessons learned

HARD RULES:
- Respond ONLY in valid JSON. Zero prose outside the JSON.
- Never invent prices. Use ONLY numbers from the candle data.
- Stop loss: 40-150 points from entry price.
- Target: minimum 1.5x the stop distance (R:R >= 1.5).
- No entries after 13:30. No entries in first 15 min (before 09:30) unless very strong.
- Only ONE trade per day maximum.
- If no clear setup exists, action = "NO_TRADE".

MARKET CONTEXT:
- BankNifty Indian bank index, trades 50,000-60,000 range.
- Normal daily range: 200-600 pts. Volatile days: 600-1200 pts.
- VWAP: above = bullish bias, below = bearish bias.
- RSI > 60 = momentum, RSI < 40 = selling pressure.
- EMA_20: price above = uptrend, below = downtrend."""


def build_batch_prompt(days: list) -> str:
    """
    Build one giant prompt for a batch of days.

    days: list of dicts, each:
    {
      "date": "2026-03-16",
      "momentum_bias": "BULLISH/BEARISH/NEUTRAL",
      "momentum_pct": 0.5,
      "prior_close": 53000.0,
      "candles": [{"time","open","high","low","close","rsi","ema20","vwap","atr"}, ...]
    }
    """
    lines = [
        "BATCH BACKTEST — BankNifty 5-Minute Analysis",
        f"Days in this batch: {len(days)}",
        "",
        "Analyze each day. For each day identify the single best trade setup.",
        "Consider the full day's price action, not just individual candles.",
        "",
    ]

    for day in days:
        d = day["date"]
        bias = day.get("momentum_bias", "NEUTRAL")
        mom = day.get("momentum_pct", 0.0)
        prior = day.get("prior_close", 0.0)
        candles = day["candles"]

        # Day open/high/low/close
        day_open = candles[0]["open"] if candles else 0
        day_high = max(c["high"] for c in candles) if candles else 0
        day_low  = min(c["low"]  for c in candles) if candles else 0
        day_close = candles[-1]["close"] if candles else 0
        day_range = round(day_high - day_low, 1)

        lines += [
            "=" * 65,
            f"DATE: {d}",
            f"PRE-MARKET BIAS: {bias} | Prior momentum: {mom:+.2f}% over last 3 days | Prior close: {prior:.0f}",
            f"DAY SUMMARY: Open={day_open:.0f}  High={day_high:.0f}  Low={day_low:.0f}  Close={day_close:.0f}  Range={day_range}pts",
            f"CANDLES ({len(candles)} total — 5-min):",
            "",
            "  time | open  | high  |  low  | close | rsi  | ema20 | vwap  | atr",
            "  " + "-" * 68,
        ]

        for c in candles:
            rsi  = f"{c['rsi']:.1f}"  if c['rsi']  is not None else " N/A"
            ema  = f"{c['ema20']:.0f}" if c['ema20'] is not None else "  N/A"
            vwap = f"{c['vwap']:.0f}"  if c['vwap']  is not None else "  N/A"
            atr  = f"{c['atr']:.0f}"   if c['atr']   is not None else "N/A"
            lines.append(
                f"  {c['time']} | {c['open']:5.0f} | {c['high']:5.0f} | {c['low']:5.0f} | "
                f"{c['close']:5.0f} | {rsi:>5} | {ema:>5} | {vwap:>5} | {atr:>3}"
            )
        lines.append("")

    lines += [
        "=" * 65,
        "REQUIRED JSON OUTPUT:",
        "",
        'Return exactly this structure for EACH date in this batch:',
        "",
        """{
  "YYYY-MM-DD": {
    "bias_assessment": "BULLISH|BEARISH|NEUTRAL",
    "day_character": "trending|range_bound|volatile|choppy",
    "trade": {
      "action": "ENTER_LONG|ENTER_SHORT|NO_TRADE",
      "entry_time": "HH:MM or null",
      "entry_price": 52100 or null,
      "stop_loss": 52010 or null,
      "target": 52370 or null,
      "risk_pts": 90 or null,
      "reward_pts": 270 or null,
      "rr_ratio": 3.0 or null,
      "exit_time": "HH:MM or null",
      "exit_price": 52370 or null,
      "outcome": "target_hit|stop_hit|time_exit|no_trade",
      "pnl_pts": 270 or null
    },
    "key_levels": {
      "support": 52000,
      "resistance": 52400,
      "vwap_at_entry": 52080
    },
    "what_worked": "brief explanation of what signal was clear",
    "what_failed": "brief explanation of what was misleading",
    "lesson": "one actionable lesson for next time",
    "confidence": 0.75
  }
}""",
        "",
        "Important: Return ALL dates in one JSON object. No prose outside JSON.",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────
#  Indicator computation
# ─────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute RSI, EMA20, VWAP, ATR on a day's candles."""
    df = df.copy()
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    # EMA 20
    df["ema20"] = close.ewm(span=20, adjust=False).mean().round(2)

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df["rsi"] = (100 - 100 / (1 + rs)).round(2)

    # VWAP (resets each day)
    tp = (high + low + close) / 3
    df["vwap"] = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
    df["vwap"] = df["vwap"].round(2)

    # ATR 14
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=13, adjust=False).mean().round(2)

    return df


# ─────────────────────────────────────────────────
#  Momentum bias
# ─────────────────────────────────────────────────

def get_momentum_bias(all_candles: pd.DataFrame, trade_date) -> dict:
    """Simple 3-day momentum bias from prior closes."""
    prior = all_candles[all_candles["date"] < trade_date].copy()
    if len(prior) < 5:
        return {"momentum_bias": "NEUTRAL", "momentum_pct": 0.0, "prior_close": 0.0}

    daily_closes = prior.groupby("date")["close"].last().sort_index()
    if len(daily_closes) < 2:
        return {"momentum_bias": "NEUTRAL", "momentum_pct": 0.0, "prior_close": float(daily_closes.iloc[-1])}

    n = min(3, len(daily_closes) - 1)
    mom_pct = (daily_closes.iloc[-1] - daily_closes.iloc[-1 - n]) / daily_closes.iloc[-1 - n] * 100
    bias = "BULLISH" if mom_pct > 0.3 else ("BEARISH" if mom_pct < -0.3 else "NEUTRAL")

    return {
        "momentum_bias": bias,
        "momentum_pct": round(float(mom_pct), 3),
        "prior_close": round(float(daily_closes.iloc[-1]), 2),
    }


# ─────────────────────────────────────────────────
#  AI call
# ─────────────────────────────────────────────────

def call_ai(prompt: str, config: dict) -> dict:
    """Make a single AI call and return parsed JSON."""
    from brain.ai_client import AIClient

    ai_cfg = config.get("ai", {})
    provider = ai_cfg.get("intraday_provider", "openai_proxy")
    provider_config = ai_cfg.get(provider, {})

    # Allow bigger response for batch analysis
    provider_config = {**provider_config, "max_tokens": 8000}

    ai = AIClient(provider=provider, config=provider_config)
    response = ai.ask(prompt=prompt, system=BATCH_SYSTEM_PROMPT, response_format="json")
    content = response.get("content", {})
    if isinstance(content, str):
        import re
        # Try to extract JSON
        for pattern in [r"```json\s*([\s\S]+?)\s*```", r"```\s*([\s\S]+?)\s*```", r"(\{[\s\S]+\})"]:
            m = re.search(pattern, content)
            if m:
                try:
                    content = json.loads(m.group(1))
                    break
                except Exception:
                    pass
    return content if isinstance(content, dict) else {}


# ─────────────────────────────────────────────────
#  Journal / results saving
# ─────────────────────────────────────────────────

def save_day_journal(date_str: str, analysis: dict, output_dir: str):
    """Save one day's AI analysis as markdown + JSON."""
    os.makedirs(f"{output_dir}/journal", exist_ok=True)
    os.makedirs(f"{output_dir}/journal/json", exist_ok=True)

    trade = analysis.get("trade", {})
    action    = trade.get("action", "NO_TRADE")
    pnl_pts   = trade.get("pnl_pts")
    rr        = trade.get("rr_ratio")
    entry_t   = trade.get("entry_time", "—")
    exit_t    = trade.get("exit_time", "—")
    outcome   = trade.get("outcome", "—")
    entry_p   = trade.get("entry_price")
    sl        = trade.get("stop_loss")
    tgt       = trade.get("target")

    # Estimate P&L in Rs (lot size 15)
    lot_size = 15
    pnl_rs = round(pnl_pts * lot_size, 0) if pnl_pts is not None else 0

    md_lines = [
        f"# Jack v3 Batch Backtest — {date_str}",
        "",
        f"## Pre-Market Assessment",
        f"**Bias:** {analysis.get('bias_assessment','N/A')} | "
        f"**Day Character:** {analysis.get('day_character','N/A')} | "
        f"**Confidence:** {analysis.get('confidence', 0):.0%}",
        "",
        f"## Trade",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Action | {action} |",
        f"| Entry Time | {entry_t} |",
        f"| Entry Price | {entry_p} |",
        f"| Stop Loss | {sl} |",
        f"| Target | {tgt} |",
        f"| Exit Time | {exit_t} |",
        f"| Outcome | {outcome} |",
        f"| P&L (pts) | {pnl_pts} |",
        f"| P&L (Rs, 1 lot) | {pnl_rs:+.0f} |",
        f"| R:R | {rr} |",
        "",
        f"## Key Levels",
    ]
    kl = analysis.get("key_levels", {})
    md_lines += [
        f"- Support: {kl.get('support','N/A')}",
        f"- Resistance: {kl.get('resistance','N/A')}",
        f"- VWAP at entry: {kl.get('vwap_at_entry','N/A')}",
        "",
        f"## Analysis",
        f"**What worked:** {analysis.get('what_worked','—')}",
        "",
        f"**What failed:** {analysis.get('what_failed','—')}",
        "",
        f"**Lesson:** {analysis.get('lesson','—')}",
    ]

    with open(f"{output_dir}/journal/{date_str}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    with open(f"{output_dir}/journal/json/{date_str}.json", "w", encoding="utf-8") as f:
        json.dump({"date": date_str, **analysis}, f, indent=2)


# ─────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Jack v3 Batch AI Backtest (Fast Mode)")
    parser.add_argument("--csv",    required=True,  help="Path to 5-min candle CSV")
    parser.add_argument("--from",   dest="from_date", help="Start date YYYY-MM-DD")
    parser.add_argument("--to",     dest="to_date",   help="End date YYYY-MM-DD")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--batch-size", type=int, default=5, help="Days per AI call (default: 5)")
    parser.add_argument("--output", default="backtest_results", help="Output directory")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    os.makedirs(args.output, exist_ok=True)

    # ── Load CSV ──────────────────────────────────
    print(f"[Backtest] Loading {args.csv}...")
    df = pd.read_csv(args.csv)
    df.columns = [c.strip().lower() for c in df.columns]

    # Normalize datetime column
    dt_col = next((c for c in ["datetime","date","timestamp"] if c in df.columns), None)
    if not dt_col:
        print("[Backtest] ERROR: No datetime column found.")
        sys.exit(1)
    df["datetime"] = pd.to_datetime(df[dt_col])
    df["date"] = df["datetime"].dt.date
    df = df.sort_values("datetime").reset_index(drop=True)

    # Normalize OHLCV
    for std, variants in {"open":["open","o"],"high":["high","h"],"low":["low","l"],
                          "close":["close","c","ltp"],"volume":["volume","vol","v"]}.items():
        if std not in df.columns:
            for v in variants:
                if v in df.columns:
                    df[std] = df[v]; break

    if "volume" not in df.columns:
        df["volume"] = 1.0

    # ── Filter dates ──────────────────────────────
    all_dates = sorted(df["date"].unique())
    if args.from_date:
        from_d = datetime.strptime(args.from_date, "%Y-%m-%d").date()
        all_dates = [d for d in all_dates if d >= from_d]
    if args.to_date:
        to_d = datetime.strptime(args.to_date, "%Y-%m-%d").date()
        all_dates = [d for d in all_dates if d <= to_d]

    if not all_dates:
        print("[Backtest] No dates in range.")
        sys.exit(1)

    print(f"[Backtest] {len(all_dates)} trading days: {all_dates[0]} -> {all_dates[-1]}")
    print(f"[Backtest] Batch size: {args.batch_size} days per AI call")

    batches = [all_dates[i:i+args.batch_size] for i in range(0, len(all_dates), args.batch_size)]
    print(f"[Backtest] Total AI calls: {len(batches)}")
    print()

    all_results = {}

    for batch_num, batch_dates in enumerate(batches, 1):
        print(f"[Backtest] Batch {batch_num}/{len(batches)}: {batch_dates[0]} to {batch_dates[-1]} ...")

        days_payload = []
        for trade_date in batch_dates:
            day_df = df[df["date"] == trade_date].copy().reset_index(drop=True)
            if len(day_df) < 10:
                print(f"  Skipping {trade_date} (only {len(day_df)} candles)")
                continue

            # Compute indicators
            try:
                day_df = compute_indicators(day_df)
            except Exception as e:
                print(f"  Warning: indicator error on {trade_date}: {e}")

            # Build candle list
            candles = []
            for _, row in day_df.iterrows():
                candles.append({
                    "time":  pd.Timestamp(row["datetime"]).strftime("%H:%M"),
                    "open":  round(float(row["open"]),  2),
                    "high":  round(float(row["high"]),  2),
                    "low":   round(float(row["low"]),   2),
                    "close": round(float(row["close"]), 2),
                    "rsi":   float(row["rsi"])   if "rsi"   in row and pd.notna(row["rsi"])   else None,
                    "ema20": float(row["ema20"])  if "ema20" in row and pd.notna(row["ema20"])  else None,
                    "vwap":  float(row["vwap"])  if "vwap"  in row and pd.notna(row["vwap"])  else None,
                    "atr":   float(row["atr"])   if "atr"   in row and pd.notna(row["atr"])   else None,
                })

            bias_info = get_momentum_bias(df, trade_date)

            days_payload.append({
                "date": str(trade_date),
                **bias_info,
                "candles": candles,
            })

        if not days_payload:
            continue

        # ── One AI call for this batch ────────────
        prompt = build_batch_prompt(days_payload)
        print(f"  Sending {len(days_payload)} days ({sum(len(d['candles']) for d in days_payload)} candles) to AI...")

        try:
            result = call_ai(prompt, config)
        except Exception as e:
            print(f"  ERROR: AI call failed: {e}")
            continue

        if not result:
            print(f"  WARNING: AI returned empty response for batch {batch_num}")
            continue

        # ── Save results ──────────────────────────
        saved = 0
        for date_str, analysis in result.items():
            if not isinstance(analysis, dict):
                continue
            all_results[date_str] = analysis
            save_day_journal(date_str, analysis, args.output)
            saved += 1

        print(f"  Done. {saved} days analyzed and saved.")

    # ── Final summary ─────────────────────────────
    print()
    print("=" * 60)
    print("  BATCH BACKTEST COMPLETE")
    print("=" * 60)

    trades = []
    for date_str, a in sorted(all_results.items()):
        t = a.get("trade", {})
        if t.get("action") != "NO_TRADE" and t.get("pnl_pts") is not None:
            trades.append({
                "date":    date_str,
                "action":  t.get("action"),
                "outcome": t.get("outcome"),
                "pnl_pts": t.get("pnl_pts", 0),
                "pnl_rs":  round(t.get("pnl_pts", 0) * 15, 0),
                "rr":      t.get("rr_ratio"),
                "lesson":  a.get("lesson",""),
            })

    if trades:
        total_pnl_rs = sum(t["pnl_rs"] for t in trades)
        wins  = [t for t in trades if t["pnl_pts"] > 0]
        losses= [t for t in trades if t["pnl_pts"] <= 0]
        win_rate = len(wins) / len(trades) * 100

        print(f"  Days analyzed : {len(all_results)}")
        print(f"  Trades found  : {len(trades)}")
        print(f"  Win rate      : {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
        print(f"  Total P&L     : Rs.{total_pnl_rs:+,.0f}")
        print(f"  Avg per trade : Rs.{total_pnl_rs/len(trades):+,.0f}")
        if wins:
            print(f"  Avg win       : Rs.{sum(t['pnl_rs'] for t in wins)/len(wins):+,.0f}")
        if losses:
            print(f"  Avg loss      : Rs.{sum(t['pnl_rs'] for t in losses)/len(losses):+,.0f}")
        print()

        print("  Per-day breakdown:")
        print(f"  {'Date':<12} {'Action':<14} {'Outcome':<12} {'P&L (Rs)':<12} {'R:R'}")
        print("  " + "-"*60)
        for t in trades:
            rr_str = f"{t['rr']:.1f}" if t['rr'] else "—"
            pnl_str = f"+{t['pnl_rs']:,.0f}" if t['pnl_rs'] >= 0 else f"{t['pnl_rs']:,.0f}"
            print(f"  {t['date']:<12} {t['action']:<14} {t['outcome']:<12} {pnl_str:<12} {rr_str}")

        print()
        print("  Key Lessons:")
        for t in trades[-5:]:  # last 5 lessons
            lesson = t['lesson'].encode('ascii', errors='replace').decode('ascii')
            print(f"  [{t['date']}] {lesson}")
    else:
        print(f"  Days analyzed : {len(all_results)}")
        print("  No trades identified by AI across this period.")

    # Save full results JSON
    summary = {
        "period": {"from": str(all_dates[0]), "to": str(all_dates[-1]), "days": len(all_dates)},
        "trades": trades,
        "daily_analysis": all_results,
    }
    out_path = f"{args.output}/backtest_summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Full results: {out_path}")
    print(f"  Journals:     {args.output}/journal/")
    print("=" * 60)


if __name__ == "__main__":
    main()
