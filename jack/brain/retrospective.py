"""
AI Retrospective Agent.

Two modes of operation:

1. DUMP mode (default):
   Compresses journal logs into brain/knowledge/pending_analysis.json
   and prints a summary to stdout so Claude Code (or a human) can read
   it and write back an insight file.

   Usage:
       python -m brain.retrospective --dump
       python -m brain.retrospective --dump --from 2015-01-01 --to 2015-06-30

2. APPLY mode:
   Reads brain/knowledge/pending_analysis.json, calls Claude API,
   saves insight. Only use this if you have an ANTHROPIC_API_KEY set.

   Usage:
       python -m brain.retrospective --apply

3. SAVE mode:
   Save a pre-written insight JSON directly (used by Claude Code agent
   to write the insight after reading the pending analysis).

   Usage:
       python -m brain.retrospective --save path/to/insight.json

The simulator's _build_briefing() loads all saved insights at startup
and passes scorer_weight_adjustments to the StrategyScorer.
"""

import os
import json
import glob
import argparse
from typing import Optional

BATCH_SIZE = 100

_HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL_LOGS_DIR = os.path.join(_HERE, "..", "journal", "logs")
KNOWLEDGE_DIR = os.path.join(_HERE, "knowledge")


# ---------------------------------------------------------------------------
# Journal loading & compression
# ---------------------------------------------------------------------------

def _load_journal_batch(
    journal_logs_dir: str,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
) -> list[dict]:
    pattern = os.path.join(journal_logs_dir, "????-??-??.json")
    files = sorted(glob.glob(pattern))
    loaded = []
    for f in files:
        fname = os.path.basename(f).replace(".json", "")
        if after_date and fname <= after_date:
            continue
        if before_date and fname > before_date:
            continue
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                data["_file_date"] = fname
                loaded.append(data)
        except Exception:
            continue
    return loaded


def _compress_log(log: dict) -> dict:
    """Reduce a daily log to the fields needed for analysis."""
    trades = log.get("trades", [])
    compressed_trades = []
    for t in trades:
        compressed_trades.append({
            "strategy": t.get("strategy"),
            "direction": t.get("direction"),
            "entry_time": t.get("entry_time"),
            "exit_time": t.get("exit_time"),
            "net_pnl": t.get("net_pnl"),
            "exit_reason": t.get("exit_reason"),
            "r_multiple": t.get("r_multiple"),
        })

    scan = log.get("morning_scan", {})
    fh = log.get("first_hour", {})
    review = log.get("daily_review", {})
    briefing = log.get("briefing", {})
    filters = briefing.get("filters", {})
    global_ctx = briefing.get("global", {})

    return {
        "date": log.get("date") or log.get("_file_date"),
        "day_of_week": log.get("day_of_week"),
        "gap_pct": scan.get("gap_pct"),
        "gap_type": scan.get("gap_type"),
        "regime": scan.get("regime"),
        "atr": scan.get("atr"),
        "rsi": scan.get("rsi"),
        "fh_return_pct": fh.get("FH_Return"),
        "fh_direction": fh.get("FH_Direction"),
        "fh_strong": fh.get("FH_Strong"),
        "trades": compressed_trades,
        "total_pnl": review.get("total_pnl"),
        "no_trade_reason": review.get("no_trade_reason"),
        "trade_blocked": filters.get("trade_blocked"),
        "combined_long_mult": filters.get("combined_long_multiplier"),
        "combined_short_mult": filters.get("combined_short_multiplier"),
        # Global pre-market context
        "sp500_chg": global_ctx.get("sp500_pct_chg"),
        "india_vix": global_ctx.get("india_vix"),
        "us_sentiment": global_ctx.get("us_sentiment"),
        "vix_regime": global_ctx.get("vix_regime"),
    }


def build_analysis_payload(
    journal_logs_dir: str,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
) -> Optional[dict]:
    """Load and compress journal logs into the analysis payload."""
    logs = _load_journal_batch(journal_logs_dir, after_date=after_date, before_date=before_date)
    if not logs:
        return None

    compressed = [_compress_log(l) for l in logs]

    # Quick stats for the summary
    total = len(compressed)
    no_trade = sum(1 for d in compressed if not d["trades"])
    trade_days = total - no_trade
    all_trades = [t for d in compressed for t in d["trades"]]
    wins = sum(1 for t in all_trades if (t.get("net_pnl") or 0) > 0)
    win_rate = wins / len(all_trades) * 100 if all_trades else 0

    strat_counts: dict[str, dict] = {}
    for t in all_trades:
        s = t.get("strategy", "unknown")
        if s not in strat_counts:
            strat_counts[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
        strat_counts[s]["trades"] += 1
        if (t.get("net_pnl") or 0) > 0:
            strat_counts[s]["wins"] += 1
        strat_counts[s]["pnl"] += t.get("net_pnl") or 0

    return {
        "summary": {
            "total_days": total,
            "trade_days": trade_days,
            "no_trade_days": no_trade,
            "no_trade_pct": round(no_trade / total * 100, 1) if total else 0,
            "total_trades": len(all_trades),
            "win_rate_pct": round(win_rate, 1),
            "strategy_breakdown": strat_counts,
        },
        "days": compressed,
        "batch_start": logs[0]["_file_date"],
        "batch_end": logs[-1]["_file_date"],
    }


# ---------------------------------------------------------------------------
# DUMP: write pending_analysis.json for Claude Code to read
# ---------------------------------------------------------------------------

def dump_for_claudecode(
    journal_logs_dir: str = JOURNAL_LOGS_DIR,
    knowledge_dir: str = KNOWLEDGE_DIR,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
) -> str:
    """
    Write brain/knowledge/pending_analysis.json.
    Prints a concise summary so the Claude Code agent knows what to analyze.

    Returns path to the written file.
    """
    os.makedirs(knowledge_dir, exist_ok=True)
    payload = build_analysis_payload(journal_logs_dir, after_date, before_date)
    if not payload:
        print("[Retrospective] No journal logs found.")
        return ""

    out_path = os.path.join(knowledge_dir, "pending_analysis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    s = payload["summary"]
    print(f"\n[Retrospective] Pending analysis written to:")
    print(f"  {out_path}")
    print(f"\nSummary ({s['total_days']} days, {payload['batch_start']} -> {payload['batch_end']}):")
    print(f"  Trade days   : {s['trade_days']} ({100 - s['no_trade_pct']:.1f}%)")
    print(f"  No-trade days: {s['no_trade_days']} ({s['no_trade_pct']:.1f}%)")
    print(f"  Total trades : {s['total_trades']}")
    print(f"  Win rate     : {s['win_rate_pct']:.1f}%")
    print(f"\nStrategy breakdown:")
    for strat, stats in sorted(s["strategy_breakdown"].items()):
        wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] else 0
        print(f"  {strat:25s}: {stats['trades']:4d} trades  {wr:.1f}% WR  Rs {stats['pnl']:+,.0f}")
    print(f"\nClaude Code: read {out_path} and run brain.retrospective.save_insight(insight_dict)")
    return out_path


# ---------------------------------------------------------------------------
# SAVE: write an insight file (called by Claude Code after analysis)
# ---------------------------------------------------------------------------

def save_insight(insight: dict, knowledge_dir: str = KNOWLEDGE_DIR) -> str:
    """
    Persist a completed insight dict to brain/knowledge/YYYY-MM-DD_insight.json.
    Called by Claude Code after it reads pending_analysis.json and reasons over it.

    Args:
        insight: The structured insight dict (see INSIGHT_SCHEMA below).
        knowledge_dir: Where to write.

    Returns:
        Path to saved file.
    """
    os.makedirs(knowledge_dir, exist_ok=True)
    batch_end = insight.get("batch_end", "unknown")
    out_path = os.path.join(knowledge_dir, f"{batch_end}_insight.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(insight, f, indent=2, default=str)
    print(f"[Retrospective] Insight saved: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# APPLY: call Claude API directly (requires ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the trading brain for JACK, an automated Bank Nifty intraday futures system.
Analyze the trading journal batch and return ONLY a JSON object matching this schema:

{
  "batch_start": "YYYY-MM-DD",
  "batch_end": "YYYY-MM-DD",
  "total_days": int,
  "no_trade_days": int,
  "no_trade_root_causes": ["<cause>"],
  "win_rate_by_strategy": {"strategy_name": float},
  "best_performing_conditions": ["<condition>"],
  "worst_performing_conditions": ["<condition>"],
  "scorer_weight_adjustments": {
    "first_hour_verdict": float,
    "gap_fill": float,
    "bb_squeeze": float,
    "gap_up_fade": float,
    "vwap_reversion": float
  },
  "filter_threshold_recommendation": {
    "combined_multiplier_min": float,
    "reason": "string"
  },
  "key_learnings": ["<learning>"],
  "action_items": ["<concrete change>"]
}

Return ONLY the JSON. No markdown, no explanation."""


def apply_with_api(
    journal_logs_dir: str = JOURNAL_LOGS_DIR,
    knowledge_dir: str = KNOWLEDGE_DIR,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
) -> Optional[dict]:
    """Call Claude API directly. Requires ANTHROPIC_API_KEY env var."""
    try:
        import anthropic
    except ImportError:
        print("[Retrospective] anthropic not installed: pip install anthropic")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[Retrospective] ANTHROPIC_API_KEY not set. Use --dump mode instead.")
        return None

    payload = build_analysis_payload(journal_logs_dir, after_date, before_date)
    if not payload:
        return None

    client = anthropic.Anthropic(api_key=api_key)
    user_msg = f"Analyze these {len(payload['days'])} trading days:\n\n" + json.dumps(
        payload["days"], indent=2, default=str
    )

    print("[Retrospective] Calling Claude API...")
    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        print(f"[Retrospective] API call failed: {e}")
        return None

    raw = response.content[0].text.strip()
    try:
        insight = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[Retrospective] Failed to parse response: {e}\n{raw[:300]}")
        return None

    return save_insight(insight, knowledge_dir) and insight


# ---------------------------------------------------------------------------
# Insight loading (used by simulator and scorer)
# ---------------------------------------------------------------------------

def load_all_insights(knowledge_dir: str = KNOWLEDGE_DIR) -> list[dict]:
    """Load all saved insight files sorted by date."""
    pattern = os.path.join(knowledge_dir, "*_insight.json")
    insights = []
    for f in sorted(glob.glob(pattern)):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                insights.append(json.load(fh))
        except Exception:
            continue
    return insights


def get_scorer_adjustments(knowledge_dir: str = KNOWLEDGE_DIR) -> dict[str, float]:
    """Return the most recent scorer weight adjustments from saved insights."""
    insights = load_all_insights(knowledge_dir)
    if not insights:
        return {}
    return insights[-1].get("scorer_weight_adjustments", {})


def get_filter_threshold(knowledge_dir: str = KNOWLEDGE_DIR, default: float = 0.3) -> float:
    """Return the recommended combined_multiplier minimum from the latest insight."""
    insights = load_all_insights(knowledge_dir)
    if not insights:
        return default
    rec = insights[-1].get("filter_threshold_recommendation", {})
    return rec.get("combined_multiplier_min", default)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

INSIGHT_SCHEMA = {
    "batch_start": "YYYY-MM-DD",
    "batch_end": "YYYY-MM-DD",
    "total_days": 0,
    "no_trade_days": 0,
    "no_trade_root_causes": [],
    "win_rate_by_strategy": {},
    "best_performing_conditions": [],
    "worst_performing_conditions": [],
    "scorer_weight_adjustments": {
        "first_hour_verdict": 1.0,
        "gap_fill": 1.0,
        "bb_squeeze": 1.0,
        "gap_up_fade": 1.0,
        "vwap_reversion": 1.0,
    },
    "filter_threshold_recommendation": {"combined_multiplier_min": 0.3, "reason": ""},
    "key_learnings": [],
    "action_items": [],
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jack AI Retrospective")
    parser.add_argument("--dump", action="store_true",
                        help="Write pending_analysis.json for Claude Code to analyze")
    parser.add_argument("--apply", action="store_true",
                        help="Call Claude API directly (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--save", metavar="FILE",
                        help="Save a pre-written insight JSON file to knowledge/")
    parser.add_argument("--from", dest="from_date", default=None)
    parser.add_argument("--to", dest="to_date", default=None)
    parser.add_argument("--journal-dir", default=JOURNAL_LOGS_DIR)
    parser.add_argument("--knowledge-dir", default=KNOWLEDGE_DIR)
    args = parser.parse_args()

    if args.save:
        with open(args.save, "r", encoding="utf-8") as f:
            insight = json.load(f)
        save_insight(insight, args.knowledge_dir)

    elif args.apply:
        apply_with_api(
            journal_logs_dir=args.journal_dir,
            knowledge_dir=args.knowledge_dir,
            after_date=args.from_date,
            before_date=args.to_date,
        )

    else:
        # Default: dump mode
        dump_for_claudecode(
            journal_logs_dir=args.journal_dir,
            knowledge_dir=args.knowledge_dir,
            after_date=args.from_date,
            before_date=args.to_date,
        )
