"""
Jack v3 -- Nightly analysis entry point.

Runs after market close (typically 20:00 IST):
  1. lab/ranker.py   -> Rank all strategies by last 20 days performance
  2. AI journal review -> Post-trade analysis with lessons
  3. lab/discoverer.py -> Propose new strategies from missed opportunities

Usage:
  python scripts/run_nightly.py
  python scripts/run_nightly.py --skip-backtest  (faster, uses journal only)
  python scripts/run_nightly.py --provider claude_code
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Jack v3 -- Nightly Analysis")
    parser.add_argument("--skip-backtest", action="store_true",
                        help="Skip backtesting (faster run, uses journal data only)")
    parser.add_argument("--provider", default=None,
                        help="AI provider override (anthropic/openai_proxy/claude_code)")
    parser.add_argument("--config", default="config/settings.yaml", help="Config path")
    args = parser.parse_args()

    import yaml
    with open(args.config) as f:
        config = yaml.safe_load(f)

    if args.provider:
        config["ai"]["nightly_provider"] = args.provider

    print(f"\n{'='*60}")
    print(f"  JACK v3 NIGHTLY ANALYSIS -- {date.today()}")
    print(f"{'='*60}\n")

    from brain.ai_client import create_ai_client
    from journal.logger import JournalLogger

    ai = create_ai_client(config, mode="nightly")
    journal = JournalLogger(
        output_dir=config.get("journal", {}).get("output_dir", "journal/notes")
    )
    recent_entries = journal.get_recent_entries(n=10)

    # ── STEP 1: Strategy ranking ──
    if not args.skip_backtest:
        print("\n[Nightly] STEP 1: Running strategy rankings...")
        try:
            from lab.ranker import run_ranking
            rankings = run_ranking(config)
            top = rankings.get("rankings", [])[:3]
            print("[Nightly] Top 3 strategies:")
            for r in top:
                print(f"  #{r['rank']} {r['strategy']}: win_rate={r['win_rate']:.1f}% trades={r['total_trades']}")
        except Exception as e:
            print(f"[Nightly] Ranking failed: {e}")
            rankings = {}
    else:
        print("[Nightly] STEP 1: Skipping backtest rankings (--skip-backtest)")
        rankings = {}

    # ── STEP 2: AI comprehensive review ──
    print("\n[Nightly] STEP 2: AI comprehensive journal review...")
    try:
        from brain.prompts import nightly_review_prompt, NIGHTLY_SYSTEM_PROMPT

        strategy_perf = rankings.get("rankings", [])
        prompt = nightly_review_prompt(
            journal_entries=recent_entries,
            strategy_performance=strategy_perf,
        )

        response = ai.ask(
            prompt=prompt,
            system=NIGHTLY_SYSTEM_PROMPT,
            response_format="json",
        )

        import json
        content = response.get("content", {})
        if isinstance(content, str):
            content = json.loads(content)

        print(f"\n[Nightly] AI Performance Summary:")
        print(f"  {content.get('performance_summary', 'N/A')}")
        print(f"\n[Nightly] Tomorrow's bias: {content.get('tomorrow_bias', 'NEUTRAL')}")
        print(f"  {content.get('tomorrow_note', '')}")

        if content.get("parameter_adjustments"):
            print(f"\n[Nightly] Suggested parameter adjustments:")
            for adj in content["parameter_adjustments"]:
                print(f"  {adj.get('strategy')}.{adj.get('parameter')}: "
                      f"{adj.get('current_value')} -> {adj.get('suggested_value')} ({adj.get('reasoning')})")

        # Save nightly review
        os.makedirs("journal/notes/json", exist_ok=True)
        review_path = f"journal/notes/json/nightly_{date.today()}.json"
        with open(review_path, "w") as f:
            json.dump(content, f, indent=2)
        print(f"\n[Nightly] Review saved: {review_path}")

    except Exception as e:
        print(f"[Nightly] AI review failed: {e}")

    # ── STEP 3: Strategy discovery ──
    print("\n[Nightly] STEP 3: Strategy discovery from missed opportunities...")
    try:
        from lab.discoverer import StrategyDiscoverer
        discoverer = StrategyDiscoverer(ai, config)
        proposal = discoverer.discover(recent_entries)
        if proposal:
            print(f"\n[Nightly] New strategy proposed: {proposal.get('name')}")
            print(f"  Description: {proposal.get('description')}")
            print(f"  Confidence: {proposal.get('confidence')}")
            print(f"  Expected win rate: {proposal.get('expected_win_rate_pct')}%")
            print(f"  Saved to: lab/proposals/")
        else:
            print("[Nightly] No new strategies proposed.")
    except Exception as e:
        print(f"[Nightly] Discovery failed: {e}")

    print(f"\n[Nightly] Analysis complete. Check lab/proposals/ and journal/notes/json/ for outputs.")


if __name__ == "__main__":
    main()
